"""CGADS Ablation Experiment: Random vs Stratified vs CGADS.

Compares three scenario selection strategies on identical task+budget,
measuring coverage, P0 discovery rate, and path redundancy.

Usage:
    python experiments/run_cgads_ablation.py --instruction_file data/tasks/rider_lottery.json --budget 8
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.calibration.audit import compute_final_score
from src.dsl.compiler import compile_dsl
from src.dsl.coverage import CoverageReport, CoverageTracker
from src.dsl.state_tracker import StateTracker
from src.evaluators.cgads import CGADSConfig, CGADSRunner, _composite_coverage
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator
from src.evaluators.three_layer_user_simulator import create_simulator_from_scenario
from src.instruction_parser.auto_parser import InstructionParser
from src.llm_client import DeepSeekClient

from run_eval_pipeline import run_scenario


def load_task(args: argparse.Namespace) -> dict[str, Any]:
    content = Path(args.instruction_file).read_text(encoding="utf-8")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        llm = DeepSeekClient()
        parser = InstructionParser(llm)
        return parser.parse(content)


def run_random_baseline(
    parsed_task: dict[str, Any],
    dsl: Any,
    llm: DeepSeekClient,
    budget: int,
    max_turns: int,
) -> dict[str, Any]:
    """Random: pick budget scenarios randomly from base pool."""
    generator = CoverageDrivenScenarioGenerator(dsl)
    all_scenarios = generator.generate_base()
    selected = random.sample(all_scenarios, min(budget, len(all_scenarios)))

    tracker = CoverageTracker(dsl)
    results = []
    for idx, scenario in enumerate(selected, 1):
        result = run_scenario(scenario, idx, parsed_task, dsl, llm, max_turns)
        tracker.record_scenario(
            scenario_id=result["scenario_id"],
            state_updates=_trace_adapter(result["state_trace"]),
            coverage_targets=scenario.get("coverage_targets", []),
            violation_rule_ids=result.get("violation_rule_ids", []),
            satisfied_requirements=result.get("satisfied_requirements", []),
        )
        results.append(result)

    report = tracker.report()
    return _build_summary("random", results, report, dsl)


def run_stratified_baseline(
    parsed_task: dict[str, Any],
    dsl: Any,
    llm: DeepSeekClient,
    budget: int,
    max_turns: int,
) -> dict[str, Any]:
    """Stratified: pick first N from base (already covers major persona types)."""
    generator = CoverageDrivenScenarioGenerator(dsl)
    scenarios = generator.generate_base()[:budget]

    tracker = CoverageTracker(dsl)
    results = []
    for idx, scenario in enumerate(scenarios, 1):
        result = run_scenario(scenario, idx, parsed_task, dsl, llm, max_turns)
        tracker.record_scenario(
            scenario_id=result["scenario_id"],
            state_updates=_trace_adapter(result["state_trace"]),
            coverage_targets=scenario.get("coverage_targets", []),
            violation_rule_ids=result.get("violation_rule_ids", []),
            satisfied_requirements=result.get("satisfied_requirements", []),
        )
        results.append(result)

    report = tracker.report()
    return _build_summary("stratified", results, report, dsl)


def run_cgads_method(
    parsed_task: dict[str, Any],
    dsl: Any,
    llm: DeepSeekClient,
    budget: int,
    max_turns: int,
) -> dict[str, Any]:
    """CGADS: adaptive loop with coverage feedback."""

    def _run_fn(scenario: dict[str, Any], index: int) -> dict[str, Any]:
        return run_scenario(scenario, index, parsed_task, dsl, llm, max_turns)

    warmup_k = max(2, budget // 2)
    config = CGADSConfig(budget=budget, warmup_k=warmup_k)
    runner = CGADSRunner(dsl=dsl, run_scenario_fn=_run_fn, config=config)
    cgads_report = runner.run()

    summary = _build_summary("cgads", cgads_report.results, cgads_report.coverage, dsl)
    summary["rounds"] = [
        {
            "round": r.round_num,
            "scenarios_run": r.scenarios_run,
            "coverage_before": f"{r.coverage_before:.1%}",
            "coverage_after": f"{r.coverage_after:.1%}",
        }
        for r in cgads_report.rounds
    ]
    summary["adequate"] = cgads_report.adequate
    summary["unreachable"] = cgads_report.unreachable_targets
    return summary


def _build_summary(
    method: str,
    results: list[dict[str, Any]],
    report: CoverageReport,
    dsl: Any,
) -> dict[str, Any]:
    composite = _composite_coverage(report)
    state_cov = len(report.state_visited) / max(len(report.state_total), 1)
    edge_cov = len(report.edge_triggered) / max(len(report.edge_total), 1)
    risk_cov = len(report.risk_tested) / max(len(report.risk_total), 1)
    req_cov = len(report.requirement_satisfied) / max(len(report.requirement_total), 1)

    all_violations = []
    for r in results:
        all_violations.extend(r.get("violation_rule_ids", []))
    p0_found = [v for v in all_violations if "p0" in v.lower()]

    state_traces = []
    for r in results:
        trace = tuple(
            item.get("new_state", "") for item in r.get("state_trace", [])
        )
        state_traces.append(trace)

    unique_paths = len(set(state_traces))
    redundancy = 1 - (unique_paths / max(len(state_traces), 1))

    return {
        "method": method,
        "scenarios_run": len(results),
        "composite_coverage": f"{composite:.1%}",
        "state_coverage": f"{state_cov:.1%}",
        "edge_coverage": f"{edge_cov:.1%}",
        "risk_coverage": f"{risk_cov:.1%}",
        "requirement_coverage": f"{req_cov:.1%}",
        "p0_found": len(set(p0_found)),
        "p0_total_possible": len([
            r for r in getattr(dsl, "severity_rules", [])
            if getattr(r, "level", getattr(r, "severity", "")) == "P0"
        ]),
        "unique_paths": unique_paths,
        "redundancy_rate": f"{redundancy:.1%}",
        "uncovered": report.uncovered_targets()[:10],
    }


def _trace_adapter(trace: list[dict[str, Any]]):
    """Lightweight adapter for CoverageTracker.record_scenario."""
    for item in trace:
        yield type("_T", (), {
            "prev_state": item.get("prev_state", ""),
            "new_state": item.get("new_state", ""),
            "triggered_transition": item.get("transition"),
        })()


def main() -> int:
    parser = argparse.ArgumentParser(description="CGADS ablation experiment")
    parser.add_argument("--instruction_file", required=True)
    parser.add_argument("--budget", type=int, default=8)
    parser.add_argument("--max_turns", type=int, default=12)
    parser.add_argument("--output_dir", default="experiments/reports")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    parsed_task = load_task(args)
    dsl = compile_dsl(parsed_task)
    llm = DeepSeekClient()

    print(f"=== CGADS Ablation (budget={args.budget}) ===\n")

    print("[1/3] Running Random baseline...")
    t0 = time.time()
    random_result = run_random_baseline(parsed_task, dsl, llm, args.budget, args.max_turns)
    random_result["elapsed_s"] = round(time.time() - t0, 1)
    print(f"  Coverage: {random_result['composite_coverage']}, P0 found: {random_result['p0_found']}\n")

    print("[2/3] Running Stratified baseline...")
    t0 = time.time()
    stratified_result = run_stratified_baseline(parsed_task, dsl, llm, args.budget, args.max_turns)
    stratified_result["elapsed_s"] = round(time.time() - t0, 1)
    print(f"  Coverage: {stratified_result['composite_coverage']}, P0 found: {stratified_result['p0_found']}\n")

    print("[3/3] Running CGADS...")
    t0 = time.time()
    cgads_result = run_cgads_method(parsed_task, dsl, llm, args.budget, args.max_turns)
    cgads_result["elapsed_s"] = round(time.time() - t0, 1)
    print(f"  Coverage: {cgads_result['composite_coverage']}, P0 found: {cgads_result['p0_found']}\n")

    comparison = {
        "experiment": "cgads_ablation",
        "budget": args.budget,
        "seed": args.seed,
        "task_id": parsed_task.get("task_id", "unknown"),
        "results": {
            "random": random_result,
            "stratified": stratified_result,
            "cgads": cgads_result,
        },
    }

    print("=== Comparison ===")
    print(f"{'Method':<12} {'Coverage':<12} {'P0 Found':<10} {'Redundancy':<12}")
    print("-" * 46)
    for method in ["random", "stratified", "cgads"]:
        r = comparison["results"][method]
        print(f"{method:<12} {r['composite_coverage']:<12} {r['p0_found']:<10} {r['redundancy_rate']:<12}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ablation_{parsed_task.get('task_id', 'unknown')}.json"
    out_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
