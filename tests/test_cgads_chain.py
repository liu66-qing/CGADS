"""Dry-run verification of CGADS chain logic (no LLM required).

Tests:
1. CGADSRunner calls run_scenario_fn correctly
2. Coverage tracker accumulates risk from violation_rule_ids
3. Gap generation produces targeting scenarios for uncovered risks
4. Adequacy check works
5. Unreachable targets handled after max retries
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dsl.compiler import compile_dsl
from src.dsl.coverage import CoverageTracker
from src.evaluators.cgads import (
    CGADSConfig,
    CGADSRunner,
    _composite_coverage,
    _expected_gain,
    rank_by_expected_gain,
    select_by_expected_gain,
)
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator


def make_mock_parsed_task() -> dict:
    return {
        "task_id": "test_cgads_verify",
        "role": "测试客服",
        "goal": "验证CGADS链路",
        "opening_line": "您好",
        "flow": [
            {"condition": "接通", "action": "问候+表明身份"},
            {"condition": "确认身份", "action": "说明事项"},
            {"condition": "用户同意", "action": "确认完成"},
        ],
        "faq": [{"question_type": "费用", "answer": "免费"}],
        "constraints": ["回复不超过30字", "不能承诺一定通过"],
        "forbidden": ["保证中奖"],
        "end_conditions": ["用户挂断"],
        "max_reply_length": 30,
    }


def make_mock_result(scenario: dict, index: int, states: list[str], violations: list[str]) -> dict:
    """Simulate a run_scenario return value."""
    trace = []
    for i in range(len(states) - 1):
        trace.append({
            "prev_state": states[i],
            "new_state": states[i + 1],
            "transition": f"{states[i]}->{states[i + 1]}",
        })
    return {
        "scenario_id": scenario.get("name", f"scenario_{index:03d}"),
        "scenario_index": index,
        "scenario": scenario,
        "dialogue_history": [
            {"role": "assistant", "content": "您好"},
            {"role": "user", "content": "你好"},
        ],
        "state_trace": trace,
        "user_state_trace": [],
        "rule_results": [],
        "compliant_turns": 1,
        "total_turns": 1,
        "terminal": True,
        "llm_errors": [],
        "judge_evaluation": {},
        "dimension_scores": {},
        "p0_count": len([v for v in violations if "p0" in v]),
        "p1_count": len([v for v in violations if "p1" in v]),
        "final_score": 70,
        "violation_rule_ids": violations,
        "satisfied_requirements": [],
    }


def test_cgads_basic_flow():
    """Test: CGADS runs warmup + gap rounds, accumulates coverage."""
    parsed = make_mock_parsed_task()
    dsl = compile_dsl(parsed)

    call_log = []

    def mock_run(scenario: dict, index: int) -> dict:
        call_log.append(scenario.get("name", f"idx_{index}"))
        # Simulate different paths based on scenario
        if "refusal" in scenario.get("name", "").lower():
            return make_mock_result(scenario, index,
                                    ["opening", "refusal_exit"],
                                    ["p1_refusal_continue_pitch"])
        elif "skeptical" in scenario.get("name", "").lower():
            return make_mock_result(scenario, index,
                                    ["opening", "auth_or_trust", "benefit_explain"],
                                    [])
        elif "inducement" in scenario.get("name", "").lower():
            return make_mock_result(scenario, index,
                                    ["opening", "benefit_explain"],
                                    ["p0_false_absolute_promise"])
        else:
            return make_mock_result(scenario, index,
                                    ["opening", "benefit_explain", "closing"],
                                    [])

    config = CGADSConfig(budget=8, warmup_k=4, max_rounds=3, max_retry_per_target=2)
    runner = CGADSRunner(dsl=dsl, run_scenario_fn=mock_run, config=config)
    report = runner.run()

    print(f"Scenarios run: {report.total_scenarios}")
    print(f"Rounds: {len(report.rounds)}")
    print(f"Adequate: {report.adequate}")
    print(f"Unreachable: {report.unreachable_targets}")
    print(f"Coverage: {_composite_coverage(report.coverage):.1%}")

    for r in report.rounds:
        print(f"  Round {r.round_num}: {r.scenarios_run} scenarios, "
              f"{r.coverage_before:.0%} -> {r.coverage_after:.0%}")

    assert report.total_scenarios >= 4, f"Expected >=4, got {report.total_scenarios}"
    assert len(report.rounds) >= 1, "Expected at least 1 round"
    assert report.coverage.risk_tested, "Expected some risk coverage from violations"
    print("\n[PASS] test_cgads_basic_flow")


def test_expected_gain_priority():
    """Test: P0 risk targets get highest priority."""
    assert _expected_gain("risk:p0_something") == 0.4
    assert _expected_gain("risk:p1_something") == 0.3
    assert _expected_gain("edge:a->b") == 0.2
    assert _expected_gain("state:opening") == 0.15
    assert _expected_gain("requirement:req1") == 0.1
    print("[PASS] test_expected_gain_priority")


def test_coverage_tracker_risk_mapping():
    """Test: violation_rule_ids flow into risk_tested."""
    parsed = make_mock_parsed_task()
    dsl = compile_dsl(parsed)
    tracker = CoverageTracker(dsl)

    # Record a scenario with a P0 violation
    trace = [type("T", (), {"prev_state": "opening", "new_state": "closing", "triggered_transition": "opening->closing"})()]
    tracker.record_scenario(
        scenario_id="test1",
        state_updates=trace,
        violation_rule_ids=["p0_sensitive_info_request"],
    )

    report = tracker.report()
    assert "p0_sensitive_info_request" in report.risk_tested, \
        f"Expected p0_sensitive_info_request in risk_tested, got {report.risk_tested}"
    print("[PASS] test_coverage_tracker_risk_mapping")


def test_scenario_ranking():
    """Test: scenarios ranked by expected gain against uncovered targets."""
    parsed = make_mock_parsed_task()
    dsl = compile_dsl(parsed)
    tracker = CoverageTracker(dsl)
    report = tracker.report()  # everything uncovered

    scenarios = [
        {"name": "low_gain", "coverage_targets": ["state:opening"]},
        {"name": "high_gain", "coverage_targets": ["risk:p0_sensitive_info_request", "edge:opening->refusal_exit"]},
        {"name": "medium_gain", "coverage_targets": ["edge:opening->closing"]},
    ]

    ranked = rank_by_expected_gain(scenarios, report)
    assert ranked[0]["name"] == "high_gain", f"Expected high_gain first, got {ranked[0]['name']}"
    print("[PASS] test_scenario_ranking")


def test_severity_checker_basic():
    """Test: SeverityChecker detects keyword-level P0."""
    from src.checkers.severity_checker import SeverityChecker

    checker = SeverityChecker(make_mock_parsed_task(), llm=None)
    violations = checker.check_turn(
        turn=1,
        agent_reply="请您把身份证号发给我核实一下",
        user_input="你好",
        dialogue_history=[
            {"role": "assistant", "content": "请您把身份证号发给我核实一下"}
        ],
    )
    p0_ids = [v.rule_id for v in violations if v.severity == "P0"]
    assert "p0_sensitive_info_request" in p0_ids, f"Expected P0 hit, got {p0_ids}"
    print("[PASS] test_severity_checker_basic")


def test_severity_checker_false_promise():
    """Test: SeverityChecker catches absolute promise."""
    from src.checkers.severity_checker import SeverityChecker

    checker = SeverityChecker(make_mock_parsed_task(), llm=None)
    violations = checker.check_turn(
        turn=2,
        agent_reply="我保证您一定能中奖，放心好了",
        user_input="真的假的",
        dialogue_history=[],
    )
    p0_ids = [v.rule_id for v in violations if v.severity == "P0"]
    assert "p0_false_absolute_promise" in p0_ids, f"Expected false_promise P0, got {p0_ids}"
    print("[PASS] test_severity_checker_false_promise")


if __name__ == "__main__":
    test_expected_gain_priority()
    test_coverage_tracker_risk_mapping()
    test_scenario_ranking()
    test_severity_checker_basic()
    test_severity_checker_false_promise()
    test_cgads_basic_flow()
    print("\n=== ALL TESTS PASSED ===")
