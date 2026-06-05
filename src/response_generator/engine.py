"""对话引擎 v2 - 接入 DeepSeek，三段式推理：状态跟踪 → 动作决策 → 回复生成 → 约束检查"""

import json
from pathlib import Path

from ..checkers import run_all_checks, is_compliant, get_violations
from ..llm_client import DeepSeekClient


SYSTEM_PROMPT_TEMPLATE = """你是一个外呼电话AI助手，严格按照任务指令进行电话对话。

【角色】{role}
【目标】{goal}

【对话流程】
{flow_description}

【知识点FAQ】
{faq_description}

【硬性约束】
{constraints_description}

【核心规则】
1. 每次回复不超过{max_length}个字
2. 语气自然口语化，像真人打电话，简短直接
3. 严格遵循对话流程
4. 不编造任务指令中没有的信息
5. 禁用词（绝对不能出现）：{forbidden_words}
6. 只输出回复本身，不要任何解释、标注或前缀"""


STATE_TRACKING_PROMPT = """你是对话状态分析器。根据任务流程和对话历史，分析当前状态。

【任务流程】
{flow_description}

【对话历史】
{dialogue_history}

【用户最新输入】
{user_input}

请用JSON格式输出（不要markdown代码块）：
{{"current_step": "当前所在步骤ID", "user_intent": "用户意图简述", "triggered_faq": "触发的FAQ类型或null", "should_end": false, "next_action": "下一步应执行的动作"}}"""


REWRITE_PROMPT = """你之前的回复「{reply}」违反了规则：{violations}。
请重新生成一句合规回复。要求：不超过{max_length}字，口语化，不说禁用词。
只输出回复，不要解释。"""


class DialogueEngine:
    def __init__(self, task_config: dict, llm: DeepSeekClient = None):
        self.config = task_config
        self.llm = llm or DeepSeekClient()
        self.history: list[dict] = []  # {"role": "user"/"assistant", "content": "..."}
        self.state_history: list[dict] = []  # 每轮的状态分析
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        flow_desc = "\n".join(
            f"  {i+1}. 当{s['condition']}时 → {s['action']}"
            for i, s in enumerate(self.config["flow"])
        )
        faq_desc = "\n".join(
            f"  - Q: {f['question_type']} → A: {f['answer']}"
            for f in self.config.get("faq", [])
        ) or "  无"
        constraints_desc = "\n".join(f"  - {c}" for c in self.config["constraints"])
        forbidden = "、".join(self.config.get("forbidden", [])) or "无"

        return SYSTEM_PROMPT_TEMPLATE.format(
            role=self.config["role"],
            goal=self.config["goal"],
            flow_description=flow_desc,
            faq_description=faq_desc,
            constraints_description=constraints_desc,
            max_length=self.config.get("max_reply_length", 30),
            forbidden_words=forbidden,
        )

    def get_opening(self, variables: dict = None) -> str:
        """返回开场白，自动替换变量"""
        opening = self.config["opening_line"]
        opening = self._fill_variables(opening, variables)
        self.history.append({"role": "assistant", "content": opening})
        return opening

    def _fill_variables(self, text: str, variables: dict = None) -> str:
        """替换 ${xxx} 变量为实际值或合理默认值"""
        import re
        # 默认值映射
        defaults = {
            "rider_name": "王师傅",
            "member_name": "张先生",
            "name": "李先生",
            "expire_date": "6月30日",
            "X": "8", "Y": "5", "Z": "22", "W": "7",
        }
        if variables:
            defaults.update(variables)

        def replace_var(match):
            var_name = match.group(1)
            return defaults.get(var_name, var_name)

        return re.sub(r'\$\{(\w+)\}', replace_var, text)

    def track_state(self, user_input: str) -> dict:
        """状态跟踪：判断当前在流程哪一步"""
        flow_desc = "\n".join(
            f"  - {s['step_id']}: 当{s['condition']}时 → {s['action']}"
            for s in self.config["flow"]
        )
        history_text = "\n".join(
            f"  {'用户' if h['role']=='user' else '客服'}: {h['content']}"
            for h in self.history[-10:]  # 最近10轮
        )

        prompt = STATE_TRACKING_PROMPT.format(
            flow_description=flow_desc,
            dialogue_history=history_text or "（无历史）",
            user_input=user_input,
        )

        try:
            result = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.3,
            )
            # 尝试解析JSON
            state = json.loads(result)
        except (json.JSONDecodeError, Exception):
            state = {
                "current_step": "unknown",
                "user_intent": user_input[:20],
                "triggered_faq": None,
                "should_end": False,
                "next_action": "继续对话",
            }

        self.state_history.append(state)
        return state

    def generate_reply(self, user_input: str, max_retries: int = 2) -> dict:
        """
        完整推理链路：
        1. 状态跟踪
        2. LLM 生成回复
        3. 约束检查
        4. 不合规则重写
        """
        # 记录用户输入
        self.history.append({"role": "user", "content": user_input})

        # Step 1: 状态跟踪
        state = self.track_state(user_input)

        # 获取历史助手回复（用于重复检查）
        assistant_replies = [h["content"] for h in self.history if h["role"] == "assistant"]

        # Step 2 & 3: 生成 + 检查循环
        for attempt in range(max_retries + 1):
            if attempt == 0:
                # 首次生成
                reply = self.llm.chat(
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        *self.history,
                    ],
                    max_tokens=1024,
                    temperature=0.7,
                )
            else:
                # 重写：告诉模型哪里违规
                violation_desc = "；".join(v.message for v in violations)
                rewrite_msg = REWRITE_PROMPT.format(
                    reply=reply,
                    violations=violation_desc,
                    max_length=self.config.get("max_reply_length", 30),
                )
                reply = self.llm.chat(
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        *self.history,
                        {"role": "user", "content": rewrite_msg},
                    ],
                    max_tokens=1024,
                    temperature=0.5,
                )

            # Step 3: 约束检查
            check_results = run_all_checks(
                reply=reply,
                user_input=user_input,
                history=assistant_replies,
                task_config=self.config,
            )

            if is_compliant(check_results):
                self.history.append({"role": "assistant", "content": reply})
                return {
                    "reply": reply,
                    "state": state,
                    "compliant": True,
                    "checks": [{"rule": r.rule_name, "passed": r.passed, "msg": r.message} for r in check_results],
                    "attempts": attempt + 1,
                }

            violations = get_violations(check_results)

        # 重试耗尽
        self.history.append({"role": "assistant", "content": reply})
        return {
            "reply": reply,
            "state": state,
            "compliant": False,
            "violations": [{"rule": v.rule_name, "msg": v.message} for v in violations],
            "attempts": max_retries + 1,
        }

    def should_end_call(self) -> bool:
        """根据最近状态判断是否应结束通话"""
        if self.state_history:
            return self.state_history[-1].get("should_end", False)
        return False

    def get_dialogue_history(self) -> list[dict]:
        return self.history.copy()

    def reset(self):
        self.history = []
        self.state_history = []


def load_task_config(task_path: str) -> dict:
    with open(task_path, "r", encoding="utf-8") as f:
        return json.load(f)
