"""指令自动解析器 - 将任意纯文本外呼指令解析为结构化JSON"""

import json
import re
from pathlib import Path
from ..llm_client import DeepSeekClient


INSTRUCTION_PARSE_PROMPT = """你是一个外呼任务指令解析器。请将以下外呼任务指令解析为结构化JSON。

【输入指令】
{raw_instruction}

【输出要求】
请严格按以下JSON格式输出（不要markdown代码块，不要任何解释）：
{{
  "task_id": "简短英文ID，用下划线连接",
  "role": "模型扮演的角色",
  "goal": "本次电话的核心目标（一句话）",
  "opening_line": "开场白原文",
  "variables": ["指令中出现的变量，如${{name}}"],
  "flow": [
    {{
      "step_id": "step_1_xxx",
      "condition": "触发条件",
      "action": "执行动作",
      "branches": [
        {{"condition": "分支条件", "action": "分支动作"}}
      ]
    }}
  ],
  "faq": [
    {{
      "question_type": "问题类型关键词",
      "answer": "标准答案"
    }}
  ],
  "constraints": ["约束1", "约束2"],
  "forbidden": ["禁用词1", "禁用词2"],
  "max_reply_length": 数字,
  "end_conditions": ["结束条件1", "结束条件2"]
}}

【解析规则】
1. flow：按指令中的步骤顺序提取，每个步骤包含触发条件和执行动作。如果有分支（如"若是→...；若不是→..."），放在branches中
2. faq：从Knowledge Points、FAQ、知识点等部分提取
3. constraints：从Constraints、约束、规则等部分提取所有限制条件
4. forbidden：从约束中提取明确的禁用词（如"不说XX"、"不能说XX"）
5. max_reply_length：从约束中提取字数限制数字。如果是范围（如15-20字），取上限
6. end_conditions：提取导致通话结束的条件（如"用户说在开车"、"用户坚持拒绝"）
7. opening_line：保留原文，包括变量占位符
8. variables：提取所有${{xxx}}格式的变量名"""


class InstructionParser:
    def __init__(self, llm: DeepSeekClient = None):
        self.llm = llm or DeepSeekClient()

    def parse(self, raw_instruction: str) -> dict:
        """将纯文本指令解析为结构化JSON"""
        prompt = INSTRUCTION_PARSE_PROMPT.format(raw_instruction=raw_instruction)

        result = self.llm.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.2,
            timeout=40,
        )

        # 尝试解析JSON（多种容错策略）
        parsed = self._robust_json_parse(result)

        # 后处理：确保必要字段存在
        parsed = self._post_process(parsed, raw_instruction)
        return parsed

    def _robust_json_parse(self, text: str) -> dict:
        """健壮的JSON解析，支持多种格式"""
        import re

        # 策略1：直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略2：去掉 markdown 代码块
        cleaned = re.sub(r'```(?:json)?\s*', '', text)
        cleaned = re.sub(r'```\s*$', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 策略3：提取最外层 {}
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # 策略4：修复常见问题（尾部逗号、单引号）
        if match:
            fixed = match.group()
            fixed = re.sub(r',\s*([}\]])', r'\1', fixed)  # 去尾部逗号
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

        raise ValueError(f"无法解析LLM输出为JSON，原始输出前200字: {text[:200]}")

    def _post_process(self, parsed: dict, raw_instruction: str) -> dict:
        """后处理：补全缺失字段、修正格式、确保评测空间充分"""
        # 确保必要字段
        defaults = {
            "task_id": "unknown_task",
            "role": "",
            "goal": "",
            "opening_line": "",
            "variables": [],
            "flow": [],
            "faq": [],
            "constraints": [],
            "forbidden": [],
            "max_reply_length": 30,
            "end_conditions": [],
        }
        for key, default in defaults.items():
            if key not in parsed:
                parsed[key] = default

        # 如果没提取到max_reply_length，从constraints中尝试提取
        if parsed["max_reply_length"] == 30:
            for c in parsed["constraints"]:
                match = re.search(r'(\d+)\s*[个字字符]', c)
                if match:
                    parsed["max_reply_length"] = int(match.group(1))
                    break

        # 如果没提取到forbidden，从constraints中尝试提取
        if not parsed["forbidden"]:
            for c in parsed["constraints"]:
                match = re.search(r'不[说能用使]+[""]?(.+?)[""]?(?:等|$)', c)
                if match:
                    words = re.split(r'[、，,"""]+', match.group(1))
                    parsed["forbidden"].extend([w.strip() for w in words if w.strip()])

        # Ensure max_reply_length is reasonable (never 0)
        mrl = parsed.get('max_reply_length')
        if not mrl or mrl <= 0:
            parsed['max_reply_length'] = 30

        # 关键：确保flow至少有3步，否则评测空间太小
        if len(parsed.get("flow", [])) < 3:
            parsed["flow"] = self._ensure_minimum_flow(parsed, raw_instruction)

        # 关键：从原始指令提取隐含约束
        if len(parsed.get("constraints", [])) < 2:
            parsed["constraints"] = self._extract_implicit_constraints(parsed, raw_instruction)

        # 关键：从原始指令提取隐含FAQ
        if not parsed.get("faq") and len(raw_instruction) > 200:
            parsed["faq"] = self._extract_implicit_faq(parsed, raw_instruction)

        return parsed

    def _ensure_minimum_flow(self, parsed: dict, raw_instruction: str) -> list[dict]:
        """确保flow至少覆盖外呼核心步骤，避免评测空间过小"""
        existing = parsed.get("flow", [])
        goal = parsed.get("goal", "")
        role = parsed.get("role", "")

        # 从原始指令中提取关键动作词
        action_patterns = [
            (r"通知.*?(?:签署|生效|完成|到期)", "通知关键事项"),
            (r"提醒.*?(?:完成|配送|任务|操作)", "提醒执行任务"),
            (r"确认.*?(?:身份|信息|意向)", "确认用户身份/意向"),
            (r"说明.*?(?:规则|要求|条件|流程)", "说明规则要求"),
            (r"(?:退出|结束).*?(?:规则|条件|方式)", "告知退出方式"),
        ]

        extracted_actions = []
        for pattern, label in action_patterns:
            if re.search(pattern, raw_instruction):
                extracted_actions.append(label)

        # 构建最小完整流程
        flow = []
        if existing:
            flow.extend(existing)

        # 补充标准外呼流程步骤
        standard_steps = [
            {"step_id": "step_opening", "condition": "通话接通", "action": "自我介绍并说明来电目的"},
            {"step_id": "step_identity", "condition": "用户接听", "action": "确认对方身份"},
            {"step_id": "step_inform_main", "condition": "身份确认后", "action": goal[:50] if goal else "说明核心任务内容"},
            {"step_id": "step_confirm", "condition": "信息传达完毕", "action": "确认用户理解并询问意向"},
            {"step_id": "step_closing", "condition": "用户确认或拒绝", "action": "礼貌结束通话"},
        ]

        # 如果有提取到的动作，插入到inform和confirm之间
        if extracted_actions:
            for i, action in enumerate(extracted_actions[:3]):
                standard_steps.insert(3 + i, {
                    "step_id": f"step_detail_{i+1}",
                    "condition": "用户配合后",
                    "action": action,
                })

        # 合并：保留已有步骤，补充缺失
        existing_actions = set(s.get("action", "")[:10] for s in flow)
        for step in standard_steps:
            if step["action"][:10] not in existing_actions:
                flow.append(step)
                existing_actions.add(step["action"][:10])

        return flow[:8]

    def _extract_implicit_constraints(self, parsed: dict, raw_instruction: str) -> list[str]:
        """从原始指令中提取隐含约束"""
        existing = list(parsed.get("constraints", []))

        # 常见外呼约束模式
        constraint_patterns = [
            (r"(\d+)[字个]", "每次回复不超过{0}字"),
            (r"口语化|自然|像.*?说话", "回复需口语化，适合电话沟通"),
            (r"不[能得要].*?(承诺|保证|绝对)", "不得作绝对化承诺"),
            (r"超出.*?(职责|范围|能力)", "超出职责范围的问题需转人工或说明无法处理"),
            (r"(?:敏感|隐私|身份证|银行卡)", "不索要用户敏感信息"),
        ]

        for pattern, template in constraint_patterns:
            match = re.search(pattern, raw_instruction)
            if match:
                constraint_text = template.format(match.group(1)) if "{0}" in template else template
                if constraint_text not in existing:
                    existing.append(constraint_text)

        # 外呼通用约束（如果原始指令暗示外呼场景）
        if any(kw in raw_instruction for kw in ["外呼", "电话", "通话", "骑手", "客服"]):
            universal = [
                "用户明确拒绝时需礼貌退出",
                "不诱导用户绕过官方渠道",
            ]
            for u in universal:
                if u not in existing:
                    existing.append(u)

        return existing

    def _extract_implicit_faq(self, parsed: dict, raw_instruction: str) -> list[dict]:
        """从原始指令中提取隐含FAQ知识点"""
        faq = []

        # 匹配知识点模式
        faq_patterns = [
            (r"(?:如何|怎么).*?(?:查看|查询|确认|退出|取消)", "question"),
            (r"(?:什么时候|多久).*?(?:生效|到期|开始|结束)", "question"),
            (r"(?:最低|最少|至少).*?(?:要求|标准|条件)", "question"),
        ]

        for pattern, _ in faq_patterns:
            match = re.search(pattern, raw_instruction)
            if match:
                question_text = match.group().strip()
                # Try to find answer nearby
                answer_context = raw_instruction[max(0, match.start()-50):match.end()+100]
                faq.append({
                    "question_type": question_text[:30],
                    "answer": answer_context[:60],
                })

        return faq[:5]

    def parse_and_save(self, raw_instruction: str, output_dir: str = None) -> dict:
        """解析并保存到文件"""
        parsed = self.parse(raw_instruction)

        if output_dir is None:
            output_dir = Path(__file__).parent.parent.parent / "data" / "processed"
        else:
            output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / f"{parsed['task_id']}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)

        return parsed

    def parse_batch(self, instructions: list[str], output_dir: str = None) -> list[dict]:
        """批量解析多条指令"""
        results = []
        for i, inst in enumerate(instructions):
            print(f"  解析指令 {i+1}/{len(instructions)}...")
            try:
                parsed = self.parse_and_save(inst, output_dir)
                results.append(parsed)
                print(f"    ✓ {parsed['task_id']}: {parsed['goal'][:30]}")
            except Exception as e:
                print(f"    ✗ 解析失败: {e}")
                results.append({"error": str(e)})
        return results
