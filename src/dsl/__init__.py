"""外呼任务 DSL：状态机 + 覆盖率核心包。

公开 API：
- TaskDSL / State / Transition / SeverityRule / GlobalConstraints / AtomicRequirement
- compile_dsl(parsed_task) -> TaskDSL
- StateTracker(dsl, llm)：runtime 状态追踪
- CoverageTracker(dsl)：四类覆盖率聚合
"""

from .compiler import compile_dsl
from .coverage import CoverageReport, CoverageTracker
from .schema import (
    AtomicRequirement,
    GlobalConstraints,
    SeverityRule,
    State,
    TaskDSL,
    Transition,
    TransitionCondition,
)
from .state_tracker import IntentResult, StateTracker, StateUpdate

__all__ = [
    "AtomicRequirement",
    "CoverageReport",
    "CoverageTracker",
    "GlobalConstraints",
    "IntentResult",
    "SeverityRule",
    "State",
    "StateTracker",
    "StateUpdate",
    "TaskDSL",
    "Transition",
    "TransitionCondition",
    "compile_dsl",
]
