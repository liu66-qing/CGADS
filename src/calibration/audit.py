"""Gold-standard calibration dataset audit.

This module intentionally sits outside ``src.dsl`` so DSL implementation work can
continue independently. It validates the human gold labels that later calibrate
the LLM judge, scoring gates, and report generator.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.checkers.severity_rules import valid_rule_ids


DIMENSION_WEIGHTS = {
    "task_completion": 25,
    "flow_state_adherence": 20,
    "constraint_compliance": 20,
    "branch_handling": 15,
    "context_consistency": 10,
    "communication_experience": 10,
}

VALID_STATUS = {"PASS", "CAPPED_P1", "FAIL_P0"}
VALID_TASKS = {"rider_lottery_notify", "course_live_switch"}
VALID_COVERAGE_PREFIXES = ("edge:", "state:", "risk:", "requirement:", "faq:", "slot:")
VALID_BOUNDARY_FLAGS = {
    None,
    "hidden_p1",
    "late_exit",
    "p0_in_faq",
    "multi_p1_no_p0",
    "p0_recovery_attempt",
    "low_dim_no_violation",
}

VALID_P0_RULES = valid_rule_ids("P0")
VALID_P1_RULES = valid_rule_ids("P1")


@dataclass(frozen=True)
class AuditIssue:
    case_id: str
    level: str
    message: str


@dataclass
class AuditReport:
    total_cases: int
    issues: list[AuditIssue] = field(default_factory=list)
    status_distribution: Counter[str] = field(default_factory=Counter)
    task_distribution: Counter[str] = field(default_factory=Counter)
    persona_distribution: Counter[str] = field(default_factory=Counter)
    boundary_distribution: Counter[str] = field(default_factory=Counter)
    p0_rule_distribution: Counter[str] = field(default_factory=Counter)
    p1_rule_distribution: Counter[str] = field(default_factory=Counter)
    score_deltas: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total_cases": self.total_cases,
            "issue_count": len(self.issues),
            "issues": [issue.__dict__ for issue in self.issues],
            "status_distribution": dict(self.status_distribution),
            "task_distribution": dict(self.task_distribution),
            "persona_distribution": dict(self.persona_distribution),
            "boundary_distribution": dict(self.boundary_distribution),
            "p0_rule_distribution": dict(self.p0_rule_distribution),
            "p1_rule_distribution": dict(self.p1_rule_distribution),
            "score_deltas": self.score_deltas,
        }


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    with file_path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def compute_raw_weighted_score(dimension_scores: dict[str, int]) -> float:
    return sum(dimension_scores[name] / 5 * weight for name, weight in DIMENSION_WEIGHTS.items())


def compute_final_score(dimension_scores: dict[str, int], p0_count: int, p1_count: int) -> float:
    raw_score = compute_raw_weighted_score(dimension_scores)
    if p0_count:
        return min(raw_score, 30)
    if p1_count >= 3:
        return min(raw_score, 50)
    if p1_count == 2:
        return min(raw_score, 60)
    if p1_count == 1:
        return min(raw_score, 70)
    return raw_score


def audit_cases(cases: list[dict[str, Any]], strict30: bool = False) -> AuditReport:
    report = AuditReport(total_cases=len(cases))
    ids: list[str] = []

    for case in cases:
        case_id = case.get("case_id", "<missing>")
        ids.append(case_id)
        _audit_case(case, report)

    duplicates = [case_id for case_id, count in Counter(ids).items() if count > 1]
    for case_id in duplicates:
        report.issues.append(AuditIssue(case_id, "error", "duplicate case_id"))

    if strict30:
        expected_ids = [f"calib_{i:03d}" for i in range(1, 31)]
        if ids != expected_ids:
            report.issues.append(AuditIssue("dataset", "error", "case_id sequence must be calib_001..calib_030"))
        _expect_distribution(report, "PASS", 10, report.status_distribution)
        _expect_distribution(report, "CAPPED_P1", 12, report.status_distribution)
        _expect_distribution(report, "FAIL_P0", 8, report.status_distribution)
        _expect_distribution(report, "rider_lottery_notify", 15, report.task_distribution)
        _expect_distribution(report, "course_live_switch", 15, report.task_distribution)

    return report


def _audit_case(case: dict[str, Any], report: AuditReport) -> None:
    case_id = case.get("case_id", "<missing>")
    task_id = case.get("task_id")
    persona = case.get("persona")
    annotation = case.get("human_annotation", {})
    dialogue = case.get("dialogue", [])

    status = annotation.get("pass_status")
    boundary_flag = annotation.get("boundary_flag")
    p0_violations = annotation.get("p0_violations", [])
    p1_violations = annotation.get("p1_violations", [])
    dimension_scores = annotation.get("dimension_scores", {})

    report.status_distribution.update([status])
    report.task_distribution.update([task_id])
    report.persona_distribution.update([persona])
    if boundary_flag is not None:
        report.boundary_distribution.update([boundary_flag])
    report.p0_rule_distribution.update(v.get("rule_id") for v in p0_violations)
    report.p1_rule_distribution.update(v.get("rule_id") for v in p1_violations)

    if task_id not in VALID_TASKS:
        _error(report, case_id, f"invalid task_id: {task_id}")
    if status not in VALID_STATUS:
        _error(report, case_id, f"invalid pass_status: {status}")
    if boundary_flag not in VALID_BOUNDARY_FLAGS:
        _error(report, case_id, f"invalid boundary_flag: {boundary_flag}")

    _audit_dialogue(case_id, dialogue, report)
    turns = {item.get("turn") for item in dialogue}
    _audit_violations(case_id, p0_violations, turns, VALID_P0_RULES, "P0", report)
    _audit_violations(case_id, p1_violations, turns, VALID_P1_RULES, "P1", report)

    if set(dimension_scores) != set(DIMENSION_WEIGHTS):
        _error(report, case_id, "dimension_scores keys do not match rubric")
    else:
        expected_score = compute_final_score(dimension_scores, len(p0_violations), len(p1_violations))
        actual_score = annotation.get("total_score")
        delta = round(float(actual_score) - expected_score, 4)
        if abs(delta) > 0.01:
            report.score_deltas[case_id] = delta
            _error(report, case_id, f"total_score mismatch: actual={actual_score}, expected={expected_score:g}")

    if status == "PASS" and (p0_violations or p1_violations):
        _error(report, case_id, "PASS case must not contain P0/P1 violations")
    if status == "CAPPED_P1" and not p1_violations:
        _error(report, case_id, "CAPPED_P1 case must contain at least one P1 violation")
    if status == "FAIL_P0" and not p0_violations:
        _error(report, case_id, "FAIL_P0 case must contain at least one P0 violation")

    for target in case.get("coverage_targets", []):
        if not isinstance(target, str) or not target.startswith(VALID_COVERAGE_PREFIXES):
            _error(report, case_id, f"invalid coverage target: {target}")

    if not isinstance(case.get("adversarial_traits", []), list):
        _error(report, case_id, "adversarial_traits must be a list")


def _audit_dialogue(case_id: str, dialogue: list[dict[str, Any]], report: AuditReport) -> None:
    if not 6 <= len(dialogue) <= 15:
        _error(report, case_id, f"dialogue length must be 6-15, got {len(dialogue)}")
    expected_turns = list(range(len(dialogue)))
    actual_turns = [item.get("turn") for item in dialogue]
    if actual_turns != expected_turns:
        _error(report, case_id, "dialogue turns must be contiguous from 0")
    if dialogue and dialogue[0].get("role") != "assistant":
        _error(report, case_id, "dialogue must start with assistant")
    for index, item in enumerate(dialogue):
        role = item.get("role")
        if role not in {"assistant", "user"}:
            _error(report, case_id, f"invalid role at turn {index}: {role}")
        if index and role == dialogue[index - 1].get("role"):
            _error(report, case_id, f"roles must alternate at turn {index}")


def _audit_violations(
    case_id: str,
    violations: list[dict[str, Any]],
    turns: set[int],
    valid_rules: set[str],
    expected_severity: str,
    report: AuditReport,
) -> None:
    for violation in violations:
        rule_id = violation.get("rule_id")
        evidence_turn = violation.get("evidence_turn")
        if rule_id not in valid_rules:
            _error(report, case_id, f"invalid {expected_severity} rule_id: {rule_id}")
        if evidence_turn not in turns:
            _error(report, case_id, f"evidence_turn does not exist: {evidence_turn}")
        if violation.get("severity") != expected_severity:
            _error(report, case_id, f"wrong severity for {rule_id}: {violation.get('severity')}")
        if not violation.get("evidence_text"):
            _error(report, case_id, f"missing evidence_text for {rule_id}")


def _expect_distribution(report: AuditReport, key: str, expected: int, counter: Counter[str]) -> None:
    actual = counter.get(key, 0)
    if actual != expected:
        report.issues.append(AuditIssue("dataset", "error", f"{key} count expected {expected}, got {actual}"))


def _error(report: AuditReport, case_id: str, message: str) -> None:
    report.issues.append(AuditIssue(case_id, "error", message))
