"""外呼任务 DSL schema (Pydantic v2).

DSL 是评测系统的核心中间表示：把自然语言任务指令编译成可执行评测程序。
四类核心对象：State / Transition / SeverityRule / TaskDSL。

参考思想：
- ConvLab-2 DST + user agenda（github.com/thu-coai/ConvLab-2）
- IFEval 可验证约束（arXiv:2311.07911）

设计要点：
- 阶段状态（id）+ 槽位状态（slots）双层
- 转移条件支持规则强触发（rule_keywords）与 LLM 意图分类（intent）
- severity_rules 单独承载 P0/P1，不混入维度评分
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SeverityLevel = Literal["P0", "P1", "normal"]


class TransitionCondition(BaseModel):
    """转移条件。规则触发与意图分类二选一或并存。"""

    intent: str | None = Field(
        default=None,
        description="LLM 意图分类命中。来自 TaskDSL.intents 枚举。",
    )
    slot_equals: dict[str, Any] = Field(
        default_factory=dict,
        description="槽位等值条件，如 trust_verified=True。",
    )
    rule_keywords: list[str] = Field(
        default_factory=list,
        description="用户输入中出现任一关键词即强触发，绕过 LLM。",
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> "TransitionCondition":
        if not self.intent and not self.slot_equals and not self.rule_keywords:
            raise ValueError("TransitionCondition 至少需要一个判定字段")
        return self


class Transition(BaseModel):
    """状态转移边。"""

    to: str
    when: TransitionCondition
    description: str = ""

    @field_validator("to")
    @classmethod
    def _to_nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("transition.to 不可为空")
        return value


class State(BaseModel):
    """对话阶段状态节点。"""

    id: str
    description: str = ""
    entry: bool = False
    terminal: bool = False
    required_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    success_conditions: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_pattern(cls, value: str) -> str:
        if not value or not value.replace("_", "").isalnum():
            raise ValueError(f"state.id 必须为字母数字下划线: {value}")
        return value


class SeverityRule(BaseModel):
    """P0/P1 风险规则。每条规则必须给出可机器或 LLM 判定的条件描述。"""

    id: str
    level: SeverityLevel
    description: str
    detector: Literal["rule", "llm", "hybrid"] = "hybrid"
    rule_keywords: list[str] = Field(
        default_factory=list,
        description="规则前置筛选关键词，命中后再让 LLM 复核以降低成本。",
    )
    state_scope: list[str] = Field(
        default_factory=list,
        description="仅在这些状态下检测；空列表表示全状态生效。",
    )
    rationale_template: str = Field(
        default="",
        description="生成 violation rationale 时的模板提示。",
    )

    @model_validator(mode="after")
    def _normal_no_keyword(self) -> "SeverityRule":
        if self.level == "normal" and self.detector == "rule" and not self.rule_keywords:
            raise ValueError(f"normal 级 rule 至少给一个 rule_keywords: {self.id}")
        return self


class GlobalConstraints(BaseModel):
    """全局约束（来自原始 constraints / forbidden / max_reply_length）。"""

    max_reply_chars: int = 30
    forbidden_phrases: list[str] = Field(default_factory=list)
    must_not_answer_out_of_scope: bool = True
    out_of_scope_fallback: str = ""


class AtomicRequirement(BaseModel):
    """原子需求项。覆盖率分母与失败定位的最小单元。"""

    id: str
    description: str
    bound_to_state: str | None = None
    severity_hint: SeverityLevel = "normal"


class TaskDSL(BaseModel):
    """编译后的外呼任务 DSL。

    入口约束：必须有且仅有一个 entry=True 的 state。
    终止约束：至少一个 terminal=True 的 state。
    转移目标必须存在于 states 列表。
    """

    task_id: str
    role: str
    objective: str
    states: list[State]
    intents: list[str] = Field(default_factory=list)
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="槽位初值。运行时由 StateTracker 更新。",
    )
    severity_rules: list[SeverityRule] = Field(default_factory=list)
    global_constraints: GlobalConstraints = Field(default_factory=GlobalConstraints)
    atomic_requirements: list[AtomicRequirement] = Field(default_factory=list)
    faq: list[dict[str, str]] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structural_check(self) -> "TaskDSL":
        ids = [s.id for s in self.states]
        if len(set(ids)) != len(ids):
            raise ValueError("states.id 重复")
        entries = [s for s in self.states if s.entry]
        if len(entries) != 1:
            raise ValueError(f"必须恰好 1 个 entry state，当前 {len(entries)}")
        if not any(s.terminal for s in self.states):
            raise ValueError("至少 1 个 terminal state")
        valid_ids = set(ids)
        for state in self.states:
            for tr in state.transitions:
                if tr.to not in valid_ids:
                    raise ValueError(f"transition.to 未定义: {state.id}->{tr.to}")
        intents_set = set(self.intents)
        for state in self.states:
            for tr in state.transitions:
                if tr.when.intent and tr.when.intent not in intents_set:
                    raise ValueError(
                        f"transition.intent 未在 intents 枚举: {tr.when.intent}"
                    )
        rule_ids = [r.id for r in self.severity_rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("severity_rules.id 重复")
        req_ids = [r.id for r in self.atomic_requirements]
        if len(set(req_ids)) != len(req_ids):
            raise ValueError("atomic_requirements.id 重复")
        return self

    def state_by_id(self, sid: str) -> State:
        for s in self.states:
            if s.id == sid:
                return s
        raise KeyError(sid)

    @property
    def entry_state(self) -> State:
        return next(s for s in self.states if s.entry)

    @property
    def all_edges(self) -> list[tuple[str, str]]:
        return [(s.id, tr.to) for s in self.states for tr in s.transitions]
