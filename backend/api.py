"""FastAPI SSE 后端 — 为 React 前端提供实时评测流式接口。

启动：
    uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload

SSE 事件流设计：
    POST /api/evaluate  → SSE stream
    GET  /api/examples  → 示例任务列表
    GET  /api/health    → 健康检查
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, AsyncGenerator

# 确保项目根目录在 path
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

app = FastAPI(title="CGADS Evaluation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React前端build产物（如果存在）
_frontend_dist = PROJECT_ROOT / "frontend" / "dist"


# ============================================================
# Models
# ============================================================

class EvalRequest(BaseModel):
    instruction: str
    budget: int = 8
    warmup_ratio: float = 0.5
    max_turns: int = 10


# ============================================================
# Helpers
# ============================================================

def sse_event(event: str, data: Any) -> str:
    """Format a Server-Sent Event."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


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
    """主评测流 — 逐步推送SSE事件。"""

    llm = DeepSeekClient()

    # ═══ Stage 1: 指令解析 ═══
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

    # ═══ Stage 2: DSL编译 ═══
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

    # ═══ Stage 3: CGADS场景生成 ═══
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

    # 跑Round 1 scenarios收集覆盖率
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

    # Gap分析
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
        "stage": "scenario_gen",
        "duration_s": duration,
        "result": {
            "total_scenarios": len(scenario_results),
            "rounds": 2 if gaps and remaining_budget > 0 else 1,
            "coverage": final_coverage,
            "adequacy": adequacy,
        },
    })

    await asyncio.sleep(0.1)

    # ═══ Stage 4+5: 评测评分（已在场景运行中完成）═══
    yield sse_event("stage_start", {"stage": "scoring", "label": "评测评分"})

    # 汇总分数
    valid_results = [r for r in scenario_results if not r.get("error")]
    scores = [r.get("final_score", 0) for r in valid_results]
    avg_score = sum(scores) / len(scores) if scores else 0

    # 汇总维度
    dim_avg = {}
    for dim in DIMENSION_DISPLAY:
        vals = [r.get("dimension_scores", {}).get(dim, 3) for r in valid_results if r.get("dimension_scores")]
        dim_avg[dim] = round(sum(vals) / len(vals), 1) if vals else 3.0

    # 汇总violations
    all_violations = []
    for r in valid_results:
        for v in r.get("violation_rule_ids", []):
            all_violations.append({"scenario": r.get("scenario_id", ""), "rule_id": v})

    total_p0 = sum(r.get("p0_count", 0) for r in valid_results)
    total_p1 = sum(r.get("p1_count", 0) for r in valid_results)

    # 判定pass_status
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

    # ═══ Final: pipeline完成 ═══
    yield sse_event("pipeline_complete", {
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
    """运行单个场景，返回结果dict。"""
    scenario_id = scenario.get("name", f"scenario_{index:03d}")
    try:
        sim = create_simulator_from_scenario(scenario, llm)
        state_tracker = StateTracker(dsl=dsl, llm=llm)
        checker = AutoCheckerBuilder(parsed_task)

        history: list[dict[str, str]] = []
        state_trace = []
        rule_results_all = []
        violation_ids = []

        agent_msg = parsed_task.get("opening_line", "你好，我是客服。")[:80]
        history.append({"role": "assistant", "content": agent_msg})

        for turn in range(1, max_turns + 1):
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
            agent_msg = llm.chat([
                {"role": "system", "content": f"你是{parsed_task.get('role','')}。目标:{parsed_task.get('goal','')[:30]}。只输出一句话不超{parsed_task.get('max_reply_length',30)}字。"},
                *history[-6:]
            ], max_tokens=150, temperature=0.3)
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

            await asyncio.sleep(0.05)

        # Judge
        compliant_turns = sum(1 for r in rule_results_all if r["compliant"])
        total_turns = len(rule_results_all)

        judge = LLMJudge(parsed_task, llm)
        evaluation = judge.full_evaluation(history, compliant_turns, total_turns)

        # Score
        dim_scores = {
            "task_completion": evaluation.get("dialogue_score", {}).get("overall", 3),
            "flow_state_adherence": 4 if evaluation.get("dialogue_score", {}).get("flow_followed") else 2,
            "constraint_compliance": 5 if compliant_turns == total_turns else 3,
            "branch_handling": 3,
            "context_consistency": 4,
            "communication_experience": evaluation.get("dialogue_score", {}).get("user_experience", 3),
        }

        p0_count = sum(1 for v in set(violation_ids) if "p0" in v)
        p1_count = sum(1 for v in set(violation_ids) if "p1" in v)
        final_score = compute_final_score(dim_scores, p0_count, p1_count)

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
    """适配CoverageTracker需要的StateUpdate接口。"""
    class FakeUpdate:
        def __init__(self, d):
            self.new_state = d.get("new_state", "opening")
            self.prev_state = d.get("prev_state", "opening")
            self.triggered_transition = d.get("transition")
    return [FakeUpdate(t) for t in trace]


# ============================================================
# Routes
# ============================================================

@app.post("/api/evaluate")
async def evaluate(request: EvalRequest):
    """主评测接口 — 返回SSE事件流。"""
    return StreamingResponse(
        run_evaluation_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/examples")
async def get_examples():
    """返回示例任务列表。"""
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
# 报告相关接口
# ============================================================

@app.get("/api/report")
async def get_report(format: str = "markdown", eval_id: str | None = None):
    """获取评估报告。

    Args:
        format: "markdown" 或 "json"
        eval_id: 指定评测结果文件名（不含扩展名）。默认取最新。
    """
    from src.report.eval_report_generator import generate_eval_report, render_report_markdown

    pipeline_output = _load_eval_result(eval_id)
    if pipeline_output is None:
        raise HTTPException(status_code=404, detail="无评测结果，请先运行评测")

    report = generate_eval_report(pipeline_output)

    if format == "json":
        return report
    else:
        markdown = render_report_markdown(report)
        return {"markdown": markdown}


@app.get("/api/report/download")
async def download_report(format: str = "markdown", eval_id: str | None = None):
    """下载报告文件。"""
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
# 评测历史接口
# ============================================================

@app.get("/api/evaluations")
async def list_evaluations():
    """列出所有历史评测结果。"""
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
    """获取指定评测结果详情。"""
    pipeline_output = _load_eval_result(eval_id)
    if pipeline_output is None:
        raise HTTPException(status_code=404, detail=f"未找到评测结果: {eval_id}")
    return pipeline_output


# ============================================================
# 文件上传接口
# ============================================================

@app.post("/api/upload")
async def upload_instruction(file: Any = None):
    """上传任务指令文件（.txt/.md/.json/.xlsx/.csv）。

    返回解析后的指令文本。
    """
    from fastapi import UploadFile, File

    # 由于FastAPI的File依赖注入需要在参数声明，这里用替代方案
    raise HTTPException(status_code=501, detail="请使用POST /api/evaluate直接传instruction文本")


@app.post("/api/upload-file")
async def upload_file(file: bytes = None):
    """接收上传文件并返回文本内容。"""
    from fastapi import UploadFile, File, Form
    # 前端应将文件读为文本后传到 /api/evaluate 的 instruction 字段
    # 此接口作为辅助：接收文件→返回文本
    raise HTTPException(
        status_code=501,
        detail="前端请在客户端读取文件文本，直接POST到/api/evaluate。支持格式：.txt/.md/.json"
    )


# ============================================================
# DSL/状态机接口（独立于SSE，供前端初始化或回看）
# ============================================================

@app.get("/api/dsl/state-names")
async def get_state_names():
    """获取状态机节点中文名映射。"""
    return {"state_names": STATE_DISPLAY_NAMES, "dimension_labels": DIMENSION_DISPLAY}


@app.post("/api/dsl/compile")
async def compile_dsl_endpoint(instruction: str = ""):
    """独立DSL编译接口（不触发完整评测）。

    用于前端快速预览状态机图。
    """
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="instruction不能为空")

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
# 内部工具函数
# ============================================================

def _load_eval_result(eval_id: str | None = None) -> dict | None:
    """加载评测结果JSON。eval_id为None时取最新。"""
    eval_dir = PROJECT_ROOT / "data" / "eval"
    if not eval_dir.exists():
        return None

    if eval_id:
        target = eval_dir / f"{eval_id}.json"
        if not target.exists():
            # 尝试模糊匹配
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
# 静态文件挂载（必须在所有API路由之后）
# ============================================================
if _frontend_dist.exists():
    from starlette.responses import FileResponse as _FR
    from fastapi.staticfiles import StaticFiles

    # 挂载assets子目录
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    # 所有非/api路径 fallback 到 index.html（SPA路由支持）
    @app.get("/{full_path:path}")
    async def _serve_spa(full_path: str):
        # 如果是文件（如 favicon.svg），直接返回
        file_path = _frontend_dist / full_path
        if file_path.is_file():
            return _FR(str(file_path))
        # 否则返回index.html（React Router处理）
        return _FR(str(_frontend_dist / "index.html"))

