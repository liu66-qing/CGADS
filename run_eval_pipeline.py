"""End-to-end evaluation pipeline for outbound-call dialogue tasks.

Pipeline:
1. raw instruction -> InstructionParser -> parsed_task
2. parsed_task -> compile_dsl -> TaskDSL
3. DSL -> coverage-driven scenarios
4. scenario loop -> user simulator + state tracker + auto checks + LLM judge
5. aggregate coverage and write JSON results to data/eval/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows GBK编码修复：强制UTF-8输出
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - keeps the pipeline usable without tqdm installed.
    def tqdm(iterable, **_: Any):
        return iterable

from src.calibration.audit import compute_final_score
from src.checkers.auto_checker_builder import AutoCheckerBuilder
from src.checkers.severity_checker import SeverityChecker, SeverityViolation
from src.dsl.compiler import compile_dsl
from src.dsl.coverage import CoverageTracker
from src.dsl.state_tracker import StateTracker
from src.evaluators.cgads import CGADSConfig, CGADSRunner
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator
from src.evaluators.llm_judge import LLMJudge
from src.evaluators.three_layer_user_simulator import create_simulator_from_scenario
from src.instruction_parser.auto_parser import InstructionParser
from src.llm_client import DeepSeekClient


DEFAULT_MAX_TURNS = 12
DEFAULT_MAX_SCENARIOS = 20  # 修复：原值10导致只跑2/8场景，提升到20以容纳base 8个+gap场景


AGENT_SYSTEM_PROMPT = """你是外呼数字人，请严格按任务指令和当前对话状态回复。

要求：
1. 只输出客服一句话，不要解释推理过程。
2. 回复自然、简短、适合电话沟通。
3. 不索要敏感信息，不作绝对化承诺，不绕过官方渠道。
4. 用户拒绝或挂断时礼貌结束。

任务角色：{role}
任务目标：{goal}
开场白：{opening_line}
流程摘要：
{flow_summary}
FAQ：
{faq_summary}
约束：
{constraints}
当前状态：{state}
当前槽位：{slots}
"""


def load_instruction(args: argparse.Namespace) -> str | dict:
    """Load instruction. Returns str (raw) or dict (pre-parsed JSON)."""
    if args.instruction_text:
        return args.instruction_text
    if args.instruction_file:
        content = Path(args.instruction_file).read_text(encoding="utf-8")
        if getattr(args, "parsed", False) or args.instruction_file.endswith(".json"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
        return content
    raise ValueError("Either --instruction_file or --instruction_text is required.")


def safe_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: safe_to_dict(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_to_dict(v) for v in value]
    if isinstance(value, tuple):
        return [safe_to_dict(v) for v in value]
    if isinstance(value, set):
        return sorted(safe_to_dict(v) for v in value)
    return value


def flow_summary(parsed_task: dict[str, Any]) -> str:
    steps = parsed_task.get("flow", [])
    if not steps:
        return "- 无"
    return "\n".join(
        f"- {step.get('condition', '')}: {step.get('action', '')}"
        for step in steps
    )


def faq_summary(parsed_task: dict[str, Any]) -> str:
    faq = parsed_task.get("faq", [])
    if not faq:
        return "- 无"
    return "\n".join(
        f"- {item.get('question_type', '')}: {item.get('answer', '')}"
        for item in faq
    )


def build_agent_prompt(parsed_task: dict[str, Any], state_tracker: StateTracker) -> str:
    constraints = "\n".join(f"- {item}" for item in parsed_task.get("constraints", [])) or "- 无"
    return AGENT_SYSTEM_PROMPT.format(
        role=parsed_task.get("role", ""),
        goal=parsed_task.get("goal", ""),
        opening_line=parsed_task.get("opening_line", ""),
        flow_summary=flow_summary(parsed_task),
        faq_summary=faq_summary(parsed_task),
        constraints=constraints,
        state=state_tracker.current_state,
        slots=json.dumps(state_tracker.slots, ensure_ascii=False),
    )


def generate_agent_reply(
    llm: DeepSeekClient,
    parsed_task: dict[str, Any],
    state_tracker: StateTracker,
    history: list[dict[str, str]],
) -> tuple[str, str | None]:
    system_prompt = build_agent_prompt(parsed_task, state_tracker)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-10:])
    try:
        reply = llm.chat(messages, max_tokens=256, temperature=0.3)
        reply = (reply or "").strip()
        if not reply:
            return fallback_agent_reply(state_tracker), "empty_llm_reply"
        return reply, None
    except Exception as exc:  # noqa: BLE001 - scenario-level fault tolerance.
        return fallback_agent_reply(state_tracker), f"{exc.__class__.__name__}: {exc}"


def fallback_agent_reply(state_tracker: StateTracker) -> str:
    state_id = state_tracker.current_state
    if state_id in {"refusal_exit", "closing"}:
        return "好的，打扰了，祝您顺利。"
    if state_id == "auth_or_trust":
        return "您可通过官方App或后台消息核实。"
    if state_id == "busy_handling":
        return "占用半分钟，我简短说明重点。"
    return "我先为您说明本次通知的重点。"


def run_rule_checks(
    checker: AutoCheckerBuilder,
    agent_reply: str,
    user_reply: str,
    history: list[dict[str, str]],
) -> dict[str, Any]:
    assistant_history = [m["content"] for m in history if m.get("role") == "assistant"]
    results = checker.run_all(agent_reply, user_reply, assistant_history)
    result_dicts = [safe_to_dict(item) for item in results]
    violations = [item for item in result_dicts if not item.get("passed", True)]
    return {
        "results": result_dicts,
        "violations": violations,
        "compliant": not violations,
    }


def is_terminal_state(state_tracker: StateTracker) -> bool:
    try:
        state = state_tracker.dsl.state_by_id(state_tracker.current_state)
        return bool(getattr(state, "terminal", False))
    except Exception:
        return state_tracker.current_state in {"closing", "refusal_exit", "handoff_or_escalation"}


def infer_satisfied_requirements(dsl: Any, dialogue: list[dict[str, str]]) -> list[str]:
    text = "\n".join(item.get("content", "") for item in dialogue)
    satisfied: list[str] = []
    for req in getattr(dsl, "atomic_requirements", []):
        desc = getattr(req, "description", "") or ""
        tokens = [token for token in desc.replace("，", " ").replace("。", " ").split() if len(token) >= 2]
        if tokens and any(token in text for token in tokens[:5]):
            satisfied.append(getattr(req, "id", ""))
    return [item for item in satisfied if item]


def derive_dimension_scores(
    eval_result: dict[str, Any],
    compliant_turns: int,
    total_turns: int,
    terminal: bool,
) -> dict[str, int]:
    averages = eval_result.get("averages", {}) if eval_result else {}
    dialogue_score = eval_result.get("dialogue_score", {}) if eval_result else {}

    task_completion = 5 if dialogue_score.get("task_completed") else 3
    if total_turns == 0:
        task_completion = 1

    flow_state_adherence = 5 if dialogue_score.get("flow_followed") else 3
    if not terminal:
        flow_state_adherence = min(flow_state_adherence, 3)

    compliance_rate = compliant_turns / total_turns if total_turns else 0
    constraint_compliance = max(1, min(5, round(1 + compliance_rate * 4)))

    branch_handling = int(round(averages.get("avg_cohesion", 3)))
    context_consistency = int(round(averages.get("avg_knowledge", 3)))
    communication_experience = int(dialogue_score.get("user_experience", 3) or 3)

    return {
        "task_completion": _clamp_score(task_completion),
        "flow_state_adherence": _clamp_score(flow_state_adherence),
        "constraint_compliance": _clamp_score(constraint_compliance),
        "branch_handling": _clamp_score(branch_handling),
        "context_consistency": _clamp_score(context_consistency),
        "communication_experience": _clamp_score(communication_experience),
    }


def _clamp_score(value: int | float) -> int:
    return max(1, min(5, int(round(value))))


def run_scenario(
    scenario: dict[str, Any],
    scenario_index: int,
    parsed_task: dict[str, Any],
    dsl: Any,
    llm: DeepSeekClient,
    max_turns: int,
) -> dict[str, Any]:
    scenario_id = scenario.get("name") or f"scenario_{scenario_index:03d}"
    user_sim = create_simulator_from_scenario(scenario, llm)
    state_tracker = StateTracker(dsl, llm)
    checker = AutoCheckerBuilder(parsed_task)
    severity_checker = SeverityChecker(parsed_task, llm)

    opening = parsed_task.get("opening_line") or fallback_agent_reply(state_tracker)
    dialogue: list[dict[str, str]] = [{"role": "assistant", "content": opening}]
    rule_results: list[dict[str, Any]] = []
    severity_violations: list[SeverityViolation] = []
    llm_errors: list[str] = []
    terminal = False

    last_agent_reply = opening
    state_tracker.observe_agent(0, opening)

    for turn in range(1, max_turns + 1):
        user_reply = user_sim.respond(last_agent_reply)
        dialogue.append({"role": "user", "content": user_reply})

        state_update = state_tracker.step(turn, user_reply, dialogue)
        terminal = is_terminal_state(state_tracker)

        agent_reply, error = generate_agent_reply(llm, parsed_task, state_tracker, dialogue)
        if error:
            llm_errors.append(f"turn {turn}: {error}")
        dialogue.append({"role": "assistant", "content": agent_reply})

        agent_slot_updates = state_tracker.observe_agent(turn, agent_reply)
        checks = run_rule_checks(checker, agent_reply, user_reply, dialogue)

        turn_violations = severity_checker.check_turn(
            turn=turn,
            agent_reply=agent_reply,
            user_input=user_reply,
            dialogue_history=dialogue,
            current_state=state_tracker.current_state,
        )
        severity_violations.extend(turn_violations)

        checks.update(
            {
                "turn": turn,
                "state_update": safe_to_dict(state_update),
                "agent_slot_updates": agent_slot_updates,
                "user_reply": user_reply,
                "agent_reply": agent_reply,
                "severity_violations": [
                    {"rule_id": v.rule_id, "severity": v.severity, "confidence": v.confidence}
                    for v in turn_violations
                ],
            }
        )
        rule_results.append(checks)

        last_agent_reply = agent_reply
        if user_sim.should_hangup() or terminal:
            terminal = terminal or user_sim.should_hangup()
            break

    total_turns = len(rule_results)
    compliant_turns = sum(1 for item in rule_results if item.get("compliant"))
    judge = LLMJudge(parsed_task, llm=llm)
    evaluation = judge.full_evaluation(dialogue, compliant_turns, total_turns)
    dimension_scores = derive_dimension_scores(evaluation, compliant_turns, total_turns, terminal)

    p0_count, p1_count = severity_checker.count_by_severity(severity_violations)
    final_score = compute_final_score(dimension_scores, p0_count, p1_count)

    violation_rule_ids = severity_checker.get_violation_rule_ids(severity_violations)
    # Also include basic constraint checker violations for backward compat
    for item in rule_results:
        for violation in item.get("violations", []):
            rule_name = violation.get("rule_name") or violation.get("rule")
            if rule_name and rule_name not in violation_rule_ids:
                violation_rule_ids.append(rule_name)

    return {
        "scenario_id": scenario_id,
        "scenario_index": scenario_index,
        "scenario": scenario,
        "dialogue_history": dialogue,
        "state_trace": state_tracker.export_trace(),
        "user_state_trace": user_sim.export_state_trace(),
        "rule_results": rule_results,
        "compliant_turns": compliant_turns,
        "total_turns": total_turns,
        "terminal": terminal,
        "llm_errors": llm_errors,
        "judge_evaluation": evaluation,
        "dimension_scores": dimension_scores,
        "p0_count": p0_count,
        "p1_count": p1_count,
        "final_score": final_score,
        "violation_rule_ids": violation_rule_ids,
        "severity_violations": [
            {
                "rule_id": v.rule_id,
                "severity": v.severity,
                "turn": v.turn,
                "evidence": v.evidence,
                "confidence": v.confidence,
                "confirmed": v.confirmed,
            }
            for v in severity_violations
        ],
        "satisfied_requirements": infer_satisfied_requirements(dsl, dialogue),
    }


def run_pipeline(
    raw_instruction: str | dict,
    max_scenarios: int = DEFAULT_MAX_SCENARIOS,
    max_turns: int = DEFAULT_MAX_TURNS,
    output_dir: str | Path = "data/eval",
    use_cgads: bool = False,
    cgads_budget: int = 12,
    cgads_warmup: int = 4,
) -> dict[str, Any]:
    started_at = datetime.now()
    llm = DeepSeekClient()

    if isinstance(raw_instruction, dict):
        parsed_task = raw_instruction
    else:
        parser = InstructionParser(llm)
        parsed_task = parser.parse(raw_instruction)
    dsl = compile_dsl(parsed_task)

    if use_cgads:
        return _run_cgads_pipeline(
            dsl=dsl,
            parsed_task=parsed_task,
            llm=llm,
            max_turns=max_turns,
            output_dir=output_dir,
            budget=cgads_budget,
            warmup_k=cgads_warmup,
            started_at=started_at,
        )

    generator = CoverageDrivenScenarioGenerator(dsl)
    scenarios = generator.generate_base()[:max_scenarios]
    coverage_tracker = CoverageTracker(dsl)

    scenario_results: list[dict[str, Any]] = []
    for index, scenario in enumerate(tqdm(scenarios, desc="scenarios"), start=1):
        scenario_id = scenario.get("name") or f"scenario_{index:03d}"
        try:
            result = run_scenario(
                scenario=scenario,
                scenario_index=index,
                parsed_task=parsed_task,
                dsl=dsl,
                llm=llm,
                max_turns=max_turns,
            )
            coverage_tracker.record_scenario(
                scenario_id=scenario_id,
                state_updates=StateTrackerTraceAdapter(result["state_trace"]),
                coverage_targets=scenario.get("coverage_targets", []),
                violation_rule_ids=result.get("violation_rule_ids", []),
                satisfied_requirements=result.get("satisfied_requirements", []),
            )
            scenario_results.append(result)
        except Exception as exc:  # noqa: BLE001 - pipeline must continue.
            scenario_results.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_index": index,
                    "scenario": scenario,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )

    coverage_report = coverage_tracker.report()
    output = {
        "pipeline_version": "eval_pipeline_v2",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "parsed_task": parsed_task,
        "dsl": safe_to_dict(dsl),
        "scenario_count": len(scenarios),
        "success_count": sum(1 for item in scenario_results if "error" not in item),
        "error_count": sum(1 for item in scenario_results if "error" in item),
        "coverage_report": coverage_report.to_dict(),
        "uncovered_targets": coverage_report.uncovered_targets(),
        "scenario_results": safe_to_dict(scenario_results),
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    task_id = parsed_task.get("task_id", "unknown_task")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = out_dir / f"eval_pipeline_{task_id}_{timestamp}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    output["output_path"] = str(output_path)
    return output


def _run_cgads_pipeline(
    dsl: Any,
    parsed_task: dict[str, Any],
    llm: DeepSeekClient,
    max_turns: int,
    output_dir: str | Path,
    budget: int,
    warmup_k: int,
    started_at: datetime,
) -> dict[str, Any]:
    """Run pipeline with CGADS adaptive loop."""

    def _run_scenario_fn(scenario: dict[str, Any], index: int) -> dict[str, Any]:
        return run_scenario(
            scenario=scenario,
            scenario_index=index,
            parsed_task=parsed_task,
            dsl=dsl,
            llm=llm,
            max_turns=max_turns,
        )

    config = CGADSConfig(budget=budget, warmup_k=warmup_k)
    runner = CGADSRunner(dsl=dsl, run_scenario_fn=_run_scenario_fn, config=config)
    cgads_report = runner.run()

    coverage_report = cgads_report.coverage
    output = {
        "pipeline_version": "eval_pipeline_v2_cgads",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "parsed_task": parsed_task,
        "dsl": safe_to_dict(dsl),
        "mode": "cgads",
        "cgads_config": {"budget": budget, "warmup_k": warmup_k},
        "cgads_rounds": [
            {
                "round": r.round_num,
                "scenarios_run": r.scenarios_run,
                "coverage_before": f"{r.coverage_before:.1%}",
                "coverage_after": f"{r.coverage_after:.1%}",
                "gaps_before": r.gaps_before[:10],
                "new_findings": r.new_findings,
                "duration_s": round(r.duration_s, 1),
            }
            for r in cgads_report.rounds
        ],
        "adequate": cgads_report.adequate,
        "unreachable_targets": cgads_report.unreachable_targets,
        "scenario_count": cgads_report.total_scenarios,
        "success_count": sum(1 for r in cgads_report.results if "error" not in r),
        "error_count": sum(1 for r in cgads_report.results if "error" in r),
        "coverage_report": coverage_report.to_dict(),
        "uncovered_targets": coverage_report.uncovered_targets(),
        "scenario_results": safe_to_dict(cgads_report.results),
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    task_id = parsed_task.get("task_id", "unknown_task")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = out_dir / f"eval_cgads_{task_id}_{timestamp}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    output["output_path"] = str(output_path)

    for line in cgads_report.summary_lines():
        print(line)

    return output


class StateTrackerTraceAdapter:
    """Adapter from exported state trace dicts back to CoverageTracker fields."""

    def __init__(self, trace: list[dict[str, Any]]):
        self.trace = trace

    def __iter__(self):
        for item in self.trace:
            yield TraceUpdate(
                prev_state=item.get("prev_state", ""),
                new_state=item.get("new_state", ""),
                triggered_transition=item.get("transition"),
            )


class TraceUpdate:
    def __init__(self, prev_state: str, new_state: str, triggered_transition: str | None):
        self.prev_state = prev_state
        self.new_state = new_state
        self.triggered_transition = triggered_transition


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full outbound dialogue evaluation pipeline.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--instruction_file", help="Path to raw instruction text file.")
    source.add_argument("--instruction_text", help="Raw instruction text.")
    parser.add_argument("--max_scenarios", type=int, default=DEFAULT_MAX_SCENARIOS)
    parser.add_argument("--max_turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--output_dir", default="data/eval")
    parser.add_argument("--cgads", action="store_true", help="Enable CGADS adaptive loop")
    parser.add_argument("--cgads_budget", type=int, default=12, help="CGADS total scenario budget")
    parser.add_argument("--cgads_warmup", type=int, default=4, help="CGADS warmup scenario count")
    parser.add_argument("--replay", help="Path to pre-recorded traces file (JSON/JSONL) for replay mode")
    parser.add_argument("--replay_with_judge", action="store_true", help="Use LLM judge in replay mode")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.replay:
        from src.evaluators.replay_mode import run_replay_pipeline
        raw_instruction = load_instruction(args)
        parsed_task = raw_instruction if isinstance(raw_instruction, dict) else InstructionParser(DeepSeekClient()).parse(raw_instruction)
        result = run_replay_pipeline(
            parsed_task=parsed_task,
            traces_path=args.replay,
            output_dir=args.output_dir,
            use_llm_judge=args.replay_with_judge,
        )
        print(json.dumps(
            {
                "mode": "replay",
                "output_path": result["output_path"],
                "scenario_count": result["scenario_count"],
                "composite_coverage": result["composite_coverage"],
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    raw_instruction = load_instruction(args)
    result = run_pipeline(
        raw_instruction=raw_instruction,
        max_scenarios=args.max_scenarios,
        max_turns=args.max_turns,
        output_dir=args.output_dir,
        use_cgads=args.cgads,
        cgads_budget=args.cgads_budget,
        cgads_warmup=args.cgads_warmup,
    )
    print(json.dumps(
        {
            "output_path": result["output_path"],
            "scenario_count": result["scenario_count"],
            "success_count": result["success_count"],
            "error_count": result["error_count"],
            "uncovered_targets": len(result["uncovered_targets"]),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
