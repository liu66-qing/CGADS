import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.checkers.severity_rules import valid_rule_ids


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
VALID_P0 = valid_rule_ids("P0")
VALID_P1 = valid_rule_ids("P1")
REQUIRED_ANNOTATION = {
    "total_score",
    "pass_status",
    "boundary_flag",
    "p0_violations",
    "p1_violations",
    "dimension_scores",
    "failed_turns",
    "failure_reasons",
    "suggestions",
}
DIMENSIONS = {
    "task_completion",
    "flow_state_adherence",
    "constraint_compliance",
    "branch_handling",
    "context_consistency",
    "communication_experience",
}
DIMENSION_WEIGHTS = {
    "task_completion": 25,
    "flow_state_adherence": 20,
    "constraint_compliance": 20,
    "branch_handling": 15,
    "context_consistency": 10,
    "communication_experience": 10,
}


def expected_total_score(dimension_scores, p0_count, p1_count):
    raw = sum(dimension_scores[key] / 5 * weight for key, weight in DIMENSION_WEIGHTS.items())
    if p0_count:
        return min(raw, 30)
    if p1_count >= 3:
        return min(raw, 50)
    if p1_count == 2:
        return min(raw, 60)
    if p1_count == 1:
        return min(raw, 70)
    return raw


def load_cases(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def validate_case(case):
    assert case["task_id"] in VALID_TASKS, case["case_id"]
    ann = case["human_annotation"]
    assert REQUIRED_ANNOTATION <= ann.keys(), case["case_id"]
    assert ann["pass_status"] in VALID_STATUS, case["case_id"]
    assert ann["boundary_flag"] in VALID_BOUNDARY_FLAGS, case["case_id"]
    assert DIMENSIONS == ann["dimension_scores"].keys(), case["case_id"]
    expected_score = expected_total_score(
        ann["dimension_scores"],
        len(ann["p0_violations"]),
        len(ann["p1_violations"]),
    )
    assert abs(float(ann["total_score"]) - expected_score) <= 0.01, case["case_id"]
    assert 6 <= len(case["dialogue"]) <= 15, case["case_id"]
    turns = {t["turn"] for t in case["dialogue"]}
    assert turns == set(range(len(case["dialogue"]))), case["case_id"]
    assert case["dialogue"][0]["role"] == "assistant", case["case_id"]
    for i, item in enumerate(case["dialogue"]):
        assert item["turn"] == i, case["case_id"]
        assert item["role"] in {"assistant", "user"}, case["case_id"]
        if i:
            assert item["role"] != case["dialogue"][i - 1]["role"], case["case_id"]
    for violation in ann["p0_violations"]:
        assert violation["rule_id"] in VALID_P0, (case["case_id"], violation["rule_id"])
        assert violation["evidence_turn"] in turns, case["case_id"]
        assert violation["severity"] == "P0", case["case_id"]
    for violation in ann["p1_violations"]:
        assert violation["rule_id"] in VALID_P1, (case["case_id"], violation["rule_id"])
        assert violation["evidence_turn"] in turns, case["case_id"]
        assert violation["severity"] == "P1", case["case_id"]
    if ann["pass_status"] == "FAIL_P0":
        assert ann["p0_violations"], case["case_id"]
        assert ann["total_score"] <= 30, case["case_id"]
    if ann["pass_status"] == "CAPPED_P1":
        assert ann["p1_violations"], case["case_id"]
        assert ann["total_score"] <= 70, case["case_id"]
    for target in case["coverage_targets"]:
        assert target.startswith(VALID_COVERAGE_PREFIXES), (case["case_id"], target)
    assert isinstance(case.get("adversarial_traits", []), list), case["case_id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="gold_standard_v1.jsonl")
    parser.add_argument("--strict30", action="store_true")
    args = parser.parse_args()

    path = Path(args.path)
    cases = load_cases(path)
    for case in cases:
        validate_case(case)

    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids)), "duplicate case_id"
    if args.strict30:
        assert len(cases) == 30
        assert ids == [f"calib_{i:03d}" for i in range(1, 31)]
        status = Counter(c["human_annotation"]["pass_status"] for c in cases)
        assert status["PASS"] == 10
        assert status["CAPPED_P1"] == 12
        assert status["FAIL_P0"] == 8
        task = Counter(c["task_id"] for c in cases)
        assert task["rider_lottery_notify"] == 15
        assert task["course_live_switch"] == 15
    print(json.dumps({"cases": len(cases), "status": Counter(c["human_annotation"]["pass_status"] for c in cases)}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
