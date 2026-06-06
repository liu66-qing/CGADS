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
            max_tokens=4096,
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
        """后处理：补全缺失字段、修正格式"""
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
                # 匹配 "不说/不能说/禁止说 X、Y、Z"
                match = re.search(r'不[说能用使]+["“]?(.+?)["”]?(?:等|$)', c)
                if match:
                    words = re.split(r'[、，,"“”""]+', match.group(1))
                    parsed["forbidden"].extend([w.strip() for w in words if w.strip()])

        return parsed

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
