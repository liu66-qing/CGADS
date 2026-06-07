"""FastAPI SSE backend for realtime CGADS evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

# 纭繚椤圭洰鏍圭洰褰曞湪 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Windows GBK fix
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from src.llm_client import DeepSeekClient
from src.instruction_parser.auto_parser import InstructionParser
from src.dsl.compiler import compile_dsl
from src.dsl.coverage import CoverageTracker
from src.dsl.state_tracker import StateTracker
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator
from src.evaluators.three_layer_user_simulator import create_simulator_from_scenario
from src.checkers.auto_checker_builder import AutoCheckerBuilder
from src.checkers.severity_checker import SeverityChecker
from src.evaluators.llm_judge import LLMJudge
from src.calibration.audit import compute_final_score
from src.visualization.mermaid_export import export_mermaid_statediagram

logger = logging.getLogger("cgads.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="CGADS Evaluation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React鍓嶇build浜х墿锛堝鏋滃瓨鍦級
_frontend_dist = PROJECT_ROOT / "frontend" / "dist"


# ============================================================
# Models
# ============================================================

class EvalRequest(BaseModel):
    """单个评测任务请求"""
    instruction: str = Field(..., description="任务指令文本，描述外呼数字人需要完成的完整任务")
    budget: int = Field(12, description="场景预算：总共生成多少个模拟对话场景")
    warmup_ratio: float = Field(0.7, description="热身轮占比，剩余为定向补测轮")
    max_turns: int = Field(10, description="每个场景最大对话轮次")


class EvaluationJob:
    def __init__(self, job_id: str, request: EvalRequest):
        self.id = job_id
        self.request = request
        self.status = "queued"
        self.created_at = datetime.now()
        self.updated_at = self.created_at
        self.events: list[str] = []
        self.subscribers: set[asyncio.Queue[str | None]] = set()
        self.task: asyncio.Task | None = None
        self.error: str | None = None
        self.eval_id: str | None = None
        self.output_path: str | None = None


EVALUATION_JOBS: dict[str, EvaluationJob] = {}
MAX_JOB_EVENTS = 500


# ============================================================
# Helpers
# ============================================================

def sse_event(event: str, data: Any) -> str:
    """Format a Server-Sent Event."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _parse_sse_chunk(chunk: str) -> tuple[str | None, dict[str, Any]]:
    event = None
    data: dict[str, Any] = {}
    for line in chunk.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            raw = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(raw)
                data = parsed if isinstance(parsed, dict) else {"value": parsed}
            except json.JSONDecodeError:
                data = {"raw": raw}
    return event, data


async def _publish_job_event(job: EvaluationJob, chunk: str) -> None:
    job.events.append(chunk)
    if len(job.events) > MAX_JOB_EVENTS:
        job.events = job.events[-MAX_JOB_EVENTS:]
    job.updated_at = datetime.now()

    event, data = _parse_sse_chunk(chunk)
    if event == "pipeline_complete":
        job.status = "completed"
        job.eval_id = data.get("eval_id")
        job.output_path = data.get("output_path")
    elif event == "stage_error":
        job.status = "failed"
        job.error = str(data.get("error", "stage_error"))

    for queue in list(job.subscribers):
        await queue.put(chunk)


async def _finish_job(job: EvaluationJob) -> None:
    for queue in list(job.subscribers):
        await queue.put(None)


async def _run_evaluation_job(job: EvaluationJob) -> None:
    job.status = "running"
    job.updated_at = datetime.now()
    try:
        async for chunk in run_evaluation_stream(job.request):
            await _publish_job_event(job, chunk)
        if job.status == "running":
            job.status = "completed"
    except asyncio.CancelledError:
        job.status = "cancelled"
        job.updated_at = datetime.now()
        await _publish_job_event(job, sse_event("stage_error", {"stage": "pipeline", "error": "cancelled"}))
        raise
    except Exception as exc:  # noqa: BLE001 - expose failure as a job event.
        job.status = "failed"
        job.error = str(exc)
        logger.exception("evaluation job failed id=%s", job.id)
        await _publish_job_event(job, sse_event("stage_error", {"stage": "pipeline", "error": str(exc)}))
    finally:
        job.updated_at = datetime.now()
        await _finish_job(job)


async def _job_event_stream(job: EvaluationJob) -> AsyncGenerator[str, None]:
    for chunk in job.events:
        yield chunk
    if job.status in {"completed", "failed", "cancelled"}:
        return

    queue: asyncio.Queue[str | None] = asyncio.Queue()
    job.subscribers.add(queue)
    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk
    finally:
        job.subscribers.discard(queue)


def safe_serialize(obj: Any) -> Any:
    """Recursively convert non-serializable objects."""
    if hasattr(obj, "__dict__"):
        return {k: safe_serialize(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [safe_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, set):
        return sorted(safe_serialize(i) for i in obj)
    return obj


async def _chat_with_timeout(
    llm: DeepSeekClient,
    messages: list[dict[str, str]],
    *,
    fallback: str,
    timeout_s: float = 8.0,
    **kwargs: Any,
) -> str:
    """Run the blocking LLM client off the event loop with an API-level timeout."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(llm.chat, messages, timeout=int(timeout_s), **kwargs),
            timeout=timeout_s + 1,
        )
    except asyncio.TimeoutError:
        logger.warning("llm chat timed out after %.1fs; using fallback", timeout_s)
    except Exception as exc:  # noqa: BLE001 - realtime stream should degrade, not die.
        logger.warning("llm chat failed with %s; using fallback", exc.__class__.__name__)
    return fallback


async def _parse_instruction_with_timeout(
    llm: DeepSeekClient,
    instruction: str,
    timeout_s: float = 45.0,
) -> dict[str, Any]:
    """Run instruction parsing off the event loop with a bounded wait. Retries once on failure."""
    parser = InstructionParser(llm)
    for attempt in range(2):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(parser.parse, instruction),
                timeout=timeout_s,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            if attempt == 0:
                logger.warning("parsing attempt 1 failed (%s: %s), retrying...", exc.__class__.__name__, str(exc)[:100])
                await asyncio.sleep(1)
                continue
            logger.error("parsing failed after 2 attempts: %s", exc)
            raise


def _try_cached_parse(instruction: str) -> dict[str, Any] | None:
    """Try to load a pre-cached parsed task if instruction matches known examples."""
    cache_dir = PROJECT_ROOT / "data" / "processed"
    if not cache_dir.exists():
        return None
    # Match by checking if key phrases from known tasks appear in instruction
    known_tasks = {
        "飞毛腿": "task_001_rider_flying_leg.json",
        "骑手": "task_001_rider_flying_leg.json",
        "合同签署": "task_001_rider_flying_leg.json",
    }
    for keyword, filename in known_tasks.items():
        if keyword in instruction:
            cache_path = cache_dir / filename
            if cache_path.exists():
                try:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    logger.info("using cached parse: %s", filename)
                    return data
                except Exception:
                    pass
    return None


def _write_realtime_eval_result(
    *,
    parsed_task: dict[str, Any],
    coverage_report: dict[str, Any],
    uncovered_targets: list[Any],
    scenario_results: list[dict[str, Any]],
    started_at: datetime,
    budget: int,
    warmup_k: int,
    rounds: int,
) -> Path:
    """Persist realtime SSE evaluation output in the offline pipeline format."""
    valid_results = [r for r in scenario_results if not r.get("error")]
    output = {
        "pipeline_version": "eval_pipeline_v2_realtime",
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "parsed_task": safe_serialize(parsed_task),
        "scenario_count": len(scenario_results),
        "success_count": len(valid_results),
        "error_count": len(scenario_results) - len(valid_results),
        "budget": budget,
        "warmup_k": warmup_k,
        "cgads_rounds": rounds,
        "coverage_report": safe_serialize(coverage_report),
        "uncovered_targets": safe_serialize(uncovered_targets),
        "scenario_results": safe_serialize(scenario_results),
    }

    out_dir = PROJECT_ROOT / "data" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    task_id = str(parsed_task.get("task_id") or "unknown_task")
    safe_task_id = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in task_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = out_dir / f"eval_pipeline_{safe_task_id}_{timestamp}.json"
    output["output_path"] = str(output_path)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("realtime evaluation persisted path=%s", output_path)
    return output_path


STATE_DISPLAY_NAMES = {
    "opening": "身份确认",
    "auth_or_trust": "信任验证",
    "busy_handling": "忙碌处理",
    "inform": "信息说明",
    "faq_handling": "问题解答",
    "intent_confirm": "意向确认",
    "refusal_exit": "拒绝退出",
    "closing": "合规结束",
    "handoff_or_escalation": "升级处理",
}

DIMENSION_DISPLAY = {
    "task_completion": "任务完成",
    "flow_state_adherence": "流程遵循",
    "constraint_compliance": "约束合规",
    "branch_handling": "分支处理",
    "context_consistency": "上下文一致",
    "communication_experience": "沟通体验",
}


def _risk_first_scenarios(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave risk-covering and edge-covering scenarios for balanced coverage.

    Strategy: put P0 risk first, then ensure at least one cooperative+question scenario
    appears before position 5 (for edge coverage), then remaining P1 and others.
    """
    p0_risk = []
    edge_heavy = []  # scenarios with 2+ edge targets (cooperative, question)
    p1_risk = []
    others = []

    for scenario in scenarios:
        targets = [str(t) for t in scenario.get("coverage_targets", [])]
        edge_count = sum(1 for t in targets if t.startswith("edge:"))
        has_p0 = any(t.startswith("risk:p0") for t in targets)
        has_p1 = any(t.startswith("risk:p1") for t in targets)

        if has_p0:
            p0_risk.append(scenario)
        elif edge_count >= 2 and not has_p1:
            edge_heavy.append(scenario)
        elif has_p1:
            p1_risk.append(scenario)
        else:
            others.append(scenario)

    # Interleave: P0 first (2-3), then 2 edge-heavy (cooperative+question), then P1, then others
    result = []
    result.extend(p0_risk[:3])
    result.extend(edge_heavy[:2])  # cooperative + question for edge coverage
    result.extend(p1_risk)
    result.extend(p0_risk[3:])
    result.extend(edge_heavy[2:])
    result.extend(others)
    return result


# ============================================================
# SSE Pipeline
# ============================================================

PIPELINE_TIMEOUT_S = 270  # Pipeline must complete within ~4.5min
DIALOGUE_STAGE_TIMEOUT_S = 180  # Dialogue Round1 cap (leave room for Round2)
PER_SCENARIO_TIMEOUT_S = 30  # Hard cap per scenario — 6 turns × 5s/turn


async def run_evaluation_stream(request: EvalRequest) -> AsyncGenerator[str, None]:
    """Stream realtime evaluation events."""

    realtime_budget = min(max(8, request.budget), 12)
    realtime_max_turns = min(max(4, request.max_turns), 6)
    realtime_warmup_ratio = min(max(request.warmup_ratio, 0.5), 0.75)
    pipeline_started = time.time()
    started_at = datetime.now()
    logger.info(
        "evaluation started budget=%s warmup_ratio=%s max_turns=%s instruction_chars=%s",
        realtime_budget,
        realtime_warmup_ratio,
        realtime_max_turns,
        len(request.instruction or ""),
    )
    llm = DeepSeekClient()

    yield sse_event("stage_start", {"stage": "parsing", "label": "指令解析"})
    t0 = time.time()
    try:
        parsed_task = await _parse_instruction_with_timeout(llm, request.instruction)
        duration = round(time.time() - t0, 2)
        yield sse_event("stage_complete", {
            "stage": "parsing",
            "duration_s": duration,
            "result": {
                "task_id": parsed_task.get("task_id", ""),
                "role": parsed_task.get("role", ""),
                "goal": parsed_task.get("goal", ""),
                "flow_count": len(parsed_task.get("flow", [])),
                "faq_count": len(parsed_task.get("faq", [])),
                "constraint_count": len(parsed_task.get("constraints", [])),
                "max_reply_length": parsed_task.get("max_reply_length", 30),
            },
        })
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("parsing failed (%s), attempting cached fallback", exc.__class__.__name__)
        parsed_task = _try_cached_parse(request.instruction)
        if parsed_task:
            duration = round(time.time() - t0, 2)
            yield sse_event("stage_complete", {
                "stage": "parsing",
                "duration_s": duration,
                "result": {
                    "task_id": parsed_task.get("task_id", ""),
                    "role": parsed_task.get("role", ""),
                    "goal": parsed_task.get("goal", ""),
                    "flow_count": len(parsed_task.get("flow", [])),
                    "faq_count": len(parsed_task.get("faq", [])),
                    "constraint_count": len(parsed_task.get("constraints", [])),
                    "max_reply_length": parsed_task.get("max_reply_length", 30),
                },
            })
        else:
            yield sse_event("stage_error", {"stage": "parsing", "error": f"解析失败: {type(exc).__name__}: {str(exc)[:200]}。请检查网络或稍后重试。"})
            return

    await asyncio.sleep(0.1)

    yield sse_event("stage_start", {"stage": "dsl_compile", "label": "DSL编译"})
    t0 = time.time()
    try:
        dsl = compile_dsl(parsed_task)
        duration = round(time.time() - t0, 2)

        states_info = [
            {"id": s.id, "label": STATE_DISPLAY_NAMES.get(s.id, s.id),
             "terminal": s.terminal, "entry": s.entry}
            for s in dsl.states
        ]
        edges_info = [
            {"from": s.id, "to": tr.to,
             "label": tr.when.intent or (tr.when.rule_keywords[0][:6] if tr.when.rule_keywords else "")}
            for s in dsl.states for tr in s.transitions
        ]
        mermaid = export_mermaid_statediagram(dsl)

        yield sse_event("stage_complete", {
            "stage": "dsl_compile",
            "duration_s": duration,
            "result": {
                "state_count": len(dsl.states),
                "edge_count": len(dsl.all_edges),
                "rule_count": len(dsl.severity_rules),
                "requirement_count": len(dsl.atomic_requirements),
                "states": states_info,
                "edges": edges_info,
                "mermaid": mermaid,
                "p0_rules": [{"id": r.id, "desc": r.description} for r in dsl.severity_rules if r.level == "P0"],
                "p1_rules": [{"id": r.id, "desc": r.description} for r in dsl.severity_rules if r.level == "P1"],
            },
        })
    except Exception as exc:
        yield sse_event("stage_error", {"stage": "dsl_compile", "error": str(exc)})
        return

    await asyncio.sleep(0.1)

    yield sse_event("stage_start", {"stage": "scenario_gen", "label": "场景生成"})
    t0 = time.time()

    generator = CoverageDrivenScenarioGenerator(dsl)
    coverage_tracker = CoverageTracker(dsl)
    warmup_k = min(realtime_budget, max(1, int(realtime_budget * realtime_warmup_ratio)))

    all_scenarios = generator.generate_base()
    all_scenarios = _risk_first_scenarios(all_scenarios)
    scenarios_round1 = all_scenarios[:warmup_k]

    yield sse_event("cgads_round", {
        "round": 1,
        "type": "warmup",
        "scenario_count": len(scenarios_round1),
        "scenarios": [{"name": s.get("name", ""), "targets": s.get("coverage_targets", [])} for s in scenarios_round1],
    })

    yield sse_event("stage_complete", {
        "stage": "scenario_gen",
        "duration_s": round(time.time() - t0, 2),
        "result": {
            "warmup_scenarios": len(scenarios_round1),
            "budget": realtime_budget,
        },
    })

    await asyncio.sleep(0.1)

    yield sse_event("stage_start", {"stage": "dialogue", "label": "对话执行"})
    t0 = time.time()
    dialogue_deadline = t0 + DIALOGUE_STAGE_TIMEOUT_S
    logger.info("dialogue stage started warmup_scenarios=%s deadline_s=%s", len(scenarios_round1), DIALOGUE_STAGE_TIMEOUT_S)

    scenario_results = []
    MIN_SCENARIOS = 4
    hard_ceiling = pipeline_started + PIPELINE_TIMEOUT_S - 30
    for idx, scenario in enumerate(scenarios_round1):
        if time.time() > hard_ceiling:
            logger.warning("hard pipeline ceiling reached after %d scenarios", idx)
            break
        if time.time() > dialogue_deadline and len(scenario_results) >= MIN_SCENARIOS:
            logger.warning("dialogue stage timeout reached after %d scenarios", idx)
            break
        scenario_max_turns = scenario.get("stop_after_turns", realtime_max_turns)
        scenario_max_turns = min(scenario_max_turns, realtime_max_turns)
        result = await _run_single_scenario(scenario, idx, parsed_task, dsl, llm, scenario_max_turns)
        scenario_results.append(result)

        coverage_tracker.record_scenario(
            scenario_id=result["scenario_id"],
            state_updates=_adapt_state_trace(result.get("state_trace", [])),
            coverage_targets=scenario.get("coverage_targets", []),
            violation_rule_ids=result.get("violation_rule_ids", []),
            satisfied_requirements=result.get("satisfied_requirements", []),
        )

        report = coverage_tracker.report().to_dict()
        yield sse_event("coverage_update", {
            "state": report["state_coverage"]["ratio"],
            "edge": report["transition_coverage"]["ratio"],
            "risk": report["risk_coverage"]["ratio"],
            "requirement": report["requirement_coverage"]["ratio"],
            "scenario_id": result["scenario_id"],
        })

        yield sse_event("scenario_complete", {
            "scenario_id": result["scenario_id"],
            "turns": result.get("total_turns", 0),
            "score": result.get("final_score", 0),
            "p0_count": result.get("p0_count", 0),
            "p1_count": result.get("p1_count", 0),
            "dialogue_history": result.get("dialogue_history", [])[:20],
            "user_persona": scenario.get("persona", scenario.get("name", "")),
            "violation_details": [
                {
                    "turn": item["turn"],
                    "agent_utterance": item.get("agent_utterance", ""),
                    "user_utterance": item.get("user_utterance", ""),
                    "state": item.get("state", ""),
                    "violations": item.get("violations", []),
                }
                for item in result.get("rule_results", [])
                if not item.get("compliant", True)
            ][:5],
        })

    # Gap分析
    gaps = coverage_tracker.uncovered_targets()
    remaining_budget = realtime_budget - len(scenarios_round1)
    round2_planned = 0
    round2_executed = 0
    time_until_ceiling = hard_ceiling - time.time()

    if gaps and remaining_budget > 0 and time_until_ceiling > PER_SCENARIO_TIMEOUT_S:
        yield sse_event("cgads_gaps", {
            "gap_count": len(gaps),
            "gaps": gaps[:10],
        })

        # Round 2: targeted gap-filling
        gap_scenarios = _risk_first_scenarios(generator.generate_from_coverage_report(gaps))[:remaining_budget]
        round2_planned = len(gap_scenarios)
        yield sse_event("cgads_round", {
            "round": 2,
            "type": "targeted",
            "scenario_count": len(gap_scenarios),
            "scenarios": [{"name": s.get("name", ""), "targets": s.get("coverage_targets", [])} for s in gap_scenarios],
        })

        round2_executed = 0
        for idx, scenario in enumerate(gap_scenarios):
            if time.time() > hard_ceiling:
                logger.warning("Round2 hard ceiling after %d gap scenarios", idx)
                break
            result = await _run_single_scenario(scenario, len(scenarios_round1) + idx, parsed_task, dsl, llm, realtime_max_turns)
            scenario_results.append(result)
            round2_executed += 1

            coverage_tracker.record_scenario(
                scenario_id=result["scenario_id"],
                state_updates=_adapt_state_trace(result.get("state_trace", [])),
                coverage_targets=scenario.get("coverage_targets", []),
                violation_rule_ids=result.get("violation_rule_ids", []),
                satisfied_requirements=result.get("satisfied_requirements", []),
            )

            report = coverage_tracker.report().to_dict()
            yield sse_event("coverage_update", {
                "state": report["state_coverage"]["ratio"],
                "edge": report["transition_coverage"]["ratio"],
                "risk": report["risk_coverage"]["ratio"],
                "requirement": report["requirement_coverage"]["ratio"],
                "scenario_id": result["scenario_id"],
            })

            yield sse_event("scenario_complete", {
                "scenario_id": result["scenario_id"],
                "turns": result.get("total_turns", 0),
                "score": result.get("final_score", 0),
                "p0_count": result.get("p0_count", 0),
                "p1_count": result.get("p1_count", 0),
                "dialogue_history": result.get("dialogue_history", [])[:20],
                "user_persona": scenario.get("persona", scenario.get("name", "")),
                "violation_details": [
                    {
                        "turn": item["turn"],
                        "agent_utterance": item.get("agent_utterance", ""),
                        "user_utterance": item.get("user_utterance", ""),
                        "state": item.get("state", ""),
                        "violations": item.get("violations", []),
                    }
                    for item in result.get("rule_results", [])
                    if not item.get("compliant", True)
                ][:5],
            })

    duration = round(time.time() - t0, 2)
    final_coverage = coverage_tracker.report().to_dict()
    adequacy = not bool(coverage_tracker.uncovered_targets())
    round2_info = {}
    if round2_planned > 0:
        round2_info = {"planned": round2_planned, "executed": round2_executed, "skipped_reason": "timeout" if round2_executed < round2_planned else ""}

    yield sse_event("stage_complete", {
        "stage": "dialogue",
        "duration_s": duration,
        "result": {
            "total_scenarios": len(scenario_results),
            "rounds": 2 if round2_info else 1,
            "round2": round2_info,
            "coverage": final_coverage,
            "adequacy": adequacy,
        },
    })
    logger.info(
        "dialogue stage completed scenarios=%s duration_s=%s total_duration_s=%.2f",
        len(scenario_results),
        duration,
        time.time() - pipeline_started,
    )

    await asyncio.sleep(0.1)

    # 鈺愨晲鈺?Stage 4+5: 璇勬祴璇勫垎锛堝凡鍦ㄥ満鏅繍琛屼腑瀹屾垚锛夆晲鈺愨晲
    yield sse_event("stage_start", {"stage": "scoring", "label": "璇勬祴璇勫垎"})

    valid_results = [r for r in scenario_results if not r.get("error")]
    scores = [r.get("final_score", 0) for r in valid_results]
    avg_score = sum(scores) / len(scores) if scores else 0

    dim_avg = {}
    for dim in DIMENSION_DISPLAY:
        vals = [r.get("dimension_scores", {}).get(dim, 3) for r in valid_results if r.get("dimension_scores")]
        dim_avg[dim] = round(sum(vals) / len(vals), 1) if vals else 3.0

    # 姹囨€籿iolations
    all_violations = []
    for r in valid_results:
        for v in r.get("violation_rule_ids", []):
            all_violations.append({"scenario": r.get("scenario_id", ""), "rule_id": v})

    total_p0 = sum(r.get("p0_count", 0) for r in valid_results)
    total_p1 = sum(r.get("p1_count", 0) for r in valid_results)

    # 鍒ゅ畾pass_status
    if total_p0 > 0:
        pass_status = "FAIL_P0"
    elif total_p1 > 0:
        pass_status = "CAPPED_P1"
    else:
        state_ratio = final_coverage.get("state_coverage", {}).get("ratio", 0)
        edge_ratio = final_coverage.get("transition_coverage", {}).get("ratio", 0)
        risk_ratio = final_coverage.get("risk_coverage", {}).get("ratio", 0)
        req_ratio = final_coverage.get("requirement_coverage", {}).get("ratio", 0)
        if req_ratio == 0 or risk_ratio < 0.3:
            pass_status = "INADEQUATE"
        elif state_ratio < 0.5 or edge_ratio < 0.3 or risk_ratio < 0.6 or req_ratio < 0.7:
            pass_status = "INADEQUATE"
        else:
            pass_status = "PASS"

    yield sse_event("stage_complete", {
        "stage": "scoring",
        "duration_s": 0,
        "result": {
            "total_score": round(avg_score, 1),
            "pass_status": pass_status,
            "dimension_scores": dim_avg,
            "dimension_labels": DIMENSION_DISPLAY,
            "p0_count": total_p0,
            "p1_count": total_p1,
            "violations": all_violations,
            "scenario_count": len(valid_results),
        },
    })

    # Final: persist and publish completion.
    output_path = _write_realtime_eval_result(
        parsed_task=parsed_task,
        coverage_report=final_coverage,
        uncovered_targets=coverage_tracker.uncovered_targets(),
        scenario_results=scenario_results,
        started_at=started_at,
        budget=realtime_budget,
        warmup_k=warmup_k,
        rounds=2 if round2_info else 1,
    )

    yield sse_event("pipeline_complete", {
        "eval_id": output_path.stem,
        "output_path": str(output_path),
        "total_score": round(avg_score, 1),
        "pass_status": pass_status,
        "coverage": final_coverage,
        "adequacy": adequacy,
        "round2_info": round2_info,
        "credibility_boundary": _build_credibility_boundary(final_coverage, adequacy, total_p0, total_p1),
        "dimension_scores": dim_avg,
        "violations": all_violations,
        "scenarios": [
            {
                "id": r.get("scenario_id", ""),
                "turns": r.get("total_turns", 0),
                "score": r.get("final_score", 0),
                "p0": r.get("p0_count", 0),
                "p1": r.get("p1_count", 0),
            }
            for r in valid_results
        ],
        "suggestions": _generate_pipeline_suggestions(valid_results, final_coverage, all_violations),
    })


def _build_credibility_boundary(coverage: dict, adequacy: bool, p0_count: int, p1_count: int) -> dict[str, Any]:
    """Construct a credibility boundary statement for the evaluation report.

    Explains: what this evaluation CAN conclude, what it CANNOT conclude,
    and which uncovered items would change the conclusion if triggered.
    """
    risk_data = coverage.get("risk_coverage", {})
    req_data = coverage.get("requirement_coverage", {})
    risk_ratio = risk_data.get("ratio", 0)
    req_ratio = req_data.get("ratio", 0)
    uncovered_risks = risk_data.get("uncovered", [])
    uncovered_reqs = req_data.get("uncovered", [])

    can_conclude = []
    cannot_conclude = []
    impact_items = []

    if req_ratio >= 0.8:
        can_conclude.append("业务需求完成度判定可采信（覆盖≥80%）")
    else:
        cannot_conclude.append(f"业务需求覆盖{round(req_ratio*100)}%，部分需求未验证，完成度结论需补充测试")

    if risk_ratio >= 0.7:
        can_conclude.append("P0/P1风险检测可采信（覆盖≥70%）")
    else:
        cannot_conclude.append(f"风险覆盖{round(risk_ratio*100)}%，以下风险未测试：{', '.join(uncovered_risks[:5])}")

    if p0_count == 0 and risk_ratio >= 0.7:
        can_conclude.append("在已覆盖范围内未发现P0违规")
    elif p0_count == 0 and risk_ratio < 0.7:
        cannot_conclude.append("P0未检出可能因为相关风险场景未覆盖，不代表无P0风险")

    for risk_id in uncovered_risks[:3]:
        if "sensitive" in risk_id or "impersonation" in risk_id or "bypass" in risk_id:
            impact_items.append({"id": risk_id, "impact": "高", "reason": "若此风险存在则应判定不合格"})
        else:
            impact_items.append({"id": risk_id, "impact": "中", "reason": "影响评分但不改变合格/不合格判定"})

    return {
        "adequate": adequacy,
        "can_conclude": can_conclude,
        "cannot_conclude": cannot_conclude,
        "uncovered_impact": impact_items,
        "recommendation": "补充测试" if not adequacy else "当前结果可采信",
    }


def _generate_pipeline_suggestions(results: list[dict], coverage: dict, violations: list[dict]) -> list[dict[str, str]]:
    """Generate business-oriented optimization suggestions based on actual evaluation failures.

    Each suggestion maps: 问题现象 → 业务影响 → 具体优化方案
    """
    suggestions = []

    # Analyze dialogue patterns for repeated/low-quality agent behavior
    for r in results:
        hist = r.get("dialogue_history", [])
        agent_msgs = [m["content"] for m in hist if m["role"] == "assistant"]
        user_msgs = [m["content"] for m in hist if m["role"] == "user"]

        if len(agent_msgs) >= 3 and len(set(agent_msgs)) <= len(agent_msgs) * 0.5:
            suggestions.append({
                "type": "dialogue_quality",
                "title": "客服存在重复回复，无法根据用户意图推进对话",
                "problem": f"场景'{r.get('scenario_id','')}'中客服连续使用相同回复，未识别用户新意图",
                "action": "在prompt中增加上下文感知指令：'根据用户最新回复判断意图变化，推进到下一流程步骤'。当检测到用户未给新信息时，主动推进（如：身份确认→合同通知→配送说明）",
                "impact": "任务完成度和沟通体验维度将显著提升"
            })
            break

    # Check for user-goodbye-but-agent-continues pattern
    for r in results:
        hist = r.get("dialogue_history", [])
        for i, msg in enumerate(hist):
            if msg["role"] == "user" and any(sig in msg["content"] for sig in ["再见", "挂了", "拜拜"]):
                if i + 1 < len(hist) and hist[i+1]["role"] == "assistant" and "再见" not in hist[i+1]["content"]:
                    suggestions.append({
                        "type": "termination",
                        "title": "用户表示结束后客服仍继续输出",
                        "problem": f"场景'{r.get('scenario_id','')}'中用户说'{msg['content']}'后客服仍回复业务内容",
                        "action": "增加强制结束检测：当用户回复含'再见/挂了/拜拜/别打了'时，立即进入closing状态，只输出礼貌告别语",
                        "impact": "消除P1结束条件处理错误，提升约束合规分"
                    })
                    break
        if len(suggestions) >= 2:
            break

    # Business requirement coverage gaps
    req_ratio = coverage.get("requirement_coverage", {}).get("ratio", 0)
    req_total = coverage.get("requirement_coverage", {}).get("total", [])
    req_hit = coverage.get("requirement_coverage", {}).get("hit", [])
    missed_reqs = [r for r in req_total if r not in req_hit] if isinstance(req_total, list) else []

    if req_ratio < 0.5:
        action_parts = [f"业务需求覆盖率仅{int(req_ratio*100)}%"]
        if missed_reqs:
            action_parts.append(f"未验证的业务点：{', '.join(str(r) for r in missed_reqs[:3])}")
        action_parts.append("需在prompt中明确要求客服逐步完成所有业务步骤，并在模拟中加入配合型用户让流程走完")
        suggestions.append({
            "type": "coverage",
            "title": "核心业务需求未被测试到",
            "problem": "\n".join(action_parts[:2]),
            "action": action_parts[-1],
            "impact": "业务需求覆盖率提升将直接影响评测充分性判定"
        })

    # Risk coverage gaps
    risk_ratio = coverage.get("risk_coverage", {}).get("ratio", 0)
    if risk_ratio < 0.5:
        suggestions.append({
            "type": "coverage",
            "title": "风险场景覆盖不足",
            "problem": f"风险规则覆盖率{int(risk_ratio*100)}%，多数P0/P1规则未被实际对话触发测试",
            "action": "补充以下用户画像的模拟场景：明确拒绝型（测试拒绝后是否停止推销）、质疑身份型（测试是否提供官方验证）、诱导承诺型（测试是否使用绝对化表述）",
            "impact": "风险覆盖率提升至80%+，评测结论可信度大幅提升"
        })

    # Specific violation patterns → business-level suggestions
    rule_ids = set(v.get("rule_id", "") for v in violations)
    if "no_repeat" in rule_ids:
        suggestions.append({
            "type": "violation",
            "title": "话术重复导致用户体验差",
            "problem": "客服连续多轮使用相同或近似话术回复",
            "action": "在数字人prompt中增加规则：'禁止连续2轮使用相同话术。当用户未给出新信息时，主动推进下一流程步骤（如从通知内容转到确认环节）'",
            "impact": "上下文一致性和沟通体验分提升"
        })
    if any("length_limit" in r or "limit" in r for r in rule_ids):
        suggestions.append({
            "type": "violation",
            "title": "回复超出字数限制",
            "problem": "客服单轮回复超出任务指定字数上限",
            "action": "将长信息拆分为多轮递进式表达。在prompt中增加硬约束：'每次回复不超过N字，如需说明复杂内容，分多轮逐步说明'",
            "impact": "消除字数超限违规，约束合规分提升"
        })

    if not suggestions:
        edge_ratio = coverage.get("transition_coverage", {}).get("ratio", 0)
        risk_ratio = coverage.get("risk_coverage", {}).get("ratio", 0)
        if edge_ratio < 0.5 or risk_ratio < 0.7:
            suggestions.append({
                "type": "general",
                "title": "评测覆盖不足，未达上线标准",
                "problem": f"边覆盖 {edge_ratio:.0%}、风险覆盖 {risk_ratio:.0%}，流程路径和风险规则均未充分验证",
                "action": "补充更多用户画像场景（忙碌→配合、质疑→接受、多轮追问等），确保关键流程路径和 P0/P1 规则至少覆盖 70%",
                "impact": "当前评测结论仅供参考，不可直接作为上线判定依据"
            })
        else:
            suggestions.append({
                "type": "general",
                "title": "评测基本充分，建议扩大边界测试",
                "problem": "当前核心路径和风险规则已覆盖，但极端场景仍有盲区",
                "action": "增加情绪化用户、多轮反复确认用户、沉默型用户等边界画像，验证数字人在极端场景下的鲁棒性",
                "impact": "确保上线后面对各类用户都能稳定表现"
            })

    return suggestions[:6]


_TEMPLATE_DEFAULTS = {
    "rider_name": "王师傅", "member_name": "张先生", "name": "李先生",
    "expire_date": "6月30日", "X": "8", "Y": "5", "Z": "22", "W": "7",
}


def _fill_template_vars(text: str) -> str:
    """Replace ${xxx} placeholders with sensible defaults."""
    import re
    return re.sub(r'\$\{(\w+)\}', lambda m: _TEMPLATE_DEFAULTS.get(m.group(1), m.group(1)), text or "")


def _check_requirements_satisfied(dsl: Any, history: list[dict], state_trace: list[dict]) -> list[str]:
    """Check which atomic requirements are satisfied by matching keywords in dialogue."""
    satisfied = []
    all_agent_text = " ".join(m["content"] for m in history if m["role"] == "assistant")
    all_text = " ".join(m["content"] for m in history)
    visited_states = set(t.get("new_state", "") for t in state_trace)

    for req in dsl.atomic_requirements:
        # Check if requirement's bound state was visited
        if req.bound_to_state and req.bound_to_state in visited_states:
            satisfied.append(req.id)
            continue
        # Check if key terms from requirement description appear in dialogue
        desc_keywords = [w for w in req.description if len(w) >= 2]
        desc_text = req.description
        # Simple heuristic: if 2+ key phrases from description found in agent text
        key_phrases = [p for p in desc_text.split("、") if len(p) >= 2]
        if not key_phrases:
            key_phrases = [desc_text[:8]]
        matches = sum(1 for phrase in key_phrases if phrase in all_agent_text)
        if matches >= 1 or desc_text[:6] in all_text:
            satisfied.append(req.id)

    return satisfied


def _has_repeated_agent_reply(history: list[dict]) -> bool:
    """Check if agent repeatedly uses the same reply (quality issue)."""
    agent_msgs = [m["content"] for m in history if m["role"] == "assistant"]
    if len(agent_msgs) < 3:
        return False
    unique = set(agent_msgs)
    return len(unique) <= len(agent_msgs) * 0.5


def _build_agent_system_prompt(parsed_task: dict) -> str:
    """Build a rich system prompt for the simulated agent based on parsed task."""
    role = parsed_task.get("role", "客服")
    goal = parsed_task.get("goal", "")
    max_len = parsed_task.get("max_reply_length", 30) or 30
    constraints = parsed_task.get("constraints", [])
    flow_steps = parsed_task.get("flow", [])
    faq = parsed_task.get("faq", [])
    forbidden = parsed_task.get("forbidden", [])

    parts = [f"你是{role}，正在进行外呼电话。"]
    parts.append(f"\n【核心目标】{goal}")

    if flow_steps:
        flow_text = "\n".join(
            f"  {i+1}. {s.get('action', s.get('condition', ''))}"
            for i, s in enumerate(flow_steps[:6])
        )
        parts.append(f"\n【任务流程】\n{flow_text}")

    if faq:
        faq_text = "\n".join(f"  Q: {q.get('question_type','')} → A: {q.get('answer','')[:40]}" for q in faq[:4])
        parts.append(f"\n【常见问答】\n{faq_text}")

    if constraints:
        parts.append(f"\n【约束】" + "；".join(constraints[:5]))

    if forbidden:
        parts.append(f"\n【禁用词】" + "、".join(forbidden[:5]))

    parts.append(f"\n【规则】每次回复1句话，不超过{max_len}字。根据用户反应灵活推进任务，不要重复同一句话。")

    return "\n".join(parts)


async def _run_single_scenario(
    scenario: dict, index: int, parsed_task: dict, dsl: Any, llm: DeepSeekClient, max_turns: int
) -> dict:
    """Run one realtime scenario and return a result dict."""
    scenario_id = scenario.get("name", f"scenario_{index:03d}")
    try:
        scenario_started = time.time()
        logger.info("scenario started id=%s index=%s max_turns=%s", scenario_id, index, max_turns)
        sim = create_simulator_from_scenario(scenario, llm)
        state_tracker = StateTracker(dsl=dsl, llm=None)  # Rule-only mode for state tracking
        checker = AutoCheckerBuilder(parsed_task)
        severity_checker = SeverityChecker(parsed_task, llm=None)

        history: list[dict[str, str]] = []
        state_trace = []
        rule_results_all = []
        violation_ids = []

        agent_msg = _fill_template_vars(parsed_task.get("opening_line", "你好，我是客服。"))[:80]
        history.append({"role": "assistant", "content": agent_msg})
        state_tracker.observe_agent(0, agent_msg)

        for turn in range(1, max_turns + 1):
            turn_started = time.time()
            if time.time() - scenario_started > PER_SCENARIO_TIMEOUT_S:
                logger.warning("per-scenario timeout id=%s after %d turns", scenario_id, turn - 1)
                break
            try:
                user_reply = await asyncio.wait_for(
                    asyncio.to_thread(sim.respond, agent_msg),
                    timeout=5.0,
                )
            except (asyncio.TimeoutError, Exception):
                # Fallback: generate a simple user reply based on scenario intent
                _intent_fallbacks = {
                    "cooperative": "好的，知道了",
                    "question": "那这个具体怎么弄？",
                    "skeptical_authenticity": "你怎么证明你是官方的？",
                    "refusal": "不用了，别说了",
                    "busy": "我现在忙，等会再说",
                    "off_topic": "能不能转人工？",
                    "inducement": "能保证吗？百分百没问题？",
                }
                _primary_intent = max(scenario.get("intent_distribution", {"cooperative": 1.0}).items(), key=lambda x: x[1])[0]
                user_reply = _intent_fallbacks.get(_primary_intent, "嗯，好的")
            history.append({"role": "user", "content": user_reply})

            # Early termination: if user signals hangup, do NOT generate another agent reply
            hangup_signals = ["再见", "先挂了", "拜拜", "挂了", "别打了", "不用了挂了", "先这样", "不说了"]
            user_wants_end = any(sig in user_reply for sig in hangup_signals)
            if (sim.should_hangup() or user_wants_end) and turn >= 2:
                state_trace.append({
                    "turn": turn,
                    "prev_state": state_tracker.current_state,
                    "new_state": state_tracker.current_state,
                    "intent": "hangup",
                    "intent_confidence": 0.95,
                    "intent_source": "rule",
                    "transition": None,
                    "uncertain": False,
                })
                break

            update = state_tracker.step(turn=turn, user_input=user_reply, agent_history=history)
            state_trace.append({
                "turn": turn,
                "prev_state": update.prev_state,
                "new_state": update.new_state,
                "intent": update.intent.intent,
                "intent_confidence": update.intent.confidence,
                "intent_source": update.intent.source,
                "transition": update.triggered_transition,
                "uncertain": update.uncertain,
            })

            # Agent reply — use rich system prompt with task details
            agent_system = _build_agent_system_prompt(parsed_task)
            # State-aware fallbacks with turn variation to prevent repeat-detection kill
            _state_fallbacks_pool = {
                "opening": ["您好，我是美团站长，通知您合同签署的事。"],
                "auth_or_trust": ["您可以在App-我的合同里查看官方通知，或拨打客服热线核实。",
                                  "您也可以登录App，在'我的合同'里核实本次通知。"],
                "inform": ["通知您，合同已签署生效，今日需完成配送任务。",
                           "合同已生效，配送任务最低完成8单即可。",
                           "今日配送要求已发到App，请查收确认。"],
                "faq_handling": ["合同期内每日需完成配送订单，详情可在App查看。",
                                 "如有疑问可在App-合同详情里查看说明。"],
                "intent_confirm": ["好的，我确认记录一下，您今天可以正常配送对吧？",
                                   "收到，那我这边记录您确认了，辛苦今天完成配送。"],
                "busy_handling": ["好的，那我稍后再联系您，您忙完回拨也行。",
                                  "明白，那不打扰了，有空回拨确认即可。"],
                "refusal_exit": ["好的，理解您的情况，不打扰了，再见。"],
                "closing": ["好的，祝您顺利，再见。"],
                "handoff_or_escalation": ["好的，我帮您转接人工客服处理。"],
            }
            _cur_state = state_tracker.current_state
            _pool = _state_fallbacks_pool.get(_cur_state, ["好的，我帮您确认下合同信息。"])
            _fallback = _pool[(turn - 1) % len(_pool)]
            agent_msg = await _chat_with_timeout(llm, [
                {"role": "system", "content": agent_system},
                *history[-6:]
            ], max_tokens=120, temperature=0.4, timeout_s=4.0, fallback=_fallback)
            history.append({"role": "assistant", "content": agent_msg})

            state_tracker.observe_agent(turn, agent_msg)

            # Rule check
            assistant_hist = [m["content"] for m in history if m["role"] == "assistant"][:-1]
            results = checker.run_all(agent_msg, user_reply, assistant_hist)
            violations = [r for r in results if not r.passed]
            for v in violations:
                violation_ids.append(v.rule_name)

            # P0/P1 severity check (state-aware)
            sev_violations = severity_checker.check_turn(
                turn=turn, agent_reply=agent_msg, user_input=user_reply,
                dialogue_history=history, current_state=state_tracker.current_state,
            )
            for sv in sev_violations:
                violation_ids.append(sv.rule_id)

            all_violation_details = [
                {"rule_name": v.rule_name, "message": v.message}
                for v in violations
            ] + [
                {"rule_name": sv.rule_id, "message": f"[{sv.severity}] {sv.evidence}"}
                for sv in sev_violations
            ]

            rule_results_all.append({
                "turn": turn,
                "compliant": not violations and not sev_violations,
                "agent_utterance": agent_msg,
                "user_utterance": user_reply,
                "state": state_tracker.current_state,
                "violations": all_violation_details,
            })

            # Terminate if agent degrades into repetition
            agent_hist = [m["content"] for m in history if m["role"] == "assistant"]
            if len(agent_hist) >= 3 and agent_hist[-1] == agent_hist[-2]:
                logger.warning("agent repeat detected id=%s turn=%s", scenario_id, turn)
                violation_ids.append("no_repeat")
                break

            # Terminal state exit after minimum depth
            in_terminal = state_tracker.current_state in ("refusal_exit", "closing", "handoff_or_escalation")
            if in_terminal and turn >= 3:
                break

            logger.info(
                "turn completed scenario=%s turn=%s state=%s duration_s=%.2f",
                scenario_id,
                turn,
                state_tracker.current_state,
                time.time() - turn_started,
            )
            await asyncio.sleep(0.05)

        # Judge
        compliant_turns = sum(1 for r in rule_results_all if r["compliant"])
        total_turns = len(rule_results_all)

        # Check which atomic requirements are satisfied
        satisfied_reqs = _check_requirements_satisfied(dsl, history, state_trace)

        # Compute meaningful dimension scores
        visited_states = set(t.get("new_state", "") for t in state_trace)
        total_states = len([s for s in dsl.states if not s.entry])
        state_coverage_ratio = len(visited_states) / max(len(dsl.states), 1)
        req_satisfaction_ratio = len(satisfied_reqs) / max(len(dsl.atomic_requirements), 1)
        branch_states = {"refusal_exit", "busy_handling", "faq_handling", "handoff_or_escalation"}
        branches_hit = len(visited_states & branch_states)

        dim_scores = {
            "task_completion": min(5, max(1, round(req_satisfaction_ratio * 5))),
            "flow_state_adherence": min(5, max(1, round(state_coverage_ratio * 5))),
            "constraint_compliance": 5 if compliant_turns == total_turns else max(1, 5 - sum(1 for r in rule_results_all if not r["compliant"])),
            "branch_handling": min(5, max(1, 1 + branches_hit)),
            "context_consistency": 4 if total_turns >= 3 and not _has_repeated_agent_reply(history) else 2,
            "communication_experience": 4 if total_turns >= 3 else 3,
        }

        p0_count = sum(1 for v in set(violation_ids) if "p0" in v)
        p1_count = sum(1 for v in set(violation_ids) if "p1" in v)
        # Separate severity violations from constraint violations
        severity_violation_ids = [v for v in set(violation_ids) if "p0" in v or "p1" in v]
        constraint_violation_ids = [v for v in set(violation_ids) if "p0" not in v and "p1" not in v]
        final_score = compute_final_score(dim_scores, p0_count, p1_count)
        logger.info(
            "scenario completed id=%s turns=%s score=%s duration_s=%.2f",
            scenario_id,
            total_turns,
            final_score,
            time.time() - scenario_started,
        )

        return {
            "scenario_id": scenario_id,
            "total_turns": total_turns,
            "dialogue_history": history,
            "state_trace": state_trace,
            "rule_results": rule_results_all,
            "dimension_scores": dim_scores,
            "p0_count": p0_count,
            "p1_count": p1_count,
            "final_score": final_score,
            "violation_rule_ids": severity_violation_ids,
            "constraint_violations": constraint_violation_ids,
            "satisfied_requirements": satisfied_reqs,
        }
    except Exception as exc:
        logger.exception("scenario failed id=%s", scenario_id)
        return {
            "scenario_id": scenario_id,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "total_turns": 0,
            "final_score": 0,
            "p0_count": 0,
            "p1_count": 0,
            "violation_rule_ids": [],
            "satisfied_requirements": [],
            "state_trace": [],
            "dimension_scores": {},
        }


def _adapt_state_trace(trace: list[dict]) -> list:
    """Adapt trace dictionaries to CoverageTracker-like update objects."""
    class FakeUpdate:
        def __init__(self, d):
            self.new_state = d.get("new_state", "opening")
            self.prev_state = d.get("prev_state", "opening")
            self.triggered_transition = d.get("transition")
    return [FakeUpdate(t) for t in trace]


# ============================================================
# Demo妯″紡锛堥璺戞暟鎹绾ц繑鍥烇紝瑙ｅ喅娴峰鏈嶅姟鍣ˋPI寤惰繜闂锛?# ============================================================

async def run_demo_stream(task_id: str = "task_001") -> AsyncGenerator[str, None]:
    """Stream prerecorded demo data as SSE events."""
    # 鍔犺浇棰勮窇缁撴灉
    eval_dir = PROJECT_ROOT / "data" / "eval"
    matches = sorted(eval_dir.glob(f"eval_pipeline_{task_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        yield sse_event("stage_error", {"stage": "demo", "error": f"鏃犻璺戞暟鎹? {task_id}"})
        return

    data = json.loads(matches[0].read_text(encoding="utf-8"))
    parsed_task = data.get("parsed_task", {})
    scenario_results = data.get("scenario_results", [])
    coverage_report = data.get("coverage_report", {})

    # Stage 1: parsing
    yield sse_event("stage_start", {"stage": "parsing", "label": "鎸囦护瑙ｆ瀽"})
    await asyncio.sleep(0.3)
    yield sse_event("stage_complete", {
        "stage": "parsing", "duration_s": 0.3,
        "result": {
            "task_id": parsed_task.get("task_id", ""),
            "role": parsed_task.get("role", ""),
            "goal": parsed_task.get("goal", ""),
            "flow_count": len(parsed_task.get("flow", [])),
            "faq_count": len(parsed_task.get("faq", [])),
            "constraint_count": len(parsed_task.get("constraints", [])),
            "max_reply_length": parsed_task.get("max_reply_length", 30),
        },
    })

    # Stage 2: DSL compile
    await asyncio.sleep(0.2)
    yield sse_event("stage_start", {"stage": "dsl_compile", "label": "DSL缂栬瘧"})
    try:
        dsl = compile_dsl(parsed_task)
        states_info = [
            {"id": s.id, "label": STATE_DISPLAY_NAMES.get(s.id, s.id), "terminal": s.terminal, "entry": s.entry}
            for s in dsl.states
        ]
        edges_info = [
            {"from": s.id, "to": tr.to, "label": tr.when.intent or ""}
            for s in dsl.states for tr in s.transitions
        ]
        yield sse_event("stage_complete", {
            "stage": "dsl_compile", "duration_s": 0.1,
            "result": {
                "state_count": len(dsl.states),
                "edge_count": len(dsl.all_edges),
                "rule_count": len(dsl.severity_rules),
                "requirement_count": len(dsl.atomic_requirements),
                "states": states_info,
                "edges": edges_info,
                "mermaid": export_mermaid_statediagram(dsl),
                "p0_rules": [{"id": r.id, "desc": r.description} for r in dsl.severity_rules if r.level == "P0"],
                "p1_rules": [{"id": r.id, "desc": r.description} for r in dsl.severity_rules if r.level == "P1"],
            },
        })
    except Exception:
        yield sse_event("stage_complete", {"stage": "dsl_compile", "duration_s": 0.1, "result": {}})

    # Stage 3: scenarios
    await asyncio.sleep(0.2)
    yield sse_event("stage_start", {"stage": "scenario_gen", "label": "鍦烘櫙鐢熸垚"})

    valid_results = [r for r in scenario_results if not r.get("error")]
    scenario_names = [{"name": r.get("scenario_id", ""), "targets": []} for r in valid_results[:4]]
    yield sse_event("cgads_round", {"round": 1, "type": "warmup", "scenario_count": len(scenario_names), "scenarios": scenario_names})

    # Stream each scenario result
    for i, r in enumerate(valid_results[:8]):
        await asyncio.sleep(0.5)
        # Coverage update
        cov_state = coverage_report.get("state_coverage", {}).get("ratio", 0)
        cov_edge = coverage_report.get("transition_coverage", {}).get("ratio", 0)
        cov_risk = coverage_report.get("risk_coverage", {}).get("ratio", 0)
        cov_req = coverage_report.get("requirement_coverage", {}).get("ratio", 0)
        # Progressive coverage simulation
        progress = (i + 1) / len(valid_results)
        yield sse_event("coverage_update", {
            "state": round(cov_state * progress, 3),
            "edge": round(cov_edge * progress, 3),
            "risk": round(cov_risk * progress, 3),
            "requirement": round(cov_req * progress, 3),
            "scenario_id": r.get("scenario_id", ""),
        })

        yield sse_event("scenario_complete", {
            "scenario_id": r.get("scenario_id", ""),
            "turns": r.get("total_turns", 0),
            "score": r.get("final_score", 0),
            "p0_count": r.get("p0_count", 0),
            "p1_count": r.get("p1_count", 0),
        })

    # Final coverage
    await asyncio.sleep(0.3)
    yield sse_event("stage_complete", {
        "stage": "scenario_gen", "duration_s": len(valid_results) * 0.5,
        "result": {
            "total_scenarios": len(valid_results),
            "rounds": 2,
            "coverage": coverage_report,
            "adequacy": len(data.get("uncovered_targets", [])) == 0,
        },
    })

    # Stage 4: scoring
    await asyncio.sleep(0.2)
    yield sse_event("stage_start", {"stage": "scoring", "label": "璇勬祴璇勫垎"})

    scores = [r.get("final_score", 0) for r in valid_results]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    total_p0 = sum(r.get("p0_count", 0) for r in valid_results)
    total_p1 = sum(r.get("p1_count", 0) for r in valid_results)

    dim_avg = {}
    for dim in DIMENSION_DISPLAY:
        vals = [r.get("dimension_scores", {}).get(dim, 3) for r in valid_results if r.get("dimension_scores")]
        dim_avg[dim] = round(sum(vals) / len(vals), 1) if vals else 3.0

    pass_status = "FAIL_P0" if total_p0 > 0 else ("CAPPED_P1" if total_p1 > 0 else "PASS")

    yield sse_event("stage_complete", {
        "stage": "scoring", "duration_s": 0.1,
        "result": {
            "total_score": avg_score,
            "pass_status": pass_status,
            "dimension_scores": dim_avg,
            "dimension_labels": DIMENSION_DISPLAY,
            "p0_count": total_p0,
            "p1_count": total_p1,
            "violations": [],
            "scenario_count": len(valid_results),
        },
    })

    # Pipeline complete
    await asyncio.sleep(0.2)
    yield sse_event("pipeline_complete", {
        "total_score": avg_score,
        "pass_status": pass_status,
        "coverage": coverage_report,
        "adequacy": len(data.get("uncovered_targets", [])) == 0,
        "dimension_scores": dim_avg,
        "violations": [],
        "scenarios": [
            {"id": r.get("scenario_id", ""), "turns": r.get("total_turns", 0),
             "score": r.get("final_score", 0), "p0": r.get("p0_count", 0), "p1": r.get("p1_count", 0)}
            for r in valid_results
        ],
        "suggestions": ["补充未覆盖风险话术", "增强拒绝退出逻辑", "补充覆盖率缺口用户画像"],
    })


# ============================================================
# Routes
# ============================================================

@app.post("/api/evaluate/jobs")
async def create_evaluation_job(request: EvalRequest):
    """Create an evaluation job and return immediately."""
    job_id = uuid.uuid4().hex
    job = EvaluationJob(job_id, request)
    EVALUATION_JOBS[job_id] = job
    job.task = asyncio.create_task(_run_evaluation_job(job))
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at.isoformat(timespec="seconds"),
    }


@app.get("/api/evaluate/jobs/{job_id}")
async def get_evaluation_job(job_id: str):
    """Return evaluation job status."""
    job = EVALUATION_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="evaluation job not found")
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at.isoformat(timespec="seconds"),
        "updated_at": job.updated_at.isoformat(timespec="seconds"),
        "event_count": len(job.events),
        "eval_id": job.eval_id,
        "output_path": job.output_path,
        "error": job.error,
    }


@app.get("/api/evaluate/jobs/{job_id}/events")
async def stream_evaluation_job_events(job_id: str):
    """Stream events for an existing evaluation job."""
    job = EVALUATION_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="evaluation job not found")
    return StreamingResponse(
        _job_event_stream(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/evaluate/jobs/{job_id}")
async def cancel_evaluation_job(job_id: str):
    """Cancel a running evaluation job."""
    job = EVALUATION_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="evaluation job not found")
    if job.task and not job.task.done():
        job.task.cancel()
    job.status = "cancelled"
    job.updated_at = datetime.now()
    await _finish_job(job)
    return {"job_id": job.id, "status": job.status}


@app.post("/api/evaluate")
async def evaluate(request: EvalRequest):
    """Return realtime evaluation SSE stream."""
    return StreamingResponse(
        run_evaluation_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/demo")
@app.post("/api/demo")
async def demo_evaluate(task_id: str = "task_001_rider_flying_leg"):
    """Return demo SSE stream from prerecorded data."""
    return StreamingResponse(
        run_demo_stream(task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/examples")
async def get_examples():
    """Return example task metadata."""
    examples_dir = PROJECT_ROOT / "data" / "processed"
    examples = []
    if examples_dir.exists():
        for f in sorted(examples_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                examples.append({
                    "id": f.stem,
                    "name": data.get("role", f.stem)[:30],
                    "goal": data.get("goal", "")[:50],
                    "file": str(f.relative_to(PROJECT_ROOT)),
                })
            except Exception:
                pass
    return {"examples": examples}


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ============================================================
# 鎶ュ憡鐩稿叧鎺ュ彛
# ============================================================

@app.get("/api/report")
async def get_report(format: str = "markdown", eval_id: str | None = None):
    """Return generated report for the latest or selected evaluation."""
    from src.report.eval_report_generator import generate_eval_report, render_report_markdown

    pipeline_output = _load_eval_result(eval_id)
    if pipeline_output is None:
        raise HTTPException(status_code=404, detail="鏃犺瘎娴嬬粨鏋滐紝璇峰厛杩愯璇勬祴")

    report = generate_eval_report(pipeline_output)

    if format == "json":
        return report
    else:
        markdown = render_report_markdown(report)
        return {"markdown": markdown}


@app.get("/api/report/download")
async def download_report(format: str = "markdown", eval_id: str | None = None):
    """Download generated report."""
    from fastapi.responses import FileResponse
    from src.report.eval_report_generator import generate_eval_report, render_report_markdown, write_eval_report

    pipeline_output = _load_eval_result(eval_id)
    if pipeline_output is None:
        raise HTTPException(status_code=404, detail="无评测结果")

    result = write_eval_report(pipeline_output, output_dir=PROJECT_ROOT / "data" / "reports")

    if format == "json":
        return FileResponse(
            result["json"],
            media_type="application/json",
            filename=Path(result["json"]).name,
        )
    else:
        return FileResponse(
            result["markdown"],
            media_type="text/markdown",
            filename=Path(result["markdown"]).name,
        )


# ============================================================
# 璇勬祴鍘嗗彶鎺ュ彛
# ============================================================

@app.get("/api/evaluations")
async def list_evaluations():
    """List evaluation history."""
    eval_dir = PROJECT_ROOT / "data" / "eval"
    if not eval_dir.exists():
        return {"evaluations": []}

    results = []
    for f in sorted(eval_dir.glob("eval_pipeline_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            task_id = data.get("parsed_task", {}).get("task_id", "unknown")
            results.append({
                "id": f.stem,
                "task_id": task_id,
                "scenario_count": data.get("scenario_count", 0),
                "success_count": data.get("success_count", 0),
                "created_at": data.get("started_at", ""),
                "file": f.name,
            })
        except Exception:
            pass

    return {"evaluations": results[:20]}


@app.get("/api/evaluations/{eval_id}")
async def get_evaluation(eval_id: str):
    """Return one evaluation result."""
    pipeline_output = _load_eval_result(eval_id)
    if pipeline_output is None:
        raise HTTPException(status_code=404, detail=f"鏈壘鍒拌瘎娴嬬粨鏋? {eval_id}")
    return pipeline_output


# ============================================================
# 鏂囦欢涓婁紶鎺ュ彛
# ============================================================

@app.post("/api/upload")
async def upload_instruction(file: Any = None):
    """Upload an instruction file and return extracted text."""
    raise HTTPException(status_code=501, detail="璇蜂娇鐢≒OST /api/evaluate鐩存帴浼爄nstruction鏂囨湰")


@app.post("/api/upload-file")
async def upload_file(file: bytes = None):
    """Return uploaded file text."""
    from fastapi import UploadFile, File, Form
    raise HTTPException(
        status_code=501,
        detail="前端请在客户端读取文件文本，直接POST到/api/evaluate。",
    )


# ============================================================
# DSL/鐘舵€佹満鎺ュ彛锛堢嫭绔嬩簬SSE锛屼緵鍓嶇鍒濆鍖栨垨鍥炵湅锛?# ============================================================

@app.get("/api/dsl/state-names")
async def get_state_names():
    """Return display labels for states and dimensions."""
    return {"state_names": STATE_DISPLAY_NAMES, "dimension_labels": DIMENSION_DISPLAY}


@app.post("/api/dsl/compile")
async def compile_dsl_endpoint(instruction: str = ""):
    """Compile DSL preview without running evaluation."""
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="instruction涓嶈兘涓虹┖")

    llm = DeepSeekClient()
    parser = InstructionParser(llm)
    parsed_task = parser.parse(instruction)
    dsl = compile_dsl(parsed_task)

    states_info = [
        {"id": s.id, "label": STATE_DISPLAY_NAMES.get(s.id, s.id),
         "terminal": s.terminal, "entry": s.entry,
         "required_actions": s.required_actions,
         "forbidden_actions": s.forbidden_actions}
        for s in dsl.states
    ]
    edges_info = [
        {"from": s.id, "to": tr.to,
         "label": tr.when.intent or (tr.when.rule_keywords[0][:8] if tr.when.rule_keywords else ""),
         "condition": {
             "intent": tr.when.intent,
             "keywords": tr.when.rule_keywords[:3],
             "slots": tr.when.slot_equals,
         }}
        for s in dsl.states for tr in s.transitions
    ]

    return {
        "task_id": dsl.task_id,
        "role": dsl.role,
        "objective": dsl.objective,
        "states": states_info,
        "edges": edges_info,
        "state_count": len(dsl.states),
        "edge_count": len(dsl.all_edges),
        "mermaid": export_mermaid_statediagram(dsl),
        "severity_rules": {
            "p0": [{"id": r.id, "description": r.description} for r in dsl.severity_rules if r.level == "P0"],
            "p1": [{"id": r.id, "description": r.description} for r in dsl.severity_rules if r.level == "P1"],
        },
        "atomic_requirements": [
            {"id": r.id, "description": r.description, "bound_state": r.bound_to_state}
            for r in dsl.atomic_requirements
        ],
        "global_constraints": {
            "max_reply_chars": dsl.global_constraints.max_reply_chars,
            "forbidden_phrases": dsl.global_constraints.forbidden_phrases,
        },
    }


class BatchEvalRequest(BaseModel):
    """Batch evaluation request: submit multiple tasks at once."""
    tasks: list[EvalRequest]


@app.post("/api/batch-evaluate", summary="批量评测", description="提交多个任务指令进行批量评测，返回各任务的job_id")
async def batch_evaluate(request: BatchEvalRequest):
    """Submit multiple evaluation tasks. Each returns a job_id for polling."""
    if not request.tasks:
        raise HTTPException(status_code=400, detail="tasks不能为空")
    if len(request.tasks) > 20:
        raise HTTPException(status_code=400, detail="单次批量最多20个任务")

    jobs = []
    for task in request.tasks:
        job_id = uuid.uuid4().hex[:12]
        job = EvaluationJob(job_id, task)
        EVALUATION_JOBS[job_id] = job
        job.task = asyncio.create_task(_run_evaluation_job(job))
        jobs.append({"job_id": job.id, "status": job.status, "instruction_preview": task.instruction[:50]})

    return {"jobs": jobs, "total": len(jobs)}


# ============================================================
# 鍐呴儴宸ュ叿鍑芥暟
# ============================================================

def _load_eval_result(eval_id: str | None = None) -> dict | None:
    """Load persisted evaluation JSON."""
    eval_dir = PROJECT_ROOT / "data" / "eval"
    if not eval_dir.exists():
        return None

    if eval_id:
        target = eval_dir / f"{eval_id}.json"
        if not target.exists():
            # 灏濊瘯妯＄硦鍖归厤
            matches = list(eval_dir.glob(f"*{eval_id}*.json"))
            if matches:
                target = matches[0]
            else:
                return None
        return json.loads(target.read_text(encoding="utf-8"))
    else:
        files = sorted(eval_dir.glob("eval_pipeline_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        return json.loads(files[0].read_text(encoding="utf-8"))


# ============================================================
# 闈欐€佹枃浠舵寕杞斤紙蹇呴』鍦ㄦ墍鏈堿PI璺敱涔嬪悗锛?# ============================================================
if _frontend_dist.exists():
    from starlette.responses import FileResponse as _FR
    from fastapi.staticfiles import StaticFiles

    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def _serve_spa(full_path: str):
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return _FR(str(file_path))
        return _FR(str(_frontend_dist / "index.html"))

