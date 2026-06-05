"""指令泛化引擎 - 核心亮点：任意外呼指令 → 5秒内可对话+可评测"""

import json
import sys
import io
import time
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from src.llm_client import DeepSeekClient
from src.instruction_parser.auto_parser import InstructionParser
from src.checkers.auto_checker_builder import AutoCheckerBuilder
from src.evaluators.scenario_generator import ScenarioGenerator
from src.response_generator.engine import DialogueEngine
from src.evaluators.user_simulator import UserSimulator
from src.evaluators.llm_judge import LLMJudge


class GeneralizationEngine:
    """
    指令泛化引擎 - 核心能力：
    1. 输入任意纯文本外呼指令
    2. 自动解析为结构化配置
    3. 自动生成约束检查器
    4. 自动生成评测场景
    5. 立即可以开始对话和评测
    """

    def __init__(self, llm: DeepSeekClient = None):
        self.llm = llm or DeepSeekClient()
        self.parser = InstructionParser(self.llm)
        self.task_config = None
        self.checker = None
        self.scenarios = None

    def load_instruction(self, raw_instruction: str) -> dict:
        """Step 1: 解析指令"""
        print("  [1/3] 解析指令...")
        self.task_config = self.parser.parse(raw_instruction)
        print(f"        ✓ 角色: {self.task_config['role']}")
        print(f"        ✓ 目标: {self.task_config['goal']}")
        print(f"        ✓ 流程步骤: {len(self.task_config['flow'])}步")
        print(f"        ✓ FAQ: {len(self.task_config.get('faq', []))}条")
        print(f"        ✓ 约束: {len(self.task_config['constraints'])}条")
        print(f"        ✓ 禁用词: {self.task_config.get('forbidden', [])}")
        print(f"        ✓ 字数限制: {self.task_config['max_reply_length']}字")
        return self.task_config

    def build_checker(self) -> AutoCheckerBuilder:
        """Step 2: 自动生成检查器"""
        print("  [2/3] 生成约束检查器...")
        self.checker = AutoCheckerBuilder(self.task_config)
        print(f"        ✓ 生成 {len(self.checker.rules)} 条检查规则")
        for rule in self.checker.rules:
            print(f"          - {rule.name}: {rule.description[:40]}")
        return self.checker

    def build_scenarios(self) -> list[dict]:
        """Step 3: 自动生成评测场景"""
        print("  [3/3] 生成评测场景...")
        generator = ScenarioGenerator(self.task_config, self.llm)
        self.scenarios = generator.generate_all()
        print(f"        ✓ 生成 {len(self.scenarios)} 个评测场景")
        for s in self.scenarios:
            print(f"          - {s['name']}: {s['behavior'][:35]}...")
        return self.scenarios

    def initialize(self, raw_instruction: str) -> dict:
        """一键初始化：解析 + 生成检查器 + 生成场景"""
        print(f"{'='*50}")
        print(f"指令泛化引擎 - 初始化")
        print(f"{'='*50}\n")

        start = time.time()
        config = self.load_instruction(raw_instruction)
        print()
        checker = self.build_checker()
        print()
        scenarios = self.build_scenarios()
        elapsed = time.time() - start

        print(f"\n{'='*50}")
        print(f"初始化完成！耗时 {elapsed:.1f}秒")
        print(f"{'='*50}")
        print(f"  可用命令:")
        print(f"    engine.chat(user_input)     # 开始对话")
        print(f"    engine.run_scenario(idx)    # 跑指定场景")
        print(f"    engine.run_all_scenarios()  # 跑全部场景")

        return {
            "config": config,
            "rules_count": len(checker.rules),
            "scenarios_count": len(scenarios),
            "elapsed": elapsed,
        }

    def create_dialogue_engine(self) -> DialogueEngine:
        """创建对话引擎实例"""
        return DialogueEngine(self.task_config, llm=self.llm)

    def run_scenario(self, scenario_idx: int = 0, max_turns: int = 10) -> dict:
        """跑单个评测场景"""
        scenario = self.scenarios[scenario_idx]
        print(f"\n--- 场景: {scenario['name']} ---")
        print(f"    行为: {scenario['behavior']}")
        print()

        engine = DialogueEngine(self.task_config, llm=self.llm)
        user_sim = UserSimulator(llm=self.llm, persona=scenario["persona"], behavior=scenario["behavior"])

        opening = engine.get_opening()
        print(f"  客服: {opening[:60]}...")
        user_reply = user_sim.respond(opening)
        print(f"  用户: {user_reply}")

        turn_results = []
        ended_naturally = False

        for turn in range(max_turns):
            result = engine.generate_reply(user_reply)
            agent_reply = result["reply"]

            # 用自动生成的检查器验证
            checks = self.checker.run_all(agent_reply, user_reply,
                                          [h["content"] for h in engine.history if h["role"] == "assistant"][:-1])
            compliant = self.checker.is_compliant(checks)
            status = "✓" if compliant else "✗"
            print(f"  客服: {agent_reply}  [{status}]")

            turn_results.append({
                "turn": turn + 1,
                "user": user_reply,
                "agent": agent_reply,
                "compliant": compliant,
            })

            if engine.should_end_call():
                ended_naturally = True
                print(f"  [通话结束]")
                break
            end_keywords = ["再见", "挂断", "稍后再打", "再联系", "拜拜"]
            if any(kw in agent_reply for kw in end_keywords):
                ended_naturally = True
                print(f"  [通话结束]")
                break

            user_reply = user_sim.respond(agent_reply)
            print(f"  用户: {user_reply}")
            time.sleep(0.3)

        compliant_turns = sum(1 for t in turn_results if t["compliant"])
        total = len(turn_results)

        print(f"\n  结果: {total}轮 合规{compliant_turns}/{total} {'自然结束' if ended_naturally else '截断'}")
        return {
            "scenario": scenario["name"],
            "total_turns": total,
            "compliance_rate": compliant_turns / total if total > 0 else 0,
            "ended_naturally": ended_naturally,
            "turns": turn_results,
        }

    def run_all_scenarios(self, max_turns: int = 10) -> list[dict]:
        """跑全部评测场景"""
        results = []
        for i in range(len(self.scenarios)):
            try:
                r = self.run_scenario(i, max_turns)
                results.append(r)
            except Exception as e:
                print(f"  [错误] {e}")
                results.append({"scenario": self.scenarios[i]["name"], "error": str(e)})
        return results


# ============================================================
# 命令行入口
# ============================================================

def demo_with_new_instruction():
    """用一份全新的指令演示泛化能力"""

    # 一份全新的外呼指令（不在训练示例中）
    new_instruction = """# Role
你是一家健身房的会员顾问。

# Task
致电即将到期的会员，通知续费优惠活动，争取续费。

# Opening Line
您好，请问是${member_name}吗？我是XX健身的会员顾问小李。

# Call Flow
1. 确认身份后，告知会员卡将在${expire_date}到期。
2. 介绍续费优惠：年卡续费打8折，两年卡续费打7折。
3. 如果会员犹豫，询问原因并针对性回应：
   - 太贵 → 强调日均不到10元，比外面单次便宜
   - 没时间 → 介绍灵活时段和私教预约
   - 想换地方 → 介绍新增器材和课程
4. 如果会员同意续费，告知到店办理流程。
5. 如果会员明确拒绝，表示理解并告知活动截止日期。

# Knowledge Points
- 年卡原价3600，续费价2880（8折）
- 两年卡原价6000，续费价4200（7折）
- 活动截止到本月底
- 续费需到店，带身份证即可
- 新增了动感单车区和瑜伽室

# Constraints
- 每次回复不超过25个字
- 语气热情但不过度推销
- 不能承诺额外折扣或赠品
- 不说"亲""宝""哦"等过于亲昵的词
- 会员说在忙，说"就一句话"后简短说明
- 会员明确拒绝两次以上，礼貌结束不再纠缠
"""

    engine = GeneralizationEngine()
    result = engine.initialize(new_instruction)

    print(f"\n\n{'='*50}")
    print(f"开始跑评测场景")
    print(f"{'='*50}")

    # 跑前3个场景
    for i in range(min(3, len(engine.scenarios))):
        engine.run_scenario(i)
        print()


def demo_from_file(file_path: str):
    """从文件读取指令"""
    with open(file_path, "r", encoding="utf-8") as f:
        instruction = f.read()

    engine = GeneralizationEngine()
    engine.initialize(instruction)
    engine.run_all_scenarios()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        demo_from_file(sys.argv[1])
    else:
        demo_with_new_instruction()
