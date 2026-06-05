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
from pydantic import BaseModel

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
    instruction: str
    budget: int = 8
    warmup_ratio: float = 0.5
    max_turns: int = 10


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


# ============================================================
# SSE Pipeline
# ============================================================

async def run_evaluation_stream(request: EvalRequest) -> AsyncGenerator[str, None]:
    """Stream realtime evaluation events."""

    pipeline_started = time.time()
    started_at = datetime.now()
    logger.info(
        "evaluation started budget=%s warmup_ratio=%s max_turns=%s instruction_chars=%s",
        request.budget,
        request.warmup_ratio,
        request.max_turns,
        len(request.instruction or ""),
    )
    llm = DeepSeekClient()

    yield sse_event("stage_start", {"stage": "parsing", "label": "指令解析"})
    t0 = time.time()
    try:
        parser = InstructionParser(llm)
        parsed_task = parser.parse(request.instruction)
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
    except Exception as exc:
        yield sse_event("stage_error", {"stage": "parsing", "error": str(exc)})
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
    warmup_k = max(2, int(request.budget * request.warmup_ratio))

    all_scenarios = generator.generate_base()
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
            "budget": request.budget,
        },
    })

    await asyncio.sleep(0.1)

    yield sse_event("stage_start", {"stage": "dialogue", "label": "瀵硅瘽鎵ц"})
    t0 = time.time()
    logger.info("dialogue stage started warmup_scenarios=%s", len(scenarios_round1))

    scenario_results = []
    for idx, scenario in enumerate(scenarios_round1):
        result = await _run_single_scenario(scenario, idx, parsed_task, dsl, llm, request.max_turns)
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
        })

    # Gap鍒嗘瀽
    gaps = coverage_tracker.uncovered_targets()
    remaining_budget = request.budget - len(scenarios_round1)

    if gaps and remaining_budget > 0:
        yield sse_event("cgads_gaps", {
            "gap_count": len(gaps),
            "gaps": gaps[:10],
        })

        # Round 2: targeted
        gap_scenarios = generator.generate_from_coverage_report(gaps)[:remaining_budget]
        yield sse_event("cgads_round", {
            "round": 2,
            "type": "targeted",
            "scenario_count": len(gap_scenarios),
            "scenarios": [{"name": s.get("name", ""), "targets": s.get("coverage_targets", [])} for s in gap_scenarios],
        })

        for idx, scenario in enumerate(gap_scenarios):
            result = await _run_single_scenario(scenario, len(scenarios_round1) + idx, parsed_task, dsl, llm, request.max_turns)
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
            })

    duration = round(time.time() - t0, 2)
    final_coverage = coverage_tracker.report().to_dict()
    adequacy = not bool(coverage_tracker.uncovered_targets())

    yield sse_event("stage_complete", {
        "stage": "dialogue",
        "duration_s": duration,
        "result": {
            "total_scenarios": len(scenario_results),
            "rounds": 2 if gaps and remaining_budget > 0 else 1,
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
    rounds = 2 if gaps and remaining_budget > 0 else 1
    output_path = _write_realtime_eval_result(
        parsed_task=parsed_task,
        coverage_report=final_coverage,
        uncovered_targets=coverage_tracker.uncovered_targets(),
        scenario_results=scenario_results,
        started_at=started_at,
        budget=request.budget,
        warmup_k=warmup_k,
        rounds=rounds,
    )

    yield sse_event("pipeline_complete", {
        "eval_id": output_path.stem,
        "output_path": str(output_path),
        "total_score": round(avg_score, 1),
        "pass_status": pass_status,
        "coverage": final_coverage,
        "adequacy": adequacy,
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
        "suggestions": [
            "针对未覆盖风险规则补充对应话术分支",
            "对P1违规场景增加拒绝退出和验证路径话术",
            "补充覆盖率缺口对应的用户画像测试",
        ],
    })


async def _run_single_scenario(
    scenario: dict, index: int, parsed_task: dict, dsl: Any, llm: DeepSeekClient, max_turns: int
) -> dict:
    """Run one realtime scenario and return a result dict."""
    scenario_id = scenario.get("name", f"scenario_{index:03d}")
    try:
        scenario_started = time.time()
        logger.info("scenario started id=%s index=%s max_turns=%s", scenario_id, index, max_turns)
        sim = create_simulator_from_scenario(scenario, llm)
        sim.llm = None  # Realtime API uses deterministic user fallback to avoid doubling LLM latency.
        state_tracker = StateTracker(dsl=dsl, llm=None)  # 绾鍒欐ā寮忥細鐪?0%寤惰繜锛岃鍒欏叧閿瘝宸茶鐩栦富瑕佹剰鍥?        checker = AutoCheckerBuilder(parsed_task)
        checker = AutoCheckerBuilder(parsed_task)

        history: list[dict[str, str]] = []
        state_trace = []
        rule_results_all = []
        violation_ids = []

        agent_msg = parsed_task.get("opening_line", "你好，我是客服。")[:80]
        history.append({"role": "assistant", "content": agent_msg})

        for turn in range(1, max_turns + 1):
            turn_started = time.time()
            user_reply = sim.respond(agent_msg)
            history.append({"role": "user", "content": user_reply})

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

            # Agent reply
            agent_msg = await _chat_with_timeout(llm, [
                {"role": "system", "content": f"你是{parsed_task.get('role','')}。目标:{parsed_task.get('goal','')[:30]}。只输出一句话，不超过{parsed_task.get('max_reply_length',30)}字。"},
                *history[-6:]
            ], max_tokens=150, temperature=0.3, fallback="好的，我这边记录一下。")
            history.append({"role": "assistant", "content": agent_msg})

            state_tracker.observe_agent(turn, agent_msg)

            # Rule check
            assistant_hist = [m["content"] for m in history if m["role"] == "assistant"][:-1]
            results = checker.run_all(agent_msg, user_reply, assistant_hist)
            violations = [r for r in results if not r.passed]
            for v in violations:
                violation_ids.append(v.rule_name)
            rule_results_all.append({"turn": turn, "compliant": not violations})

            if sim.should_hangup() or state_tracker.current_state in ("refusal_exit", "closing"):
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

        dim_scores = {
            "task_completion": 4 if total_turns >= 3 else 2,
            "flow_state_adherence": 4 if any(t.get("new_state") != "opening" for t in state_trace) else 2,
            "constraint_compliance": 5 if compliant_turns == total_turns else 3,
            "branch_handling": 3,
            "context_consistency": 4,
            "communication_experience": 4 if total_turns >= 2 else 3,
        }

        p0_count = sum(1 for v in set(violation_ids) if "p0" in v)
        p1_count = sum(1 for v in set(violation_ids) if "p1" in v)
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
            "violation_rule_ids": list(set(violation_ids)),
            "satisfied_requirements": [],
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

