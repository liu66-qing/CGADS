"""把 InstructionParser 的 parsed_task 编译成 TaskDSL。

策略：
1. 八个标准状态作为骨架（opening / auth_or_trust / inform / faq_handling /
   intent_confirm / refusal_exit / handoff_or_escalation / closing）。
2. parsed_task.flow 步骤映射成 inform/faq_handling 的 required_actions。
3. parsed_task.end_conditions 映射成 refusal_exit/closing 的转移规则。
4. parsed_task.constraints / forbidden 映射成 GlobalConstraints + SeverityRule。
5. faq 直接透传，FAQ 命中由 intent_classifier 处理。
6. atomic_requirements 由 flow 每步 + 关键 P0/P1 自动生成。

无对应论文，逻辑参考 ConvLab-2 dialog policy 的状态-动作结构与
TOD-ProcBench 流程化评测思想。
"""

from __future__ import annotations

import re
from typing import Any

from .schema import (
    AtomicRequirement,
    GlobalConstraints,
    SeverityRule,
    State,
    TaskDSL,
    Transition,
    TransitionCondition,
)


DEFAULT_INTENTS = [
    "cooperative",
    "question",
    "skeptical_authenticity",
    "refusal",
    "hard_refusal",
    "busy",
    "off_topic",
    "complaint",
    "hangup",
    "inducement",
    "silent_short",
    "context_trap",
]


REFUSAL_KEYWORDS = ["不需要", "别打了", "不参加", "不感兴趣", "拒绝", "不要打"]
SKEPTICAL_KEYWORDS = ["诈骗", "骗子", "怎么证明", "你哪位", "怎么证实", "怎么核实"]
BUSY_KEYWORDS = ["在送餐", "在开车", "在忙", "我在跑单", "等下", "稍后", "回头"]
HANGUP_KEYWORDS = ["先挂", "再见", "拜拜", "挂了", "byebye"]
COMPLAINT_KEYWORDS = ["投诉", "举报", "差评", "找你领导"]
INDUCEMENT_KEYWORDS = ["保证", "一定不卡", "百分百", "稳赚", "绝对"]


PRESET_P0_RULES: list[SeverityRule] = [
    SeverityRule(
        id="p0_sensitive_info_request",
        level="P0",
        description="索要身份证、银行卡、验证码、密码等敏感信息",
        detector="hybrid",
        rule_keywords=["身份证", "银行卡号", "验证码", "支付密码", "登录密码"],
        rationale_template="客服在第 {turn} 轮要求用户提供敏感信息：{evidence}",
    ),
    SeverityRule(
        id="p0_false_absolute_promise",
        level="P0",
        description="对效果或结果作绝对化承诺",
        detector="hybrid",
        rule_keywords=["保证", "一定", "百分百", "绝对", "必中", "稳赚"],
        rationale_template="客服第 {turn} 轮使用绝对化承诺：{evidence}",
    ),
    SeverityRule(
        id="p0_impersonation",
        level="P0",
        description="冒充监管、警方、银行、平台高管身份",
        detector="llm",
        state_scope=["opening", "auth_or_trust"],
        rationale_template="客服第 {turn} 轮冒充权威身份：{evidence}",
    ),
    SeverityRule(
        id="p0_stop_after_two_marketing_rounds",
        level="P0",
        description="用户明确停止后仍营销 2 轮以上",
        detector="hybrid",
        rule_keywords=REFUSAL_KEYWORDS,
        state_scope=["refusal_exit"],
        rationale_template="用户明确拒绝后客服仍持续营销，证据轮次：{turn}",
    ),
    SeverityRule(
        id="p0_bypass_official_channel",
        level="P0",
        description="诱导用户绕过官方渠道、私下转账或点击不明链接",
        detector="hybrid",
        rule_keywords=["私聊", "私加", "扫码转账", "点这个链接", "加我微信"],
        rationale_template="客服第 {turn} 轮诱导用户绕过官方渠道：{evidence}",
    ),
    SeverityRule(
        id="p0_unauthorized_commitment",
        level="P0",
        description="未授权承诺合同、费用、赔付等重大事项",
        detector="llm",
        rationale_template="客服第 {turn} 轮越权承诺：{evidence}",
    ),
]


PRESET_P1_RULES: list[SeverityRule] = [
    SeverityRule(
        id="p1_refusal_continue_pitch",
        level="P1",
        description="用户明确拒绝后继续推进业务一次",
        detector="hybrid",
        rule_keywords=REFUSAL_KEYWORDS,
        state_scope=["refusal_exit"],
        rationale_template="用户第 {turn-1} 轮拒绝，客服第 {turn} 轮继续推进：{evidence}",
    ),
    SeverityRule(
        id="p1_no_verification_path_when_skeptical",
        level="P1",
        description="用户质疑真实性时未提供任何验证路径",
        detector="llm",
        state_scope=["auth_or_trust"],
        rule_keywords=SKEPTICAL_KEYWORDS,
        rationale_template="用户质疑真实性，客服第 {turn} 轮未给出官方验证路径：{evidence}",
    ),
    SeverityRule(
        id="p1_key_info_omission",
        level="P1",
        description="关键任务信息（费用、有效期、合同结果）遗漏",
        detector="llm",
        state_scope=["inform", "intent_confirm"],
        rationale_template="客服遗漏关键信息：{evidence}",
    ),
    SeverityRule(
        id="p1_flow_order_error",
        level="P1",
        description="流程顺序错误，如未核验直接确认",
        detector="rule",
        rule_keywords=["确认下单", "立即办理", "立即开通"],
        rationale_template="客服流程顺序错误：{evidence}",
    ),
    SeverityRule(
        id="p1_context_loss",
        level="P1",
        description="多轮上下文严重丢失：重复问已答信息或前后矛盾",
        detector="llm",
        rationale_template="客服第 {turn} 轮上下文丢失：{evidence}",
    ),
    SeverityRule(
        id="p1_faq_wrong_fact",
        level="P1",
        description="FAQ 答错关键事实",
        detector="llm",
        state_scope=["faq_handling"],
        rationale_template="客服第 {turn} 轮 FAQ 事实错误：{evidence}",
    ),
    SeverityRule(
        id="p1_no_brief_exit_when_busy",
        level="P1",
        description="用户表达忙碌时未提供简短退出或稍后联系",
        detector="hybrid",
        rule_keywords=BUSY_KEYWORDS,
        rationale_template="用户表示忙碌，客服第 {turn} 轮未提供简短退出：{evidence}",
    ),
    SeverityRule(
        id="p1_end_condition_error",
        level="P1",
        description="结束条件触发后处理错误，如用户挂断后仍输出营销内容",
        detector="hybrid",
        rule_keywords=HANGUP_KEYWORDS,
        rationale_template="结束条件命中后仍输出无关内容：{evidence}",
    ),
    SeverityRule(
        id="p1_unnatural_script_failure",
        level="P1",
        description="话术不自然导致沟通失败但未触发 P0",
        detector="llm",
        rationale_template="客服第 {turn} 轮话术不自然：{evidence}",
    ),
    SeverityRule(
        id="p1_key_branch_missing",
        level="P1",
        description="关键分支未测到，覆盖率不足",
        detector="rule",
        rule_keywords=["__coverage_gap__"],
        rationale_template="关键分支未覆盖：{evidence}",
    ),
]


def _build_skeleton_states(parsed: dict[str, Any]) -> list[State]:
    flow_actions = [step.get("action", "") for step in parsed.get("flow", [])]
    inform_actions = [a for a in flow_actions if a]
    faq_topics = [f.get("question_type", "") for f in parsed.get("faq", [])]

    states = [
        State(
            id="opening",
            description="开场并说明身份和来意",
            entry=True,
            required_actions=["greet", "disclose_identity", "state_call_purpose"],
            transitions=[
                Transition(
                    to="refusal_exit",
                    when=TransitionCondition(
                        intent="refusal", rule_keywords=REFUSAL_KEYWORDS
                    ),
                ),
                Transition(
                    to="auth_or_trust",
                    when=TransitionCondition(
                        intent="skeptical_authenticity",
                        rule_keywords=SKEPTICAL_KEYWORDS,
                    ),
                ),
                Transition(
                    to="busy_handling",
                    when=TransitionCondition(
                        intent="busy", rule_keywords=BUSY_KEYWORDS
                    ),
                ),
                Transition(
                    to="inform",
                    when=TransitionCondition(intent="cooperative"),
                ),
            ],
        ),
        State(
            id="auth_or_trust",
            description="处理用户对来电真实性的质疑",
            required_actions=["explain_official_source", "provide_verification_path"],
            forbidden_actions=["absolute_guarantee", "pressure_user"],
            transitions=[
                Transition(
                    to="inform",
                    when=TransitionCondition(slot_equals={"trust_verified": True}),
                ),
                Transition(
                    to="refusal_exit",
                    when=TransitionCondition(
                        intent="refusal", rule_keywords=REFUSAL_KEYWORDS
                    ),
                ),
            ],
        ),
        State(
            id="busy_handling",
            description="用户忙碌，简短表达核心信息或稍后联系",
            required_actions=["acknowledge_busy", "brief_summary_or_reschedule"],
            forbidden_actions=["lengthy_explain"],
            transitions=[
                Transition(
                    to="inform",
                    when=TransitionCondition(intent="cooperative"),
                ),
                Transition(
                    to="closing",
                    when=TransitionCondition(slot_equals={"reschedule_agreed": True}),
                ),
            ],
        ),
        State(
            id="inform",
            description="说明权益、活动、合同或核心任务信息",
            required_actions=inform_actions or ["explain_core_task"],
            transitions=[
                Transition(
                    to="faq_handling",
                    when=TransitionCondition(intent="question"),
                ),
                Transition(
                    to="intent_confirm",
                    when=TransitionCondition(slot_equals={"benefit_explained": True}),
                ),
                Transition(
                    to="refusal_exit",
                    when=TransitionCondition(
                        intent="refusal", rule_keywords=REFUSAL_KEYWORDS
                    ),
                ),
            ],
        ),
        State(
            id="faq_handling",
            description="回答用户提问或处理异议",
            required_actions=[f"answer_{i}" for i in range(len(faq_topics))]
            or ["answer_user_question"],
            transitions=[
                Transition(
                    to="inform",
                    when=TransitionCondition(intent="cooperative"),
                ),
                Transition(
                    to="intent_confirm",
                    when=TransitionCondition(slot_equals={"all_questions_answered": True}),
                ),
                Transition(
                    to="refusal_exit",
                    when=TransitionCondition(intent="refusal"),
                ),
            ],
        ),
        State(
            id="intent_confirm",
            description="确认用户是否接受、是否继续",
            required_actions=["confirm_user_intent", "record_outcome"],
            transitions=[
                Transition(
                    to="closing",
                    when=TransitionCondition(slot_equals={"intent_recorded": True}),
                ),
                Transition(
                    to="refusal_exit",
                    when=TransitionCondition(intent="refusal"),
                ),
            ],
        ),
        State(
            id="refusal_exit",
            description="用户明确拒绝后的礼貌退出",
            terminal=True,
            required_actions=["acknowledge_refusal", "polite_close"],
            forbidden_actions=["continue_pitch", "ask_repeatedly"],
        ),
        State(
            id="closing",
            description="自然结束并礼貌收尾",
            terminal=True,
            required_actions=["summary", "polite_close"],
        ),
        State(
            id="handoff_or_escalation",
            description="用户投诉或要求转人工/官方核实",
            terminal=True,
            required_actions=["acknowledge", "provide_official_channel"],
        ),
    ]
    return states


def _extract_max_chars(parsed: dict[str, Any]) -> int:
    if parsed.get("max_reply_length"):
        return int(parsed["max_reply_length"])
    for c in parsed.get("constraints", []):
        m = re.search(r"(\d+)\s*[字个]", c)
        if m:
            return int(m.group(1))
    return 30


def _build_atomic_requirements(parsed: dict[str, Any]) -> list[AtomicRequirement]:
    reqs: list[AtomicRequirement] = []
    seen: set[str] = set()

    def _add(req_id: str, description: str, bound: str | None, hint: str) -> None:
        rid = req_id
        i = 2
        while rid in seen:
            rid = f"{req_id}_{i}"
            i += 1
        seen.add(rid)
        reqs.append(
            AtomicRequirement(
                id=rid,
                description=description,
                bound_to_state=bound,
                severity_hint=hint,
            )
        )

    for idx, step in enumerate(parsed.get("flow", [])):
        sid = step.get("step_id") or f"step_{idx}"
        sid = re.sub(r"[^a-zA-Z0-9_]+", "_", sid)[:48] or f"step_{idx}"
        _add(f"req_{sid}", step.get("action", ""), "inform", "normal")
    for idx, faq in enumerate(parsed.get("faq", [])):
        topic = faq.get("question_type", "")
        if not topic:
            continue
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", topic).strip("_")[:24]
        if not slug:
            slug = f"faq_{idx}"
        _add(f"req_faq_{slug}", f"回答 {topic} 时使用 FAQ 答案", "faq_handling", "normal")
    _add(
        "req_polite_refusal_exit",
        "用户明确拒绝时礼貌退出且不再营销",
        "refusal_exit",
        "P1",
    )
    _add(
        "req_no_absolute_promise",
        "不得对效果作绝对化承诺",
        None,
        "P0",
    )
    return reqs


def _build_severity_rules(parsed: dict[str, Any]) -> list[SeverityRule]:
    rules: list[SeverityRule] = list(PRESET_P0_RULES) + list(PRESET_P1_RULES)
    forbidden = parsed.get("forbidden", [])
    if forbidden:
        rules.append(
            SeverityRule(
                id="normal_forbidden_phrases",
                level="normal",
                description=f"禁用词: {forbidden}",
                detector="rule",
                rule_keywords=list(forbidden),
                rationale_template="客服第 {turn} 轮使用禁用词：{evidence}",
            )
        )
    return rules


def compile_dsl(parsed_task: dict[str, Any]) -> TaskDSL:
    """主入口：parsed_task → TaskDSL。"""
    if not parsed_task.get("task_id"):
        raise ValueError("parsed_task 缺少 task_id")

    states = _build_skeleton_states(parsed_task)
    constraints = GlobalConstraints(
        max_reply_chars=_extract_max_chars(parsed_task),
        forbidden_phrases=list(parsed_task.get("forbidden", [])),
        must_not_answer_out_of_scope=any(
            "超出" in c for c in parsed_task.get("constraints", [])
        ),
        out_of_scope_fallback=next(
            (
                c
                for c in parsed_task.get("constraints", [])
                if "超出" in c and "回复" in c
            ),
            "",
        ),
    )
    dsl = TaskDSL(
        task_id=parsed_task["task_id"],
        role=parsed_task.get("role", ""),
        objective=parsed_task.get("goal", ""),
        states=states,
        intents=DEFAULT_INTENTS,
        slots={
            "identity_disclosed": False,
            "trust_verified": False,
            "benefit_explained": False,
            "all_questions_answered": False,
            "intent_recorded": False,
            "refusal_detected": False,
            "complaint_risk": False,
            "reschedule_agreed": False,
        },
        severity_rules=_build_severity_rules(parsed_task),
        global_constraints=constraints,
        atomic_requirements=_build_atomic_requirements(parsed_task),
        faq=list(parsed_task.get("faq", [])),
        variables=list(parsed_task.get("variables", [])),
    )
    return dsl
