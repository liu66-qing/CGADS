"""自动对话运行器 - 模拟完整通电话并评测"""

import json
import sys
import io
import time
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from src.llm_client import DeepSeekClient
from src.response_generator.engine import DialogueEngine, load_task_config
from src.evaluators.user_simulator import (
    UserSimulator, RIDER_SCENARIOS, COURSE_SCENARIOS,
)
from src.checkers import run_all_checks, is_compliant


def run_single_dialogue(task_config: dict, scenario: dict, max_turns: int = 12) -> dict:
    """运行一通完整电话对话"""
    llm = DeepSeekClient()

    # 初始化引擎和模拟用户
    engine = DialogueEngine(task_config, llm=llm)
    user_sim = UserSimulator(
        llm=llm,
        persona=scenario["persona"],
        behavior=scenario["behavior"],
    )

    # 开场
    opening = engine.get_opening()
    print(f"  客服: {opening}")

    # 模拟用户对开场白的回应
    user_reply = user_sim.respond(opening)
    print(f"  用户: {user_reply}")

    turn_results = []
    ended_naturally = False

    for turn in range(max_turns):
        # 引擎生成回复
        result = engine.generate_reply(user_reply)
        agent_reply = result["reply"]
        print(f"  客服: {agent_reply}  [{'✓' if result['compliant'] else '✗'} 尝试{result['attempts']}次]")

        turn_results.append({
            "turn": turn + 1,
            "user": user_reply,
            "agent": agent_reply,
            "compliant": result["compliant"],
            "state": result.get("state"),
            "attempts": result["attempts"],
        })

        # 检查是否应结束
        if engine.should_end_call():
            ended_naturally = True
            print(f"  [通话结束 - 状态跟踪判定]")
            break

        # 简单结束检测：如果回复包含告别语
        end_keywords = ["再见", "挂断", "稍后再打", "再联系", "拜拜"]
        if any(kw in agent_reply for kw in end_keywords):
            ended_naturally = True
            print(f"  [通话结束 - 告别语检测]")
            break

        # 模拟用户回复
        user_reply = user_sim.respond(agent_reply)
        print(f"  用户: {user_reply}")

        time.sleep(0.5)  # 避免API限流

    # 统计
    total_turns = len(turn_results)
    compliant_turns = sum(1 for t in turn_results if t["compliant"])

    return {
        "scenario": scenario["name"],
        "total_turns": total_turns,
        "compliant_turns": compliant_turns,
        "compliance_rate": compliant_turns / total_turns if total_turns > 0 else 0,
        "ended_naturally": ended_naturally,
        "turns": turn_results,
        "full_history": engine.get_dialogue_history(),
    }


def run_batch(task_id: str = "task_001_rider_flying_leg", scenarios: list = None):
    """批量运行多个场景"""
    task_path = Path(__file__).parent / "data" / "processed" / f"{task_id}.json"
    task_config = load_task_config(str(task_path))

    if scenarios is None:
        if "rider" in task_id:
            scenarios = RIDER_SCENARIOS
        else:
            scenarios = COURSE_SCENARIOS

    print(f"{'='*60}")
    print(f"任务: {task_config['goal']}")
    print(f"角色: {task_config['role']}")
    print(f"场景数: {len(scenarios)}")
    print(f"{'='*60}\n")

    all_results = []

    for i, scenario in enumerate(scenarios):
        print(f"\n--- 场景 {i+1}/{len(scenarios)}: {scenario['name']} ---")
        print(f"    画像: {scenario['persona']}")
        print(f"    行为: {scenario['behavior']}")
        print()

        try:
            result = run_single_dialogue(task_config, scenario)
            all_results.append(result)
            print(f"\n  [结果] 轮次:{result['total_turns']} "
                  f"合规率:{result['compliance_rate']:.0%} "
                  f"自然结束:{'是' if result['ended_naturally'] else '否'}")
        except Exception as e:
            print(f"\n  [错误] {e}")
            all_results.append({"scenario": scenario["name"], "error": str(e)})

        print()

    # 汇总报告
    print(f"\n{'='*60}")
    print(f"汇总报告")
    print(f"{'='*60}")

    valid_results = [r for r in all_results if "error" not in r]
    if valid_results:
        avg_turns = sum(r["total_turns"] for r in valid_results) / len(valid_results)
        avg_compliance = sum(r["compliance_rate"] for r in valid_results) / len(valid_results)
        natural_end_rate = sum(1 for r in valid_results if r["ended_naturally"]) / len(valid_results)

        print(f"  成功运行: {len(valid_results)}/{len(all_results)}")
        print(f"  平均轮次: {avg_turns:.1f}")
        print(f"  平均合规率: {avg_compliance:.0%}")
        print(f"  自然结束率: {natural_end_rate:.0%}")

        print(f"\n  各场景详情:")
        for r in valid_results:
            status = "✓" if r["compliance_rate"] >= 0.8 else "△" if r["compliance_rate"] >= 0.5 else "✗"
            print(f"    {status} {r['scenario']}: {r['total_turns']}轮 合规{r['compliance_rate']:.0%} "
                  f"{'自然结束' if r['ended_naturally'] else '超时截断'}")

    # 保存结果
    report_path = Path(__file__).parent / "experiments" / "reports"
    report_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = report_path / f"dialogue_report_{task_id}_{timestamp}.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n  报告已保存: {report_file}")


def run_single_interactive(task_id: str = "task_001_rider_flying_leg"):
    """交互模式：人工输入用户话语"""
    task_path = Path(__file__).parent / "data" / "processed" / f"{task_id}.json"
    task_config = load_task_config(str(task_path))
    llm = DeepSeekClient()
    engine = DialogueEngine(task_config, llm=llm)

    print(f"=== 交互对话: {task_config['role']} ===")
    print(f"目标: {task_config['goal']}")
    print(f"字数限制: {task_config.get('max_reply_length', 30)}字")
    print()

    opening = engine.get_opening()
    print(f"客服: {opening}")
    print()

    while True:
        user_input = input("用户> ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break

        result = engine.generate_reply(user_input)
        status = "✓" if result["compliant"] else "✗"
        print(f"客服: {result['reply']}  [{status}]")

        if result.get("state"):
            state = result["state"]
            print(f"      [状态: {state.get('current_step', '?')} | "
                  f"意图: {state.get('user_intent', '?')} | "
                  f"结束: {state.get('should_end', False)}]")
        print()

        if engine.should_end_call():
            print("[通话结束]")
            break


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        task = sys.argv[2] if len(sys.argv) > 2 else "task_001_rider_flying_leg"

        if mode == "batch":
            run_batch(task)
        elif mode == "interactive":
            run_single_interactive(task)
        elif mode == "single":
            # 跑单个场景快速测试
            task_path = Path(__file__).parent / "data" / "processed" / f"{task}.json"
            config = load_task_config(str(task_path))
            scenario = RIDER_SCENARIOS[0] if "rider" in task else COURSE_SCENARIOS[0]
            run_single_dialogue(config, scenario)
        else:
            print("用法: python run_dialogue.py [batch|interactive|single] [task_id]")
    else:
        print("用法:")
        print("  python run_dialogue.py batch                    # 批量跑所有场景")
        print("  python run_dialogue.py interactive              # 人工交互")
        print("  python run_dialogue.py single                   # 跑单个场景")
        print("  python run_dialogue.py batch task_002_course_platform_livestream  # 指定任务")
