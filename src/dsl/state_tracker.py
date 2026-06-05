"""Runtime 对话状态追踪器。

架构：规则强触发 → LLM 高置信触发 → 低置信保持原状态。
关键不变量：
- 状态只在转移条件命中时才迁移，否则保留 current_state。
- 槽位采用单调更新（已置 True 不被默认值覆盖）。
- 每次 step 输出 StateUpdate，附带 trigger 信息以便事后审计。

参考思想：ConvLab-2 DST + IFEval 可验证检测。
LLM 意图分类 prompt 控制低 temperature + 强制 JSON 输出。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..llm_client import DeepSeekClient
from .schema import State, TaskDSL, Transition


HIGH_CONF_THRESHOLD = 0.85
LOW_CONF_THRESHOLD = 0.6


INTENT_CLASSIFY_PROMPT = """你是外呼对话意图分类器。判定用户最新一句的意图。

【可选意图】
{intents}

【对话上下文最近 4 轮】
{context}

【用户最新一句】
{user_input}

只输出 JSON，不要 markdown：
{{"intent": "意图名", "confidence": 0.0-1.0, "rationale": "一句话理由"}}

规则：
- 必须从可选意图中选一个
- 含糊不清时给低置信（<0.6）
- 信心十足时给 >=0.85"""


@dataclass
class IntentResult:
    intent: str
    confidence: float
    source: str  # "rule" | "llm" | "fallback"
    rationale: str = ""


@dataclass
class StateUpdate:
    turn: int
    user_input: str
    prev_state: str
    new_state: str
    intent: IntentResult
    triggered_transition: str | None
    slot_updates: dict[str, Any]
    uncertain: bool = False
    notes: str = ""


@dataclass
class StateTracker:
    """单通对话级别的状态追踪器。每条对话用一个新实例。"""

    dsl: TaskDSL
    llm: DeepSeekClient | None = None
    current_state: str = ""
    slots: dict[str, Any] = field(default_factory=dict)
    history: list[StateUpdate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.current_state:
            self.current_state = self.dsl.entry_state.id
        if not self.slots:
            self.slots = dict(self.dsl.slots)

    def step(
        self,
        turn: int,
        user_input: str,
        agent_history: list[dict[str, str]] | None = None,
    ) -> StateUpdate:
        """每收到一条 user 消息后调用一次。返回本步状态变化。"""
        prev = self.current_state
        intent = self._classify_intent(user_input, agent_history or [])
        target_transition = self._match_transition(intent, user_input)

        slot_updates: dict[str, Any] = {}
        uncertain = False
        notes = ""

        if target_transition is None:
            new_state = prev
            notes = "no_transition_matched"
            uncertain = intent.confidence < LOW_CONF_THRESHOLD
        else:
            if intent.source == "rule" or intent.confidence >= HIGH_CONF_THRESHOLD:
                new_state = target_transition.to
            elif intent.confidence >= LOW_CONF_THRESHOLD:
                new_state = target_transition.to
                uncertain = True
                notes = "uncertain_transition"
            else:
                new_state = prev
                uncertain = True
                notes = "low_confidence_hold"
                target_transition = None

        slot_updates = self._derive_slot_updates(intent, user_input, prev, new_state)
        self._apply_slots(slot_updates)
        self.current_state = new_state

        update = StateUpdate(
            turn=turn,
            user_input=user_input,
            prev_state=prev,
            new_state=new_state,
            intent=intent,
            triggered_transition=(
                f"{prev}->{target_transition.to}" if target_transition else None
            ),
            slot_updates=slot_updates,
            uncertain=uncertain,
            notes=notes,
        )
        self.history.append(update)
        return update

    def observe_agent(self, turn: int, agent_reply: str) -> dict[str, Any]:
        """在 assistant 回复后调用。从 agent 内容反推槽位更新。"""
        updates: dict[str, Any] = {}
        text = agent_reply or ""
        if any(kw in text for kw in ["我是", "客服", "站长", "平台"]):
            updates.setdefault("identity_disclosed", True)
        if any(kw in text for kw in ["官方", "App", "工单", "后台", "消息中心"]):
            updates.setdefault("verification_path_provided", True)
        if any(kw in text for kw in ["合同", "权益", "活动", "抽奖", "订单"]):
            updates.setdefault("benefit_explained", True)
        if any(kw in text for kw in ["再见", "祝您", "辛苦", "打扰了", "顺利"]):
            updates.setdefault("polite_close_attempted", True)
        self._apply_slots(updates)
        return updates

    def _classify_intent(
        self, user_input: str, agent_history: list[dict[str, str]]
    ) -> IntentResult:
        rule_intent = self._rule_intent(user_input)
        if rule_intent is not None:
            return rule_intent
        if self.llm is None:
            return IntentResult(
                intent="cooperative", confidence=0.3, source="fallback",
                rationale="no llm available",
            )
        return self._llm_intent(user_input, agent_history)

    def _rule_intent(self, user_input: str) -> IntentResult | None:
        text = user_input or ""
        for state in self.dsl.states:
            for tr in state.transitions:
                kw = tr.when.rule_keywords
                if not kw:
                    continue
                hit = next((w for w in kw if w in text), None)
                if hit:
                    intent_name = tr.when.intent or _infer_intent_from_keywords(kw)
                    return IntentResult(
                        intent=intent_name,
                        confidence=0.95,
                        source="rule",
                        rationale=f"rule_keyword_hit:{hit}",
                    )
        return None

    def _llm_intent(
        self, user_input: str, agent_history: list[dict[str, str]]
    ) -> IntentResult:
        ctx_lines = []
        for msg in agent_history[-8:]:
            role = "用户" if msg.get("role") == "user" else "客服"
            ctx_lines.append(f"  {role}: {msg.get('content', '')}")
        prompt = INTENT_CLASSIFY_PROMPT.format(
            intents="、".join(self.dsl.intents),
            context="\n".join(ctx_lines) or "（开场）",
            user_input=user_input,
        )
        try:
            raw = self.llm.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.1,
            )
            parsed = _robust_json_parse(raw)
            intent = parsed.get("intent", "cooperative")
            if intent not in set(self.dsl.intents):
                intent = "cooperative"
            confidence = float(parsed.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            return IntentResult(
                intent=intent,
                confidence=confidence,
                source="llm",
                rationale=str(parsed.get("rationale", ""))[:120],
            )
        except Exception as exc:  # noqa: BLE001 - LLM 任意失败都退回保守路径
            return IntentResult(
                intent="cooperative",
                confidence=0.3,
                source="fallback",
                rationale=f"llm_error:{exc.__class__.__name__}",
            )

    def _match_transition(
        self, intent: IntentResult, user_input: str
    ) -> Transition | None:
        state = self.dsl.state_by_id(self.current_state)
        for tr in state.transitions:
            if self._transition_matches(tr, intent, user_input):
                return tr
        return None

    def _transition_matches(
        self, tr: Transition, intent: IntentResult, user_input: str
    ) -> bool:
        cond = tr.when
        if cond.rule_keywords and any(w in (user_input or "") for w in cond.rule_keywords):
            return True
        if cond.intent and cond.intent == intent.intent:
            return True
        if cond.slot_equals:
            for k, v in cond.slot_equals.items():
                if self.slots.get(k) != v:
                    return False
            return True
        return False

    def _derive_slot_updates(
        self, intent: IntentResult, user_input: str, prev: str, new_state: str
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if intent.intent in {"refusal", "hard_refusal"}:
            updates["refusal_detected"] = True
        if intent.intent == "complaint":
            updates["complaint_risk"] = True
        if intent.intent == "skeptical_authenticity":
            updates["trust_challenged"] = True
        if new_state == "refusal_exit":
            updates.setdefault("refusal_detected", True)
        if intent.intent == "busy":
            updates["user_busy"] = True
        if prev == "auth_or_trust" and new_state == "inform":
            updates["trust_verified"] = True
        return updates

    def _apply_slots(self, updates: dict[str, Any]) -> None:
        for k, v in updates.items():
            existing = self.slots.get(k)
            if isinstance(existing, bool) and existing and not v:
                continue
            self.slots[k] = v

    def export_trace(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for upd in self.history:
            out.append(
                {
                    "turn": upd.turn,
                    "prev_state": upd.prev_state,
                    "new_state": upd.new_state,
                    "intent": upd.intent.intent,
                    "intent_confidence": upd.intent.confidence,
                    "intent_source": upd.intent.source,
                    "transition": upd.triggered_transition,
                    "slot_updates": upd.slot_updates,
                    "uncertain": upd.uncertain,
                    "notes": upd.notes,
                }
            )
        return out


def _infer_intent_from_keywords(keywords: list[str]) -> str:
    sample = "".join(keywords)
    if any(w in sample for w in ["不需要", "别打", "拒绝", "不参加"]):
        return "refusal"
    if any(w in sample for w in ["诈骗", "证明", "你哪位", "核实"]):
        return "skeptical_authenticity"
    if any(w in sample for w in ["在送餐", "在开车", "在忙", "稍后"]):
        return "busy"
    if any(w in sample for w in ["再见", "拜拜", "挂了"]):
        return "hangup"
    return "cooperative"


def _robust_json_parse(text: str) -> dict[str, Any]:
    text = text or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        fixed = re.sub(r",\s*([}\]])", r"\1", m.group())
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
    return {}
