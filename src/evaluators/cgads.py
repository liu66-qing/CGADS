"""CGADS: Coverage-Guided Adaptive Dialogue Simulation.

Core algorithm — iteratively selects scenarios that maximize coverage gain,
using uncovered targets from CoverageTracker to drive gap-filling generation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.dsl.coverage import CoverageReport, CoverageTracker
from src.dsl.schema import TaskDSL
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator


@dataclass
class CGADSConfig:
    budget: int = 12
    warmup_k: int = 4
    max_rounds: int = 3
    max_retry_per_target: int = 2
    adequacy_state: float = 0.80
    adequacy_edge: float = 0.60
    adequacy_risk: float = 0.80
    adequacy_req: float = 0.70


@dataclass
class RoundLog:
    round_num: int
    scenarios_run: int
    coverage_before: float
    coverage_after: float
    gaps_before: list[str]
    new_findings: list[str] = field(default_factory=list)
    duration_s: float = 0.0


@dataclass
class CGADSReport:
    results: list[dict[str, Any]]
    coverage: CoverageReport
    rounds: list[RoundLog]
    adequate: bool
    total_scenarios: int
    unreachable_targets: list[str]
    elapsed_s: float = 0.0

    def summary_lines(self) -> list[str]:
        lines = []
        for r in self.rounds:
            lines.append(
                f"Round {r.round_num}: {r.scenarios_run} scenarios → "
                f"coverage {r.coverage_before:.0%} → {r.coverage_after:.0%}"
            )
            if r.new_findings:
                lines.append(f"  New findings: {', '.join(r.new_findings)}")
        lines.append(f"Final: {self.total_scenarios} scenarios, adequate={self.adequate}")
        return lines


def _composite_coverage(report: CoverageReport) -> float:
    """Weighted composite coverage (risk-prioritized)."""
    s = len(report.state_visited) / max(len(report.state_total), 1)
    e = len(report.edge_triggered) / max(len(report.edge_total), 1)
    r = len(report.risk_tested) / max(len(report.risk_total), 1)
    q = len(report.requirement_satisfied) / max(len(report.requirement_total), 1)
    return 0.2 * s + 0.25 * e + 0.3 * r + 0.25 * q


def _expected_gain(target: str) -> float:
    """Heuristic priority score for a coverage gap."""
    if target.startswith("risk:p0"):
        return 0.4
    if target.startswith("risk:p1") or target.startswith("risk:"):
        return 0.3
    if target.startswith("edge:"):
        return 0.2
    if target.startswith("state:"):
        return 0.15
    return 0.1


def select_by_expected_gain(
    scenarios: list[dict[str, Any]],
    report: CoverageReport,
) -> dict[str, Any]:
    """Pick scenario with highest expected coverage gain."""
    if not scenarios:
        raise ValueError("No scenarios to select from")

    uncovered = set(report.uncovered_targets())

    def score(scenario: dict[str, Any]) -> float:
        targets = scenario.get("coverage_targets", [])
        return sum(_expected_gain(t) for t in targets if t in uncovered)

    return max(scenarios, key=score)


def rank_by_expected_gain(
    scenarios: list[dict[str, Any]],
    report: CoverageReport,
) -> list[dict[str, Any]]:
    """Sort scenarios descending by expected coverage gain."""
    uncovered = set(report.uncovered_targets())

    def score(scenario: dict[str, Any]) -> float:
        targets = scenario.get("coverage_targets", [])
        return sum(_expected_gain(t) for t in targets if t in uncovered)

    return sorted(scenarios, key=score, reverse=True)


class CGADSRunner:
    """Coverage-Guided Adaptive Dialogue Simulation orchestrator."""

    def __init__(
        self,
        dsl: TaskDSL,
        run_scenario_fn: Callable[[dict[str, Any], int], dict[str, Any]],
        config: CGADSConfig | None = None,
    ):
        self.dsl = dsl
        self.run_scenario_fn = run_scenario_fn
        self.config = config or CGADSConfig()
        self.generator = CoverageDrivenScenarioGenerator(dsl)
        self.tracker = CoverageTracker(dsl)
        self._unreachable: list[str] = []
        self._target_attempts: dict[str, int] = {}

    def run(self) -> CGADSReport:
        """Execute full CGADS closed loop."""
        t0 = time.time()
        results: list[dict[str, Any]] = []
        rounds: list[RoundLog] = []
        scenario_idx = 0

        base_scenarios = self.generator.generate_base()[: self.config.warmup_k]

        for round_num in range(1, self.config.max_rounds + 1):
            scenarios = base_scenarios if round_num == 1 else self._generate_gap_scenarios()
            if not scenarios:
                break

            cov_before = _composite_coverage(self.tracker.report())
            gaps_before = self.tracker.uncovered_targets()
            run_count = 0
            new_findings: list[str] = []
            round_t0 = time.time()

            ranked = rank_by_expected_gain(scenarios, self.tracker.report())

            for scenario in ranked:
                if len(results) >= self.config.budget:
                    break

                scenario_idx += 1
                result = self._run_and_record(scenario, scenario_idx)
                if result is None:
                    continue

                results.append(result)
                run_count += 1

                violations = result.get("violation_rule_ids", [])
                for v in violations:
                    new_findings.append(v)

                if self.is_adequate():
                    break

            cov_after = _composite_coverage(self.tracker.report())
            rounds.append(RoundLog(
                round_num=round_num,
                scenarios_run=run_count,
                coverage_before=cov_before,
                coverage_after=cov_after,
                gaps_before=gaps_before,
                new_findings=new_findings,
                duration_s=time.time() - round_t0,
            ))

            if self.is_adequate() or len(results) >= self.config.budget:
                break

        return CGADSReport(
            results=results,
            coverage=self.tracker.report(),
            rounds=rounds,
            adequate=self.is_adequate(),
            total_scenarios=len(results),
            unreachable_targets=self._unreachable,
            elapsed_s=time.time() - t0,
        )

    def is_adequate(self, report: CoverageReport | None = None) -> bool:
        """Check Coverage Adequacy condition."""
        r = report or self.tracker.report()
        cfg = self.config

        s = len(r.state_visited) / max(len(r.state_total), 1)
        e = len(r.edge_triggered) / max(len(r.edge_total), 1)
        risk = len(r.risk_tested) / max(len(r.risk_total), 1)
        q = len(r.requirement_satisfied) / max(len(r.requirement_total), 1)

        if s < cfg.adequacy_state:
            return False
        if e < cfg.adequacy_edge:
            return False
        if risk < cfg.adequacy_risk:
            return False
        if q < cfg.adequacy_req:
            return False

        p0_rules = {
            rule.rule_id
            for rule in self.dsl.severity_rules
            if getattr(rule, "level", getattr(rule, "severity", "")) == "P0"
        }
        if p0_rules and not p0_rules.issubset(r.risk_tested):
            return False

        return True

    def _generate_gap_scenarios(self) -> list[dict[str, Any]]:
        """Generate targeting scenarios from uncovered gaps, respecting retry limits."""
        gaps = self.tracker.uncovered_targets()
        actionable_gaps = []
        for g in gaps:
            attempts = self._target_attempts.get(g, 0)
            if attempts >= self.config.max_retry_per_target:
                if g not in self._unreachable:
                    self._unreachable.append(g)
                continue
            actionable_gaps.append(g)

        if not actionable_gaps:
            return []

        return self.generator.generate_from_coverage_report(actionable_gaps)

    def _run_and_record(
        self, scenario: dict[str, Any], index: int
    ) -> dict[str, Any] | None:
        """Run a single scenario and update coverage tracker."""
        targets = scenario.get("coverage_targets", [])
        for t in targets:
            self._target_attempts[t] = self._target_attempts.get(t, 0) + 1

        try:
            result = self.run_scenario_fn(scenario, index)
        except Exception:
            return None

        scenario_id = result.get("scenario_id", f"scenario_{index:03d}")
        self.tracker.record_scenario(
            scenario_id=scenario_id,
            state_updates=_adapt_trace(result.get("state_trace", [])),
            coverage_targets=targets,
            violation_rule_ids=result.get("violation_rule_ids", []),
            satisfied_requirements=result.get("satisfied_requirements", []),
        )
        return result


def _adapt_trace(trace: list[dict[str, Any]]):
    """Convert exported state trace dicts to objects with prev_state/new_state attrs."""
    for item in trace:
        yield _TraceItem(
            prev_state=item.get("prev_state", ""),
            new_state=item.get("new_state", ""),
            triggered_transition=item.get("transition"),
        )


class _TraceItem:
    __slots__ = ("prev_state", "new_state", "triggered_transition")

    def __init__(self, prev_state: str, new_state: str, triggered_transition: str | None):
        self.prev_state = prev_state
        self.new_state = new_state
        self.triggered_transition = triggered_transition
