"""四类覆盖率追踪器：state / transition / risk / requirement。

定义：
- state_coverage = visited_states / reachable_states
- transition_coverage = triggered_edges / all_defined_edges
- risk_coverage = tested_p0p1_rules / all_p0p1_rules
- requirement_coverage = satisfied_atomic_reqs / all_atomic_reqs

满足判定：
- state visited：StateUpdate.new_state 命中
- transition triggered：StateUpdate.triggered_transition 命中
- risk tested：场景 coverage_targets 中带 risk: 前缀，或评测产出 violation
- requirement satisfied：评测引擎传入 satisfied_requirements 集合

输出 uncovered 项，供场景生成器反向补测。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .schema import TaskDSL
from .state_tracker import StateUpdate


@dataclass
class CoverageReport:
    state_visited: set[str]
    state_total: set[str]
    edge_triggered: set[tuple[str, str]]
    edge_total: set[tuple[str, str]]
    risk_tested: set[str]
    risk_total: set[str]
    requirement_satisfied: set[str]
    requirement_total: set[str]
    per_scenario: dict[str, dict[str, int]] = field(default_factory=dict)

    def _ratio(self, hit: set, total: set) -> float:
        if not total:
            return 1.0
        return len(hit) / len(total)

    def to_dict(self) -> dict[str, object]:
        return {
            "state_coverage": {
                "ratio": round(self._ratio(self.state_visited, self.state_total), 4),
                "hit": sorted(self.state_visited),
                "total": sorted(self.state_total),
                "uncovered": sorted(self.state_total - self.state_visited),
            },
            "transition_coverage": {
                "ratio": round(self._ratio(self.edge_triggered, self.edge_total), 4),
                "hit": [f"{a}->{b}" for a, b in sorted(self.edge_triggered)],
                "total": [f"{a}->{b}" for a, b in sorted(self.edge_total)],
                "uncovered": [
                    f"{a}->{b}" for a, b in sorted(self.edge_total - self.edge_triggered)
                ],
            },
            "risk_coverage": {
                "ratio": round(self._ratio(self.risk_tested, self.risk_total), 4),
                "hit": sorted(self.risk_tested),
                "total": sorted(self.risk_total),
                "uncovered": sorted(self.risk_total - self.risk_tested),
            },
            "requirement_coverage": {
                "ratio": round(
                    self._ratio(self.requirement_satisfied, self.requirement_total), 4
                ),
                "hit": sorted(self.requirement_satisfied),
                "total": sorted(self.requirement_total),
                "uncovered": sorted(
                    self.requirement_total - self.requirement_satisfied
                ),
            },
            "per_scenario": self.per_scenario,
        }

    def uncovered_targets(self) -> list[str]:
        """聚合给 ScenarioGenerator 的反向补测目标列表。"""
        targets: list[str] = []
        for sid in sorted(self.state_total - self.state_visited):
            targets.append(f"state:{sid}")
        for a, b in sorted(self.edge_total - self.edge_triggered):
            targets.append(f"edge:{a}->{b}")
        for rid in sorted(self.risk_total - self.risk_tested):
            targets.append(f"risk:{rid}")
        for req in sorted(self.requirement_total - self.requirement_satisfied):
            targets.append(f"requirement:{req}")
        return targets


class CoverageTracker:
    """运行多个对话场景，聚合覆盖率。

    用法：
        tracker = CoverageTracker(dsl)
        for scenario in scenarios:
            ... run dialogue ...
            tracker.record_scenario(
                scenario_id=...,
                state_updates=tracker_history,
                coverage_targets=scenario.coverage_targets,
                violation_rule_ids=violations,
                satisfied_requirements=req_ids,
            )
        report = tracker.report()
    """

    def __init__(self, dsl: TaskDSL):
        self.dsl = dsl
        self._state_total = {s.id for s in dsl.states}
        self._edge_total = set(dsl.all_edges)
        self._risk_total = {
            r.id for r in dsl.severity_rules if r.level in ("P0", "P1")
        }
        self._req_total = {r.id for r in dsl.atomic_requirements}

        self._state_visited: set[str] = set()
        self._edge_triggered: set[tuple[str, str]] = set()
        self._risk_tested: set[str] = set()
        self._req_satisfied: set[str] = set()
        self._per_scenario: dict[str, dict[str, int]] = {}

    def record_scenario(
        self,
        scenario_id: str,
        state_updates: Iterable[StateUpdate],
        coverage_targets: Iterable[str] | None = None,
        violation_rule_ids: Iterable[str] | None = None,
        satisfied_requirements: Iterable[str] | None = None,
    ) -> None:
        local_states: set[str] = set()
        local_edges: set[tuple[str, str]] = set()
        local_risks: set[str] = set()
        local_reqs: set[str] = set()

        for upd in state_updates:
            local_states.add(upd.new_state)
            local_states.add(upd.prev_state)
            if upd.triggered_transition:
                a, b = upd.triggered_transition.split("->", 1)
                local_edges.add((a, b))

        targets = coverage_targets or []
        for tgt in targets:
            if tgt.startswith("risk:"):
                rid = tgt.split(":", 1)[1]
                if rid in self._risk_total:
                    local_risks.add(rid)
            elif tgt.startswith("requirement:"):
                rid = tgt.split(":", 1)[1]
                if rid in self._req_total:
                    local_reqs.add(rid)
            elif tgt.startswith("edge:"):
                edge = tgt.split(":", 1)[1]
                if "->" in edge:
                    a, b = edge.split("->", 1)
                    if (a, b) in self._edge_total:
                        local_edges.add((a, b))
            elif tgt.startswith("state:"):
                sid = tgt.split(":", 1)[1]
                if sid in self._state_total:
                    local_states.add(sid)

        for vid in violation_rule_ids or []:
            if vid in self._risk_total:
                local_risks.add(vid)

        for rid in satisfied_requirements or []:
            if rid in self._req_total:
                local_reqs.add(rid)

        self._state_visited |= local_states & self._state_total
        self._edge_triggered |= local_edges & self._edge_total
        self._risk_tested |= local_risks
        self._req_satisfied |= local_reqs

        self._per_scenario[scenario_id] = {
            "states": len(local_states & self._state_total),
            "edges": len(local_edges & self._edge_total),
            "risks": len(local_risks),
            "requirements": len(local_reqs),
        }

    def report(self) -> CoverageReport:
        return CoverageReport(
            state_visited=set(self._state_visited),
            state_total=set(self._state_total),
            edge_triggered=set(self._edge_triggered),
            edge_total=set(self._edge_total),
            risk_tested=set(self._risk_tested),
            risk_total=set(self._risk_total),
            requirement_satisfied=set(self._req_satisfied),
            requirement_total=set(self._req_total),
            per_scenario=dict(self._per_scenario),
        )

    def uncovered_targets(self) -> list[str]:
        return self.report().uncovered_targets()
