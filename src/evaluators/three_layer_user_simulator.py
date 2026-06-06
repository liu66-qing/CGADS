"""三层用户模拟器：Persona + 行为采样 + 状态转移。

Layer 1 - Persona：用户身份与性格（静态）
Layer 2 - 行为采样：每轮采样行为事件（短回/质疑/沉默/挂断/配合）
Layer 3 - 状态转移：用户内部 trust/patience/anger 连续值追踪

参考：
- OpenEvals create_llm_simulated_user（覆盖50%）
- ConvLab-2 user agenda（覆盖50%）
- prompt-based-user-simulator（arXiv:2306.00774）Persona prompt设计
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from ..llm_client import DeepSeekClient


@dataclass
class UserState:
    """用户内部状态变量（连续值 0~1）。"""

    trust: float = 0.5
    patience: float = 0.7
    interest: float = 0.5
    anger: float = 0.0
    turn: int = 0
    asked_questions: list[str] = field(default_factory=list)
    received_info: list[str] = field(default_factory=list)

    def clamp(self) -> None:
        self.trust = max(0.0, min(1.0, self.trust))
        self.patience = max(0.0, min(1.0, self.patience))
        self.interest = max(0.0, min(1.0, self.interest))
        self.anger = max(0.0, min(1.0, self.anger))


EVENT_TYPES = [
    "cooperative",
    "question",
    "short_reply",
    "skeptical",
    "refusal",
    "hangup",
    "off_topic",
    "complaint",
    "silent",
    "inducement",
]


@dataclass
class BehaviorEvent:
    """行为采样结果。"""

    event: str
    detail: str = ""


AGENT_ACTION_EFFECTS = {
    "provide_verification_path": {"trust": 0.3, "anger": -0.1},
    "explain_official_source": {"trust": 0.2},
    "absolute_guarantee": {"trust": -0.2, "anger": 0.1},
    "continue_pitch_when_refused": {"anger": 0.5, "patience": -0.4},
    "too_long": {"patience": -0.2},
    "answer_faq_correctly": {"trust": 0.1, "interest": 0.1},
    "answer_faq_incorrectly": {"trust": -0.2, "anger": 0.1},
    "acknowledge_busy": {"patience": 0.1, "trust": 0.1},
    "polite_close": {"anger": -0.1},
    "ignore_refusal": {"anger": 0.4, "patience": -0.3},
    "brief_and_clear": {"patience": 0.1, "interest": 0.1},
    "repetitive": {"patience": -0.2, "interest": -0.1},
}


class ThreeLayerUserSimulator:
    """三层用户模拟器。

    用法：
        sim = ThreeLayerUserSimulator(
            persona="质疑诈骗型骑手",
            behavior_guide="前2轮质疑真实性，获得验证路径后配合",
            intent_distribution={"skeptical_authenticity": 0.7, "question": 0.2, ...},
            initial_state=UserState(trust=0.2, patience=0.6),
            llm=llm_client,
        )
        # 每轮调用
        reply = sim.respond(agent_message, agent_action_tags=[...])
        if sim.should_hangup():
            break
    """

    def __init__(
        self,
        persona: str,
        behavior_guide: str = "",
        intent_distribution: dict[str, float] | None = None,
        initial_state: UserState | None = None,
        stop_after_turns: int = 15,
        llm: DeepSeekClient | None = None,
    ):
        self.persona = persona
        self.behavior_guide = behavior_guide
        self.intent_dist = intent_distribution or {"cooperative": 0.7, "question": 0.2, "off_topic": 0.1}
        self.state = initial_state or UserState()
        self.stop_after_turns = stop_after_turns
        self.llm = llm or DeepSeekClient()
        self.history: list[dict[str, str]] = []
        self._last_event: BehaviorEvent | None = None
        self._hangup = False

    def respond(
        self,
        agent_message: str,
        agent_action_tags: list[str] | None = None,
    ) -> str:
        """接收agent回复 → 更新状态 → 采样行为 → LLM生成回复。"""
        self.state.turn += 1

        # Layer 3: 更新用户状态（根据agent行为）
        self._update_state_from_agent(agent_message, agent_action_tags or [])

        # Layer 2: 采样行为事件
        event = self._sample_event()
        self._last_event = event

        # 挂断判定
        if event.event == "hangup" or self._check_hangup_threshold():
            self._hangup = True
            reply = self._generate_hangup_reply(agent_message)
            self.history.append({"role": "user", "content": agent_message})
            self.history.append({"role": "assistant", "content": reply})
            return reply

        # Layer 1 + LLM: 生成自然回复
        reply = self._generate_reply(agent_message, event)
        self.history.append({"role": "user", "content": agent_message})
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def should_hangup(self) -> bool:
        return self._hangup or self.state.turn >= self.stop_after_turns

    @property
    def last_event(self) -> BehaviorEvent | None:
        return self._last_event

    def export_state_trace(self) -> list[dict[str, Any]]:
        return [
            {
                "turn": self.state.turn,
                "trust": round(self.state.trust, 2),
                "patience": round(self.state.patience, 2),
                "interest": round(self.state.interest, 2),
                "anger": round(self.state.anger, 2),
            }
        ]

    def _update_state_from_agent(
        self, agent_message: str, action_tags: list[str]
    ) -> None:
        text = agent_message or ""
        inferred_actions: list[str] = list(action_tags)

        if len(text) > 60:
            inferred_actions.append("too_long")
        if any(kw in text for kw in ["保证", "一定", "百分百"]):
            inferred_actions.append("absolute_guarantee")
        if any(kw in text for kw in ["官方", "App", "后台", "消息中心", "工单"]):
            inferred_actions.append("provide_verification_path")
        if any(kw in text for kw in ["好的", "理解", "没关系", "明白"]):
            inferred_actions.append("acknowledge_busy")
        if any(kw in text for kw in ["再见", "祝您", "辛苦"]):
            inferred_actions.append("polite_close")

        for action in inferred_actions:
            effects = AGENT_ACTION_EFFECTS.get(action, {})
            for attr, delta in effects.items():
                current = getattr(self.state, attr, 0.0)
                setattr(self.state, attr, current + delta)

        self.state.patience -= 0.05
        self.state.clamp()

    def _sample_event(self) -> BehaviorEvent:
        weights = dict(self.intent_dist)

        if self.state.anger > 0.6:
            weights["refusal"] = weights.get("refusal", 0) + 0.3
            weights["complaint"] = weights.get("complaint", 0) + 0.2
        if self.state.patience < 0.3:
            weights["hangup"] = weights.get("hangup", 0) + 0.3
            weights["short_reply"] = weights.get("short_reply", 0) + 0.2
        if self.state.trust < 0.3:
            weights["skeptical"] = weights.get("skeptical", 0) + 0.2

        total = sum(weights.values())
        if total <= 0:
            return BehaviorEvent(event="cooperative")

        normalized = {k: v / total for k, v in weights.items()}
        events = list(normalized.keys())
        probs = [normalized[e] for e in events]
        chosen = random.choices(events, weights=probs, k=1)[0]
        return BehaviorEvent(event=chosen)

    def _check_hangup_threshold(self) -> bool:
        if self.state.patience < 0.15:
            return random.random() < 0.7
        if self.state.anger > 0.85:
            return random.random() < 0.6
        return False

    def _generate_hangup_reply(self, agent_message: str) -> str:
        if self.state.anger > 0.7:
            candidates = ["别打了", "不用了挂了", "我要投诉，别再打了"]
        else:
            candidates = ["先挂了", "行，先这样", "嗯好的，再见"]
        return random.choice(candidates)

    def _generate_reply(self, agent_message: str, event: BehaviorEvent) -> str:
        if not self.llm:
            return self._fallback_reply(event)
        event_guidance = self._event_to_guidance(event)
        system_prompt = f"""你正在扮演接到外呼电话的人。

【你的身份】{self.persona}

【本轮行为要求（必须遵循）】
{event_guidance}

【行为倾向参考】{self.behavior_guide}

【当前内部状态】
- 信任度: {self.state.trust:.1f} (0=完全不信 1=完全信任)
- 耐心: {self.state.patience:.1f} (0=极不耐烦 1=很有耐心)
- 怒气: {self.state.anger:.1f} (0=平静 1=很生气)

【规则】
1. 像真人接电话一样说话，口语化，简短
2. 每次回复1句话，不超过25字
3. 必须执行本轮行为要求
4. 只输出你说的话，不要标注或解释"""

        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for msg in self.history[-6:]:
            messages.append(msg)
        messages.append({"role": "user", "content": agent_message})

        try:
            reply = self.llm.chat(messages, max_tokens=128, temperature=0.8, timeout=4)
            if not reply or len(reply) > 80:
                return self._fallback_reply(event)
            return reply.strip()
        except Exception:
            return self._fallback_reply(event)

    def _event_to_guidance(self, event: BehaviorEvent) -> str:
        mapping = {
            "cooperative": "你这轮配合对话，简短确认或表示理解",
            "question": "你这轮提出一个问题，用口语追问细节",
            "short_reply": "你这轮回复极简（1-3字），如'嗯''哦''知道了'",
            "skeptical": "你这轮质疑来电真实性，要求证明身份或给出官方渠道",
            "refusal": "你这轮明确拒绝，态度坚定但礼貌，如'不用了'/'不需要'",
            "hangup": "你这轮表示要挂断电话",
            "off_topic": "你这轮问一个与主题无关的问题",
            "complaint": "你这轮表达不满或投诉意图",
            "silent": "你这轮只说一个'嗯'或不回应",
            "inducement": "你这轮追问能否保证、百分百确定、一定不会出问题",
        }
        return mapping.get(event.event, "你这轮正常配合对话")

    def _fallback_reply(self, event: BehaviorEvent) -> str:
        fallbacks = {
            "cooperative": "好的，知道了",
            "question": "那这个具体怎么弄？",
            "short_reply": "嗯",
            "skeptical": "你怎么证明你是官方的？",
            "refusal": "不用了，别说了",
            "hangup": "先挂了",
            "off_topic": "今天天气怎么样啊",
            "complaint": "你们怎么老打电话",
            "silent": "嗯",
            "inducement": "能保证吗？",
        }
        return fallbacks.get(event.event, "嗯")


def create_simulator_from_scenario(
    scenario: dict[str, Any], llm: DeepSeekClient | None = None
) -> ThreeLayerUserSimulator:
    """从 CoverageDrivenScenarioGenerator 的场景 dict 创建模拟器实例。"""
    intent_dist = scenario.get("intent_distribution", {"cooperative": 0.7, "question": 0.3})
    initial_state = UserState()

    if "skeptical" in scenario.get("name", "").lower() or "质疑" in scenario.get("name", ""):
        initial_state.trust = 0.2
    elif "拒绝" in scenario.get("name", ""):
        initial_state.trust = 0.3
        initial_state.patience = 0.4
    elif "忙碌" in scenario.get("name", ""):
        initial_state.patience = 0.4
    elif "诱导" in scenario.get("name", ""):
        initial_state.trust = 0.4
    elif "沉默" in scenario.get("name", ""):
        initial_state.patience = 0.5
        initial_state.interest = 0.2

    return ThreeLayerUserSimulator(
        persona=scenario.get("persona", "普通用户"),
        behavior_guide=scenario.get("behavior", ""),
        intent_distribution=intent_dist,
        initial_state=initial_state,
        stop_after_turns=scenario.get("stop_after_turns", 15),
        llm=llm,
    )
