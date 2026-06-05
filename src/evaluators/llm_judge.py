"""LLM 裁判评测模块 - Reasoning-First + TD-EVAL 风格逐轮 + 整体评测

升级（2026-06-04）：
- 采用Anthropic官方Eval最佳实践：<thinking>推理 + <result>评分
- 支持0分="无法判断"避免Judge瞎猜
- 参考: https://docs.anthropic.com/en/docs/build-with-claude/develop-tests
"""

import json
import re
from dataclasses import dataclass, asdict
from ..llm_client import DeepSeekClient


def _extract_result_json(text: str) -> dict:
    """从<result>...</result>标签中提取JSON，fallback到原始解析。"""
    match = re.search(r'<result>\s*(.*?)\s*</result>', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r'```(?:json)?\s*', '', text)
    cleaned = re.sub(r'```\s*$', '', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        fixed = re.sub(r',\s*([}\]])', r'\1', m.group())
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("Cannot parse judge output", text, 0)


@dataclass
class TurnScore:
    """单轮评分"""
    turn: int
    user_input: str
    agent_reply: str
    cohesion: int        # 1-5 对话连贯性
    knowledge: int       # 1-5 知识一致性
    compliance: int      # 1-5 政策合规性
    progress: int        # 1-5 任务推进
    comment: str         # 评语


@dataclass
class DialogueScore:
    """整通对话评分"""
    task_completed: bool       # 任务是否完成
    natural_ending: bool       # 是否自然结束
    faq_handled: bool          # FAQ是否正确处理
    flow_followed: bool        # 是否遵循流程
    user_experience: int       # 1-5 用户体验
    overall: int               # 1-5 综合评分
    strengths: list[str]       # 优点
    weaknesses: list[str]      # 不足
    suggestions: list[str]     # 改进建议


TURN_EVAL_PROMPT = """你是一个严格的外呼对话质检员。请对客服的这轮回复打分。

【任务背景】
角色：{role}
目标：{goal}

【对话流程要求】
{flow_description}

【知识点FAQ】
{faq_description}

【约束】
{constraints}

【对话上下文（最近几轮）】
{context}

【本轮】
用户：{user_input}
客服：{agent_reply}

请从4个维度打分（1-5分）。先在<thinking>标签中写出推理过程，再在<result>标签中输出JSON：

<thinking>
[为什么给这个分？具体分析每个维度]
</thinking>

<result>
{{"cohesion": 分数, "knowledge": 分数, "compliance": 分数, "progress": 分数, "comment": "一句话评语"}}
</result>

评分标准：
- cohesion（连贯性）：回复是否接住了用户的话，是否答非所问
- knowledge（知识一致性）：是否符合FAQ，是否编造了不存在的信息
- compliance（政策合规）：是否遵守约束（字数、禁用词、流程）
- progress（任务推进）：是否在推进任务目标完成
- 如信息不足无法判断某维度，输出0分"""


DIALOGUE_EVAL_PROMPT = """你是一个严格的外呼对话质检主管。请对这通完整电话进行整体评估。

【任务背景】
角色：{role}
目标：{goal}
流程：{flow_summary}

【完整对话记录】
{full_dialogue}

【硬约束检查结果】
合规轮次：{compliant_turns}/{total_turns}

先在<thinking>标签中推理整体评价依据，再在<result>标签中输出JSON：

<thinking>
[整体推理：任务是否完成？流程是否正确？哪些方面做得好/差？]
</thinking>

<result>
{{
  "task_completed": true/false,
  "natural_ending": true/false,
  "faq_handled": true/false,
  "flow_followed": true/false,
  "user_experience": 1-5,
  "overall": 1-5,
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["不足1", "不足2"],
  "suggestions": ["建议1", "建议2"]
}}
</result>

评估标准：
- task_completed：是否达成了通话目标
- natural_ending：通话是否自然结束（非突然中断）
- faq_handled：用户提问时是否正确回答
- flow_followed：是否按流程推进，没有跳步或遗漏
- user_experience：整体用户感受（1=很差 5=很好）
- overall：综合评分（1=不合格 5=优秀）
- 如信息不足无法判断某项，输出0"""


class LLMJudge:
    def __init__(self, task_config: dict, llm: DeepSeekClient = None):
        self.config = task_config
        self.llm = llm or DeepSeekClient()

    def evaluate_turn(self, turn_idx: int, user_input: str, agent_reply: str,
                      context: list[dict]) -> TurnScore:
        """逐轮评测"""
        flow_desc = "\n".join(
            f"  - {s['condition']} → {s['action']}" for s in self.config["flow"]
        )
        faq_desc = "\n".join(
            f"  - {f['question_type']}: {f['answer']}" for f in self.config.get("faq", [])
        ) or "  无"
        constraints = "\n".join(f"  - {c}" for c in self.config["constraints"])

        # 格式化上下文（最近4轮）
        recent = context[-8:] if len(context) > 8 else context
        context_text = "\n".join(
            f"  {'用户' if h['role']=='user' else '客服'}: {h['content']}"
            for h in recent
        )

        prompt = TURN_EVAL_PROMPT.format(
            role=self.config["role"],
            goal=self.config["goal"],
            flow_description=flow_desc,
            faq_description=faq_desc,
            constraints=constraints,
            context=context_text or "（开场）",
            user_input=user_input,
            agent_reply=agent_reply,
        )

        try:
            result = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            scores = _extract_result_json(result)
        except (json.JSONDecodeError, Exception):
            scores = {"cohesion": 3, "knowledge": 3, "compliance": 3, "progress": 3, "comment": "评测解析失败"}

        return TurnScore(
            turn=turn_idx,
            user_input=user_input,
            agent_reply=agent_reply,
            cohesion=scores.get("cohesion", 3),
            knowledge=scores.get("knowledge", 3),
            compliance=scores.get("compliance", 3),
            progress=scores.get("progress", 3),
            comment=scores.get("comment", ""),
        )

    def evaluate_dialogue(self, dialogue_history: list[dict],
                          compliant_turns: int, total_turns: int) -> DialogueScore:
        """整体评测"""
        flow_summary = " → ".join(s["action"][:15] for s in self.config["flow"])
        full_dialogue = "\n".join(
            f"{'用户' if h['role']=='user' else '客服'}: {h['content']}"
            for h in dialogue_history
        )

        prompt = DIALOGUE_EVAL_PROMPT.format(
            role=self.config["role"],
            goal=self.config["goal"],
            flow_summary=flow_summary,
            full_dialogue=full_dialogue,
            compliant_turns=compliant_turns,
            total_turns=total_turns,
        )

        try:
            result = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            scores = _extract_result_json(result)
        except (json.JSONDecodeError, Exception):
            scores = {
                "task_completed": False, "natural_ending": False,
                "faq_handled": False, "flow_followed": False,
                "user_experience": 3, "overall": 3,
                "strengths": ["评测解析失败"], "weaknesses": [], "suggestions": [],
            }

        return DialogueScore(
            task_completed=scores.get("task_completed", False),
            natural_ending=scores.get("natural_ending", False),
            faq_handled=scores.get("faq_handled", False),
            flow_followed=scores.get("flow_followed", False),
            user_experience=scores.get("user_experience", 3),
            overall=scores.get("overall", 3),
            strengths=scores.get("strengths", []),
            weaknesses=scores.get("weaknesses", []),
            suggestions=scores.get("suggestions", []),
        )

    def full_evaluation(self, dialogue_history: list[dict],
                        compliant_turns: int, total_turns: int) -> dict:
        """完整评测：逐轮 + 整体"""
        # 逐轮评测 - 找出所有 user→assistant 对
        turn_scores = []
        context = []

        i = 0
        while i < len(dialogue_history):
            msg = dialogue_history[i]
            if msg["role"] == "user":
                user_msg = msg["content"]
                # 找下一条 assistant 回复
                agent_msg = ""
                if i + 1 < len(dialogue_history) and dialogue_history[i + 1]["role"] == "assistant":
                    agent_msg = dialogue_history[i + 1]["content"]

                if agent_msg:
                    score = self.evaluate_turn(
                        turn_idx=len(turn_scores) + 1,
                        user_input=user_msg,
                        agent_reply=agent_msg,
                        context=context,
                    )
                    turn_scores.append(score)

                context.append(msg)
                if agent_msg:
                    context.append(dialogue_history[i + 1])
                    i += 2
                else:
                    i += 1
            else:
                # assistant 消息（如开场白），加入上下文
                context.append(msg)
                i += 1

        # 整体评测
        dialogue_score = self.evaluate_dialogue(dialogue_history, compliant_turns, total_turns)

        # 汇总
        avg_scores = {}
        if turn_scores:
            avg_scores = {
                "avg_cohesion": sum(t.cohesion for t in turn_scores) / len(turn_scores),
                "avg_knowledge": sum(t.knowledge for t in turn_scores) / len(turn_scores),
                "avg_compliance": sum(t.compliance for t in turn_scores) / len(turn_scores),
                "avg_progress": sum(t.progress for t in turn_scores) / len(turn_scores),
            }

        return {
            "turn_scores": [asdict(t) for t in turn_scores],
            "dialogue_score": asdict(dialogue_score),
            "averages": avg_scores,
        }
