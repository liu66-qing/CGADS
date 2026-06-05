#!/usr/bin/env python3
"""5分钟精简演示：配合型+拒绝型场景，实时显示state/rule/coverage

Usage:
    python demo_quick.py --task rider_flying_leg

演示流程：
1. 加载任务DSL
2. 跑2个base场景（配合型+拒绝型）
3. 实时显示每轮：state跳转、rule检查、coverage增量
4. 最后展示覆盖率统计
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.dsl.compiler import compile_dsl
from src.dsl.coverage import CoverageTracker
from src.dsl.state_tracker import StateTracker
from src.evaluators.coverage_driven_scenario_generator import CoverageDrivenScenarioGenerator
from src.evaluators.three_layer_user_simulator import create_simulator_from_scenario
from src.checkers.auto_checker_builder import AutoCheckerBuilder
from src.llm_client import DeepSeekClient
import json


def print_divider(char="=", width=80):
    print(char * width)


def run_quick_demo(task_file: str):
    """运行快速演示"""
    print_divider()
    print(f"📞 美团AI数字人外呼评测系统 - 5分钟演示")
    print_divider()
    print()

    # 1. 加载任务
    print(f"[1/4] 加载任务: {task_file}")
    with open(task_file, encoding="utf-8") as f:
        parsed_task = json.load(f)
    dsl = compile_dsl(parsed_task)
    print(f"✓ DSL编译完成: {len(dsl.states)}个状态, {len(dsl.all_edges)}条边")
    print()

    # 2. 生成2个base场景
    print(f"[2/4] 生成演示场景")
    generator = CoverageDrivenScenarioGenerator(dsl)
    all_scenarios = generator.generate_base()
    # 选择配合型和拒绝型
    demo_scenarios = [s for s in all_scenarios if s["name"] in ["配合型-base", "明确拒绝-base"]]
    print(f"✓ 生成 {len(demo_scenarios)} 个演示场景")
    print()

    # 3. 跑场景并实时显示
    print(f"[3/4] 运行场景（实时显示）")
    print_divider("-")

    llm = DeepSeekClient()
    checker_builder = AutoCheckerBuilder()
    coverage_tracker = CoverageTracker(dsl)

    for idx, scenario in enumerate(demo_scenarios, 1):
        print(f"\n场景 {idx}/{len(demo_scenarios)}: {scenario['name']}")
        print_divider("-", width=60)

        state_tracker = StateTracker(dsl, llm)
        user_sim = create_simulator_from_scenario(scenario, parsed_task, llm)

        history = []
        max_turns = 5  # 快速演示限制5轮

        for turn in range(1, max_turns + 1):
            # 用户回复
            user_reply = user_sim.generate_next_reply(history)
            if user_reply is None:
                print(f"  [Turn {turn}] 用户挂断")
                break

            history.append({"role": "user", "content": user_reply})

            # 状态追踪
            prev_state = state_tracker.current_state_id
            state_update = state_tracker.update_state(user_reply, history)
            new_state = state_update["new_state"]

            print(f"  [Turn {turn}] 用户: {user_reply[:40]}")

            # 状态跳转
            if new_state != prev_state:
                print(f"           → State: {prev_state} → {new_state} (置信度{state_update['intent_confidence']:.2f})")
            else:
                print(f"           → State: {new_state} (保持)")

            # Agent回复（简化版）
            agent_reply = f"好的，{parsed_task['role']}为您服务"  # 演示用简化回复
            history.append({"role": "assistant", "content": agent_reply})
            print(f"           客服: {agent_reply}")

            # 规则检查
            check_result = checker_builder.check_turn(
                agent_reply=agent_reply,
                history=history,
                parsed_task=parsed_task,
                current_state=new_state,
            )

            compliant = check_result["compliant"]
            violations = check_result.get("violations", [])

            if compliant:
                print(f"           ✓ Rule: 合规（字数{len(agent_reply)}字）")
            else:
                print(f"           ✗ Rule: 违规 - {violations[0] if violations else '未知'}")

            # 覆盖率更新
            coverage_tracker.record_scenario(
                scenario_id=scenario["name"],
                state_updates=[state_update],
                coverage_targets=scenario.get("coverage_targets", []),
                violation_rule_ids=[v["rule_id"] for v in violations],
                satisfied_requirements=[],
            )

            if new_state in dsl.terminal_states:
                print(f"  [Turn {turn+1}] 对话结束（到达终态）")
                break

        print()

    # 4. 展示覆盖率
    print_divider("-")
    print(f"[4/4] 覆盖率统计")
    print_divider("-")

    report = coverage_tracker.report()

    print(f"State覆盖率:  {report.state_coverage.hit}/{report.state_coverage.total} = {report.state_coverage.ratio:.1%}")
    print(f"Edge覆盖率:   {report.transition_coverage.hit}/{report.transition_coverage.total} = {report.transition_coverage.ratio:.1%}")
    print(f"Risk覆盖率:   {report.risk_coverage.hit}/{report.risk_coverage.total} = {report.risk_coverage.ratio:.1%}")
    print(f"需求覆盖率:   {report.requirement_coverage.hit}/{report.requirement_coverage.total} = {report.requirement_coverage.ratio:.1%}")

    uncovered = report.uncovered_targets()
    if uncovered:
        print(f"\n未覆盖目标（前5个）:")
        for target in uncovered[:5]:
            print(f"  - {target}")

    print()
    print_divider()
    print("✅ 演示完成！完整评测请运行: python run_eval_pipeline.py --instruction_file <task.json>")
    print_divider()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="5分钟快速演示")
    parser.add_argument("--task", default="data/processed/task_001_rider_flying_leg.json", help="任务文件路径")
    args = parser.parse_args()

    run_quick_demo(args.task)
