"""对比实验 + 消融实验 - 量化各模块和prompt变体的贡献"""

import json
import sys
import io
import time
import copy
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from src.llm_client import DeepSeekClient
from src.response_generator.engine import DialogueEngine, load_task_config
from src.evaluators.user_simulator import UserSimulator, RIDER_SCENARIOS
from src.evaluators.llm_judge import LLMJudge
from src.evaluators.error_analyzer import ErrorAnalyzer
from src.checkers import run_all_checks, is_compliant
from src.prompts.variants import PROMPT_VARIANTS


# ============================================================
# 对比实验：不同 Prompt 版本
# ============================================================

class VariantEngine(DialogueEngine):
    """支持替换 prompt 模板的引擎"""

    def __init__(self, task_config: dict, llm: DeepSeekClient, prompt_template: str):
        self.config = task_config
        self.llm = llm
        self.history = []
        self.state_history = []
        self.system_prompt = self._build_from_template(prompt_template)

    def _build_from_template(self, template: str) -> str:
        flow_desc = "\n".join(
            f"  {i+1}. 当{s['condition']}时 → {s['action']}"
            for i, s in enumerate(self.config["flow"])
        )
        faq_desc = "\n".join(
            f"  - Q: {f['question_type']} → A: {f['answer']}"
            for f in self.config.get("faq", [])
        ) or "  无"
        constraints_desc = "\n".join(f"  - {c}" for c in self.config["constraints"])
        forbidden = "、".join(self.config.get("forbidden", [])) or "无"

        return template.format(
            role=self.config["role"],
            goal=self.config["goal"],
            flow_description=flow_desc,
            faq_description=faq_desc,
            constraints_description=constraints_desc,
            max_length=self.config.get("max_reply_length", 30),
            forbidden_words=forbidden,
        )


def run_variant_dialogue(task_config, scenario, prompt_template, max_turns=10):
    """用指定 prompt 模板跑一通对话"""
    llm = DeepSeekClient()
    engine = VariantEngine(task_config, llm, prompt_template)
    user_sim = UserSimulator(llm=llm, persona=scenario["persona"], behavior=scenario["behavior"])

    opening = engine.get_opening()
    user_reply = user_sim.respond(opening)

    turn_results = []
    ended_naturally = False

    for turn in range(max_turns):
        result = engine.generate_reply(user_reply)
        agent_reply = result["reply"]

        turn_results.append({
            "turn": turn + 1,
            "user": user_reply,
            "agent": agent_reply,
            "compliant": result["compliant"],
            "attempts": result["attempts"],
        })

        if engine.should_end_call():
            ended_naturally = True
            break
        end_keywords = ["再见", "挂断", "稍后再打", "再联系", "拜拜"]
        if any(kw in agent_reply for kw in end_keywords):
            ended_naturally = True
            break

        user_reply = user_sim.respond(agent_reply)
        time.sleep(0.3)

    # 评测
    judge = LLMJudge(task_config, llm=llm)
    history = engine.get_dialogue_history()
    compliant_turns = sum(1 for t in turn_results if t["compliant"])
    eval_result = judge.full_evaluation(history, compliant_turns, len(turn_results))

    return {
        "total_turns": len(turn_results),
        "compliance_rate": compliant_turns / len(turn_results) if turn_results else 0,
        "ended_naturally": ended_naturally,
        "evaluation": eval_result,
    }


def run_prompt_comparison(task_id="task_001_rider_flying_leg", scenario_idx=0):
    """对比不同 prompt 版本"""
    task_path = Path(__file__).parent / "data" / "processed" / f"{task_id}.json"
    task_config = load_task_config(str(task_path))
    scenario = RIDER_SCENARIOS[scenario_idx]

    print(f"{'='*60}")
    print(f"Prompt 对比实验")
    print(f"场景: {scenario['name']}")
    print(f"{'='*60}\n")

    results = {}

    for variant_name, template in PROMPT_VARIANTS.items():
        print(f"--- {variant_name} ---")
        try:
            r = run_variant_dialogue(task_config, scenario, template)
            results[variant_name] = r

            avgs = r["evaluation"].get("averages", {})
            ds = r["evaluation"].get("dialogue_score", {})
            print(f"  轮次:{r['total_turns']} 合规:{r['compliance_rate']:.0%} "
                  f"结束:{'自然' if r['ended_naturally'] else '截断'}")
            print(f"  连贯:{avgs.get('avg_cohesion',0):.1f} 知识:{avgs.get('avg_knowledge',0):.1f} "
                  f"合规:{avgs.get('avg_compliance',0):.1f} 推进:{avgs.get('avg_progress',0):.1f}")
            print(f"  整体:{ds.get('overall',0)}/5 任务完成:{'✓' if ds.get('task_completed') else '✗'}")
        except Exception as e:
            print(f"  [错误] {e}")
            results[variant_name] = {"error": str(e)}
        print()

    # 对比表格
    print(f"\n{'='*60}")
    print(f"对比结果")
    print(f"{'='*60}")
    print(f"{'变体':<20} {'合规率':<8} {'连贯':<6} {'知识':<6} {'合规':<6} {'推进':<6} {'整体':<6} {'任务':<6}")
    print(f"{'-'*60}")
    for name, r in results.items():
        if "error" in r:
            print(f"{name:<20} ERROR")
            continue
        avgs = r["evaluation"].get("averages", {})
        ds = r["evaluation"].get("dialogue_score", {})
        print(f"{name:<20} {r['compliance_rate']:<8.0%} "
              f"{avgs.get('avg_cohesion',0):<6.1f} {avgs.get('avg_knowledge',0):<6.1f} "
              f"{avgs.get('avg_compliance',0):<6.1f} {avgs.get('avg_progress',0):<6.1f} "
              f"{ds.get('overall',0):<6} {'✓' if ds.get('task_completed') else '✗':<6}")

    # 保存
    report_path = Path(__file__).parent / "experiments" / "ablation"
    report_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(report_path / f"prompt_comparison_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存")

    return results


# ============================================================
# 消融实验：去掉各模块看效果
# ============================================================

class AblationEngine(DialogueEngine):
    """支持关闭特定模块的引擎"""

    def __init__(self, task_config, llm, disable_state_tracking=False,
                 disable_checker=False, disable_rewrite=False):
        super().__init__(task_config, llm)
        self.disable_state_tracking = disable_state_tracking
        self.disable_checker = disable_checker
        self.disable_rewrite = disable_rewrite

    def track_state(self, user_input):
        if self.disable_state_tracking:
            return {"current_step": "disabled", "user_intent": "", "triggered_faq": None,
                    "should_end": False, "next_action": ""}
        return super().track_state(user_input)

    def generate_reply(self, user_input, max_retries=2):
        if self.disable_rewrite:
            max_retries = 0
        if self.disable_checker:
            # 跳过检查，直接返回
            self.history.append({"role": "user", "content": user_input})
            state = self.track_state(user_input)
            reply = self.llm.chat(
                messages=[{"role": "system", "content": self.system_prompt}, *self.history],
                max_tokens=1024, temperature=0.7,
            )
            self.history.append({"role": "assistant", "content": reply})
            return {"reply": reply, "state": state, "compliant": True, "attempts": 1}
        return super().generate_reply(user_input, max_retries)


def run_ablation_dialogue(task_config, scenario, **ablation_kwargs):
    """跑消融实验的单通对话"""
    llm = DeepSeekClient()
    engine = AblationEngine(task_config, llm, **ablation_kwargs)
    user_sim = UserSimulator(llm=llm, persona=scenario["persona"], behavior=scenario["behavior"])

    opening = engine.get_opening()
    user_reply = user_sim.respond(opening)

    turn_results = []
    ended_naturally = False

    for turn in range(10):
        result = engine.generate_reply(user_reply)
        agent_reply = result["reply"]

        # 即使引擎跳过了检查，这里也跑一次用于统计
        from src.checkers import run_all_checks, is_compliant
        assistant_replies = [h["content"] for h in engine.history if h["role"] == "assistant"]
        checks = run_all_checks(agent_reply, user_reply, assistant_replies[:-1], task_config)
        actually_compliant = is_compliant(checks)

        turn_results.append({
            "turn": turn + 1,
            "user": user_reply,
            "agent": agent_reply,
            "compliant": actually_compliant,
            "attempts": result["attempts"],
        })

        if engine.should_end_call():
            ended_naturally = True
            break
        end_keywords = ["再见", "挂断", "稍后再打", "再联系", "拜拜"]
        if any(kw in agent_reply for kw in end_keywords):
            ended_naturally = True
            break

        user_reply = user_sim.respond(agent_reply)
        time.sleep(0.3)

    # 评测
    judge = LLMJudge(task_config, llm=llm)
    history = engine.get_dialogue_history()
    compliant_turns = sum(1 for t in turn_results if t["compliant"])
    eval_result = judge.full_evaluation(history, compliant_turns, len(turn_results))

    return {
        "total_turns": len(turn_results),
        "compliance_rate": compliant_turns / len(turn_results) if turn_results else 0,
        "ended_naturally": ended_naturally,
        "evaluation": eval_result,
    }


def run_ablation_study(task_id="task_001_rider_flying_leg", scenario_idx=2):
    """消融实验：逐个去掉模块"""
    task_path = Path(__file__).parent / "data" / "processed" / f"{task_id}.json"
    task_config = load_task_config(str(task_path))
    scenario = RIDER_SCENARIOS[scenario_idx]

    print(f"{'='*60}")
    print(f"消融实验")
    print(f"场景: {scenario['name']}")
    print(f"{'='*60}\n")

    ablation_configs = {
        "full_system": {},
        "no_state_tracking": {"disable_state_tracking": True},
        "no_checker": {"disable_checker": True},
        "no_rewrite": {"disable_rewrite": True},
        "no_checker_no_rewrite": {"disable_checker": True, "disable_rewrite": True},
    }

    results = {}

    for name, kwargs in ablation_configs.items():
        print(f"--- {name} ---")
        disabled = [k.replace("disable_", "").replace("_", " ") for k, v in kwargs.items() if v]
        print(f"  关闭: {disabled or '无（完整系统）'}")

        try:
            r = run_ablation_dialogue(task_config, scenario, **kwargs)
            results[name] = r

            avgs = r["evaluation"].get("averages", {})
            ds = r["evaluation"].get("dialogue_score", {})
            print(f"  轮次:{r['total_turns']} 合规:{r['compliance_rate']:.0%} "
                  f"结束:{'自然' if r['ended_naturally'] else '截断'}")
            print(f"  连贯:{avgs.get('avg_cohesion',0):.1f} 知识:{avgs.get('avg_knowledge',0):.1f} "
                  f"合规:{avgs.get('avg_compliance',0):.1f} 推进:{avgs.get('avg_progress',0):.1f}")
            print(f"  整体:{ds.get('overall',0)}/5")
        except Exception as e:
            print(f"  [错误] {e}")
            results[name] = {"error": str(e)}
        print()

    # 对比表格
    print(f"\n{'='*60}")
    print(f"消融对比")
    print(f"{'='*60}")
    print(f"{'配置':<25} {'合规率':<8} {'连贯':<6} {'知识':<6} {'合规':<6} {'推进':<6} {'整体':<6}")
    print(f"{'-'*60}")
    for name, r in results.items():
        if "error" in r:
            print(f"{name:<25} ERROR")
            continue
        avgs = r["evaluation"].get("averages", {})
        ds = r["evaluation"].get("dialogue_score", {})
        print(f"{name:<25} {r['compliance_rate']:<8.0%} "
              f"{avgs.get('avg_cohesion',0):<6.1f} {avgs.get('avg_knowledge',0):<6.1f} "
              f"{avgs.get('avg_compliance',0):<6.1f} {avgs.get('avg_progress',0):<6.1f} "
              f"{ds.get('overall',0):<6}")

    # 保存
    report_path = Path(__file__).parent / "experiments" / "ablation"
    report_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(report_path / f"ablation_study_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存")

    return results


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"

    if mode == "prompt":
        run_prompt_comparison()
    elif mode == "ablation":
        run_ablation_study()
    elif mode == "all":
        print("=== Prompt 对比实验 ===\n")
        run_prompt_comparison()
        print("\n\n=== 消融实验 ===\n")
        run_ablation_study()
    else:
        print("用法:")
        print("  python run_experiments.py prompt     # Prompt对比实验")
        print("  python run_experiments.py ablation   # 消融实验")
        print("  python run_experiments.py all        # 全部")
