"""Replay mode — run evaluation pipeline on pre-recorded dialogue traces.

Bypasses LLM calls entirely. Useful for:
- Demo stability (no API rate limits)
- Deterministic regression testing
- Fast iteration on scoring logic

Trace format (JSONL or JSON array):
    {
        "scenario_id": "cooperative_01",
        "scenario": {...},  # original scenario dict
        "dialogue_history": [
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "..."},
            ...
        ]
    }
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.calibration.audit import compute_final_score
from src.checkers.auto_checker_builder import AutoCheckerBuilder
from src.checkers.severity_checker import SeverityChecker
from src.dsl.compiler import compile_dsl
from src.dsl.coverage import CoverageTracker
from src.dsl.state_tracker import StateTracker
from src.evaluators.cgads import CGADSConfig, CGADSRunner, _composite_coverage
from src.evaluators.llm_judge import LLMJudge
from src.llm_client import DeepSeekClient


def load_traces(path: str | Path) -> list[dict[str, Any]]:
    """Load replay traces from JSON or JSONL file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in text.strip().split("\n") if line.strip()]
    data = json.loads(text)
    if isinstance(data, list):
        return data
    return [data]


def replay_scenario(
    trace: dict[str, Any],
    parsed_task: dict[str, Any],
    dsl: Any,
    llm: DeepSeekClient | None = None,
) -> dict[str, Any]:
    """Replay a single pre-recorded dialogue and run evaluation."""
    scenario_id = trace.get("scenario_id", "replay")
    scenario = trace.get("scenario", {})
    dialogue = trace.get("dialogue_history", [])

    state_tracker = StateTracker(dsl, llm=None)
    checker = AutoCheckerBuilder(parsed_task)
    severity_checker = SeverityChecker(parsed_task, llm=None)

    rule_results: list[dict[str, Any]] = []
    severity_violations = []

    turn = 0
    for i, msg in enumerate(dialogue):
        if msg["role"] == "assistant":
            state_tracker.observe_agent(turn, msg["content"])
            if turn > 0:
                user_input = dialogue[i - 1]["content"] if i > 0 and dialogue[i - 1]["role"] == "user" else ""
                checks = checker.run_all(msg["content"], user_input, [
                    m["content"] for m in dialogue[:i] if m["role"] == "assistant"
                ])
                turn_violations = severity_checker.check_turn(
                    turn=turn,
                    agent_reply=msg["content"],
                    user_input=user_input,
                    dialogue_history=dialogue[:i + 1],
                    current_state=state_tracker.current_state,
                )
                severity_violations.extend(turn_violations)
                rule_results.append({
                    "turn": turn,
                    "results": [{"passed": r.passed, "rule_name": r.rule_name, "message": r.message} for r in checks],
                    "violations": [{"passed": r.passed, "rule_name": r.rule_name, "message": r.message} for r in checks if not r.passed],
                    "compliant": all(r.passed for r in checks),
                    "agent_reply": msg["content"],
                    "user_reply": user_input,
                })
        elif msg["role"] == "user":
            turn += 1
            state_tracker.step(turn, msg["content"], dialogue[:i + 1])

    total_turns = len(rule_results)
    compliant_turns = sum(1 for r in rule_results if r.get("compliant"))

    # LLM judge on replay (optional — skip if no llm)
    evaluation = {}
    if llm:
        judge = LLMJudge(parsed_task, llm=llm)
        evaluation = judge.full_evaluation(dialogue, compliant_turns, total_turns)

    dimension_scores = _derive_replay_scores(evaluation, compliant_turns, total_turns)
    p0_count, p1_count = severity_checker.count_by_severity(severity_violations)
    final_score = compute_final_score(dimension_scores, p0_count, p1_count)
    violation_rule_ids = severity_checker.get_violation_rule_ids(severity_violations)

    return {
        "scenario_id": scenario_id,
        "scenario": scenario,
        "dialogue_history": dialogue,
        "state_trace": state_tracker.export_trace(),
        "rule_results": rule_results,
        "compliant_turns": compliant_turns,
        "total_turns": total_turns,
        "terminal": True,
        "judge_evaluation": evaluation,
        "dimension_scores": dimension_scores,
        "p0_count": p0_count,
        "p1_count": p1_count,
        "final_score": final_score,
        "violation_rule_ids": violation_rule_ids,
        "severity_violations": [
            {"rule_id": v.rule_id, "severity": v.severity, "turn": v.turn,
             "evidence": v.evidence, "confidence": v.confidence}
            for v in severity_violations
        ],
        "satisfied_requirements": _infer_reqs(dsl, dialogue),
    }


def run_replay_pipeline(
    parsed_task: dict[str, Any],
    traces_path: str | Path,
    output_dir: str | Path = "data/eval",
    use_llm_judge: bool = False,
) -> dict[str, Any]:
    """Run full replay pipeline on pre-recorded traces."""
    started_at = datetime.now()
    dsl = compile_dsl(parsed_task)
    traces = load_traces(traces_path)
    llm = DeepSeekClient() if use_llm_judge else None

    coverage_tracker = CoverageTracker(dsl)
    results: list[dict[str, Any]] = []

    for trace in traces:
        result = replay_scenario(trace, parsed_task, dsl, llm)
        coverage_tracker.record_scenario(
            scenario_id=result["scenario_id"],
            state_updates=_adapt(result["state_trace"]),
            coverage_targets=trace.get("scenario", {}).get("coverage_targets", []),
            violation_rule_ids=result.get("violation_rule_ids", []),
            satisfied_requirements=result.get("satisfied_requirements", []),
        )
        results.append(result)

    report = coverage_tracker.report()
    output = {
        "pipeline_version": "eval_pipeline_v2_replay",
        "mode": "replay",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "parsed_task": parsed_task,
        "traces_path": str(traces_path),
        "scenario_count": len(results),
        "coverage_report": report.to_dict(),
        "uncovered_targets": report.uncovered_targets(),
        "composite_coverage": f"{_composite_coverage(report):.1%}",
        "scenario_results": results,
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    task_id = parsed_task.get("task_id", "unknown")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"eval_replay_{task_id}_{ts}.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    output["output_path"] = str(out_path)
    return output


def _derive_replay_scores(evaluation: dict, compliant_turns: int, total_turns: int) -> dict[str, int]:
    """Fallback dimension scores when LLM judge is not available."""
    if not evaluation:
        compliance_rate = compliant_turns / total_turns if total_turns else 0
        return {
            "task_completion": 3,
            "flow_state_adherence": 3,
            "constraint_compliance": max(1, min(5, round(1 + compliance_rate * 4))),
            "branch_handling": 3,
            "context_consistency": 3,
            "communication_experience": 3,
        }
    from run_eval_pipeline import derive_dimension_scores
    return derive_dimension_scores(evaluation, compliant_turns, total_turns, True)


def _infer_reqs(dsl: Any, dialogue: list[dict]) -> list[str]:
    text = "\n".join(m.get("content", "") for m in dialogue)
    satisfied = []
    for req in getattr(dsl, "atomic_requirements", []):
        desc = getattr(req, "description", "") or ""
        tokens = [t for t in desc.replace("，", " ").replace("。", " ").split() if len(t) >= 2]
        if tokens and any(t in text for t in tokens[:5]):
            satisfied.append(getattr(req, "id", ""))
    return [s for s in satisfied if s]


def _adapt(trace: list[dict]):
    for item in trace:
        yield type("_T", (), {
            "prev_state": item.get("prev_state", ""),
            "new_state": item.get("new_state", ""),
            "triggered_transition": item.get("transition"),
        })()
