"""DSL 模块 smoke test：编译 task_001 + 模拟 5 轮状态追踪 + 覆盖率聚合。

不调用 LLM（StateTracker 不传 llm 时走 rule_intent / fallback 路径）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 过滤掉外部 editable 包路径（mira_api / Datawhale），避免 src 命名冲突
sys.path[:] = [
    p for p in sys.path
    if "editable" not in p.lower()
    and "mira_api" not in p.lower()
    and "Datawhale" not in p
    and "hello-agents" not in p
]
sys.path.insert(0, str(ROOT))

# 同步清理已被外部 src 占位的 sys.modules
for mod in list(sys.modules):
    if mod == "src" or mod.startswith("src."):
        del sys.modules[mod]

from src.dsl import CoverageTracker, StateTracker, compile_dsl  # type: ignore  # noqa: E402


def main() -> None:
    parsed_path = ROOT / "data" / "processed" / "task_001_rider_flying_leg.json"
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))

    dsl = compile_dsl(parsed)
    print(f"[compile] task_id={dsl.task_id} states={len(dsl.states)} "
          f"edges={len(dsl.all_edges)} risks="
          f"{sum(1 for r in dsl.severity_rules if r.level in ('P0','P1'))} "
          f"reqs={len(dsl.atomic_requirements)}")

    tracker = StateTracker(dsl=dsl, llm=None)
    sample_dialogue = [
        ("assistant", "您好，我是站长，飞毛腿合同已生效。"),
        ("user", "哦，今天要跑几单？"),
        ("assistant", "单日合同每天至少 X 单，停跑会影响。"),
        ("user", "你是诈骗吧？怎么证明？"),
        ("assistant", "您可在美团 App 消息中心查看官方通知核实。"),
        ("user", "我不需要，别打了。"),
        ("assistant", "好的，打扰了，祝您工作顺利。"),
    ]

    turn = 0
    for role, content in sample_dialogue:
        if role == "assistant":
            tracker.observe_agent(turn, content)
        else:
            tracker.step(turn=turn, user_input=content)
        turn += 1

    print("\n[state_trace]")
    for upd in tracker.export_trace():
        print(f"  turn={upd['turn']:>2} {upd['prev_state']:<18}->"
              f"{upd['new_state']:<18} intent={upd['intent']:<22} "
              f"src={upd['intent_source']:<8} conf={upd['intent_confidence']:.2f} "
              f"uncertain={upd['uncertain']}")

    cov = CoverageTracker(dsl)
    cov.record_scenario(
        scenario_id="smoke_001",
        state_updates=tracker.history,
        coverage_targets=[
            "risk:p0_false_absolute_promise",
            "requirement:req_polite_refusal_exit",
            "edge:opening->refusal_exit",
        ],
        violation_rule_ids=[],
        satisfied_requirements=["req_polite_refusal_exit"],
    )
    report = cov.report().to_dict()
    print("\n[coverage]")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    print("\n[uncovered_targets sample]")
    for tgt in cov.uncovered_targets()[:10]:
        print(f"  - {tgt}")
    print(f"  ... total uncovered: {len(cov.uncovered_targets())}")


if __name__ == "__main__":
    main()
