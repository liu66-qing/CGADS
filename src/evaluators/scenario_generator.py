"""评测场景自动生成 - 从任务配置自动构造用户画像和测试场景"""

from ..llm_client import DeepSeekClient


class ScenarioGenerator:
    """根据任务配置自动生成评测场景"""

    def __init__(self, task_config: dict, llm: DeepSeekClient = None):
        self.config = task_config
        self.llm = llm or DeepSeekClient()

    def generate_all(self) -> list[dict]:
        """自动生成覆盖所有分支的评测场景"""
        scenarios = []

        # 1. 从 flow 的每个分支生成场景
        scenarios.extend(self._from_flow())

        # 2. 从 FAQ 生成提问场景
        scenarios.extend(self._from_faq())

        # 3. 从 end_conditions 生成触发场景
        scenarios.extend(self._from_end_conditions())

        # 4. 通用压力场景
        scenarios.extend(self._stress_scenarios())

        return scenarios

    def _from_flow(self) -> list[dict]:
        """从流程分支生成场景"""
        scenarios = []
        role = self.config.get("role", "客服")
        goal = self.config.get("goal", "")

        for step in self.config.get("flow", []):
            condition = step.get("condition", "")
            action = step.get("action", "")

            # 主流程场景
            if "确认" in condition or "同意" in condition or "开场" in condition:
                scenarios.append({
                    "name": f"配合型-{step['step_id'][:15]}",
                    "persona": f"你是接到{role}电话的人，关于{goal[:20]}",
                    "behavior": f"你比较配合，当对方{action[:20]}时，你简单确认同意",
                    "target_step": step["step_id"],
                })

            # 分支场景
            for branch in step.get("branches", []):
                branch_cond = branch.get("condition", "")
                scenarios.append({
                    "name": f"分支-{branch_cond[:10]}",
                    "persona": f"你是接到{role}电话的人",
                    "behavior": f"你的状态是：{branch_cond}。自然表达这个状态。",
                    "target_step": step["step_id"],
                })

            # 拒绝/犹豫场景
            if "不" in condition or "拒绝" in condition or "无法" in condition:
                scenarios.append({
                    "name": f"拒绝型-{step['step_id'][:15]}",
                    "persona": f"你是接到{role}电话的人",
                    "behavior": f"你{condition}，态度坚定但礼貌",
                    "target_step": step["step_id"],
                })

        return scenarios

    def _from_faq(self) -> list[dict]:
        """从FAQ生成提问场景"""
        scenarios = []
        faqs = self.config.get("faq", [])

        if faqs:
            # 单个FAQ提问
            for faq in faqs[:5]:  # 最多5个
                scenarios.append({
                    "name": f"提问-{faq['question_type'][:10]}",
                    "persona": f"你是接到{self.config.get('role', '客服')}电话的人",
                    "behavior": f"你想问关于'{faq['question_type']}'的问题，用口语化方式提问",
                    "target_faq": faq["question_type"],
                })

            # 连续多FAQ提问
            if len(faqs) >= 2:
                faq_topics = "、".join(f["question_type"] for f in faqs[:3])
                scenarios.append({
                    "name": "连续提问型",
                    "persona": f"你是接到{self.config.get('role', '客服')}电话的人，对很多事不清楚",
                    "behavior": f"你会连续问多个问题：{faq_topics}。每次只问一个，等回答后再问下一个",
                })

        return scenarios

    def _from_end_conditions(self) -> list[dict]:
        """从结束条件生成触发场景"""
        scenarios = []

        for cond in self.config.get("end_conditions", []):
            scenarios.append({
                "name": f"结束触发-{cond[:10]}",
                "persona": f"你是接到{self.config.get('role', '客服')}电话的人",
                "behavior": f"你在对话进行2-3轮后表示：{cond}",
                "target_end": cond,
            })

        return scenarios

    def _stress_scenarios(self) -> list[dict]:
        """通用压力测试场景"""
        role = self.config.get("role", "客服")
        return [
            {
                "name": "跑题型",
                "persona": f"你是接到{role}电话的人",
                "behavior": "你会反复问与任务无关的问题（天气、其他业务、个人问题），不容易被拉回主题",
            },
            {
                "name": "急躁型",
                "persona": f"你是接到{role}电话的人，正在忙",
                "behavior": "你很急，说话简短，催对方快点说完，不耐烦听长解释",
            },
        ]

    def generate_with_llm_enhancement(self) -> list[dict]:
        """用LLM增强场景的自然度"""
        base_scenarios = self.generate_all()

        # 用LLM为每个场景生成更自然的行为描述
        enhanced = []
        for s in base_scenarios:
            prompt = f"""请为以下用户画像生成一个更自然、更具体的行为描述（1-2句话，口语化）：
角色：{s['persona']}
原始行为：{s['behavior']}
只输出改写后的行为描述，不要其他内容。"""

            try:
                better_behavior = self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    max_tokens=512,
                    temperature=0.7,
                )
                s["behavior"] = better_behavior
            except Exception:
                pass  # 保持原始描述
            enhanced.append(s)

        return enhanced

    def describe(self) -> str:
        """输出场景概览"""
        scenarios = self.generate_all()
        lines = [f"自动生成的评测场景（共{len(scenarios)}个）："]
        for i, s in enumerate(scenarios, 1):
            lines.append(f"  {i}. [{s['name']}] {s['behavior'][:40]}")
        return "\n".join(lines)
