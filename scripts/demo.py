"""交互式对话 Demo - 可直接运行测试整个链路"""

import json
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.checkers import run_all_checks, is_compliant, get_violations


def load_task(task_id: str) -> dict:
    task_path = Path(__file__).parent / "data" / "processed" / f"{task_id}.json"
    with open(task_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_system_prompt(config: dict) -> str:
    flow_desc = "\n".join(
        f"  {i+1}. 当{s['condition']}时 → {s['action']}"
        for i, s in enumerate(config["flow"])
    )
    faq_desc = "\n".join(
        f"  - Q: {f['question_type']} → A: {f['answer']}"
        for f in config.get("faq", [])
    ) or "  无"
    constraints_desc = "\n".join(f"  - {c}" for c in config["constraints"])
    forbidden = "、".join(config.get("forbidden", [])) or "无"

    return f"""你是一个外呼电话AI助手，严格按照任务指令进行电话对话。

【角色】{config['role']}
【目标】{config['goal']}

【对话流程】
{flow_desc}

【知识点FAQ】
{faq_desc}

【约束】
{constraints_desc}

【硬性规则】
- 每次回复不超过{config.get('max_reply_length', 30)}个字
- 语气自然口语化
- 禁用词：{forbidden}
"""


def demo_interactive(task_id: str = "task_001_rider_flying_leg"):
    config = load_task(task_id)
    print(f"=== 外呼对话 Demo ===")
    print(f"任务: {config['goal']}")
    print(f"角色: {config['role']}")
    print(f"字数限制: {config.get('max_reply_length', 30)}字")
    print(f"禁用词: {config.get('forbidden', [])}")
    print()

    print(f"[系统提示词已构建，共 {len(build_system_prompt(config))} 字符]")
    print()

    print(f"【开场白】{config['opening_line']}")
    print()
    print("--- 开始模拟对话（输入 quit 退出）---")
    print()

    history = []

    while True:
        user_input = input("用户> ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            break

        # 模拟一个回复（实际使用时接入 LLM）
        mock_reply = input("模型回复> ").strip()

        # 运行约束检查
        results = run_all_checks(
            reply=mock_reply,
            user_input=user_input,
            history=history,
            task_config=config,
        )

        print()
        print(f"  [约束检查结果]")
        for r in results:
            status = "✓" if r.passed else "✗"
            print(f"    {status} {r.rule_name}: {r.message}")

        if not is_compliant(results):
            violations = get_violations(results)
            print(f"  ⚠ 不合规！需要重写。违规项: {[v.rule_name for v in violations]}")
        else:
            print(f"  ✓ 回复合规")

        history.append(mock_reply)
        print()


def demo_auto_test(task_id: str = "task_001_rider_flying_leg"):
    """自动测试用例"""
    config = load_task(task_id)
    print(f"=== 自动测试: {config['task_id']} ===\n")

    test_cases = [
        ("我知道了，今天可以跑", "好的，注意安全，加油！"),
        ("我不想跑了", "理解，但名额有限，考虑下？"),
        ("我确实跑不了，家里有事", "没关系，家里事重要，后面再说。"),
        ("怎么退出飞毛腿啊", "前一天Z点前在App飞毛腿报名中取消就行。"),
        ("为什么我排名掉了", "排名看拒单率、取消率和超时，恶劣天气跑单加分。"),
        ("今天天气怎么样", "我向同事确认后再回电给你。我现在能回答的先回答。"),
        # 超长回复测试
        ("你好", "你好你好你好你好你好你好你好你好你好你好你好你好你好你好你好你好"),
    ]

    history = []
    pass_count = 0
    total = len(test_cases)

    for user_input, reply in test_cases:
        results = run_all_checks(
            reply=reply,
            user_input=user_input,
            history=history,
            task_config=config,
        )
        compliant = is_compliant(results)
        if compliant:
            pass_count += 1

        status = "PASS" if compliant else "FAIL"
        print(f"[{status}] 用户: {user_input}")
        print(f"       回复: {reply} ({len(reply)}字)")
        if not compliant:
            for v in get_violations(results):
                print(f"       ✗ {v.rule_name}: {v.message}")
        history.append(reply)
        print()

    print(f"通过率: {pass_count}/{total} ({pass_count/total*100:.0f}%)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        demo_auto_test()
    else:
        demo_interactive()
