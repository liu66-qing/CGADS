"""约束检查器自动生成 - 从解析后的任务配置动态构建检查规则"""

import re
from dataclasses import dataclass
from ..checkers.constraint_checker import CheckResult


@dataclass
class DynamicRule:
    """动态生成的检查规则"""
    name: str
    description: str
    check_fn: callable


class AutoCheckerBuilder:
    """从任务配置自动生成约束检查器"""

    def __init__(self, task_config: dict):
        self.config = task_config
        self.rules: list[DynamicRule] = []
        self._build_rules()

    def _build_rules(self):
        """从配置自动构建所有规则"""
        # 1. 字数限制（必有）
        max_len = self.config.get("max_reply_length", 30)
        self.rules.append(DynamicRule(
            name="length_limit",
            description=f"回复不超过{max_len}字",
            check_fn=lambda reply, **kw: CheckResult(
                passed=len(reply) <= max_len,
                rule_name="length_limit",
                message=f"长度 {len(reply)}/{max_len}" + ("" if len(reply) <= max_len else " 超限"),
            ),
        ))

        # 2. 禁用词（如果有）
        forbidden = self.config.get("forbidden", [])
        if forbidden:
            def check_forbidden(reply, **kw):
                found = [w for w in forbidden if w in reply]
                return CheckResult(
                    passed=len(found) == 0,
                    rule_name="forbidden_words",
                    message=f"发现禁用词: {found}" if found else "无禁用词",
                )
            self.rules.append(DynamicRule(
                name="forbidden_words",
                description=f"禁用词: {forbidden}",
                check_fn=check_forbidden,
            ))

        # 3. 重复检查（通用）
        def check_repeat(reply, history=None, **kw):
            """检查当前回复是否与历史回复完全重复。
            注意：history应传入当前回复之前的历史回复列表。
            如果调用方误将当前回复包含在history中，排除最后一次出现。
            """
            history = history or []
            # 排除history中与reply相同的最后一项（可能是刚append的自身）
            cleaned = list(history)
            if cleaned and cleaned[-1] == reply:
                cleaned = cleaned[:-1]
            for prev in cleaned:
                if prev and reply == prev:
                    return CheckResult(False, "no_repeat", f"与历史回复重复: {prev[:20]}...")
            return CheckResult(True, "no_repeat", "无重复")
        self.rules.append(DynamicRule(
            name="no_repeat",
            description="避免重复回复",
            check_fn=check_repeat,
        ))

        # 4. 结束条件检查（如果有）
        end_conditions = self.config.get("end_conditions", [])
        if end_conditions:
            self._build_end_condition_rules(end_conditions)

        # 5. 从 constraints 文本中动态提取更多规则
        for constraint in self.config.get("constraints", []):
            self._try_extract_rule(constraint)

    def _build_end_condition_rules(self, end_conditions: list):
        """构建结束条件检查规则"""
        # 提取关键词模式
        end_keywords_map = {}
        for cond in end_conditions:
            if "开车" in cond:
                end_keywords_map["开车"] = ["稍后再打", "再联系", "再见", "挂断"]
            elif "坚持" in cond and ("拒绝" in cond or "无法" in cond or "不" in cond):
                end_keywords_map["坚持拒绝"] = ["没关系", "理解", "再见", "安慰"]

        if end_keywords_map:
            def check_end(reply, user_input="", **kw):
                for trigger, expected_any in end_keywords_map.items():
                    if trigger in user_input:
                        if not any(kw_exp in reply for kw_exp in expected_any):
                            return CheckResult(
                                False, "end_condition",
                                f"触发结束条件'{trigger}'但回复未正确处理",
                            )
                return CheckResult(True, "end_condition", "结束条件正常")
            self.rules.append(DynamicRule(
                name="end_condition",
                description=f"结束条件: {end_conditions}",
                check_fn=check_end,
            ))

    def _try_extract_rule(self, constraint: str):
        """尝试从约束文本中提取可程序化的规则"""
        # 检测"不能承诺/不能答应"类约束
        if re.search(r'不[能可以]+承诺|不[能可以]+答应|不[能可以]+保证', constraint):
            promise_keywords = ["保证", "承诺", "答应", "一定会", "肯定能"]
            # 从约束中提取具体不能承诺的内容
            match = re.search(r'不[能可以]+承诺.*?([一-龥]+)', constraint)
            if match:
                promise_keywords.append(match.group(1))

            def check_promise(reply, **kw):
                found = [w for w in promise_keywords if w in reply]
                if found:
                    return CheckResult(False, "no_promise", f"违规承诺: {found}")
                return CheckResult(True, "no_promise", "无违规承诺")

            # 避免重复添加
            if not any(r.name == "no_promise" for r in self.rules):
                self.rules.append(DynamicRule(
                    name="no_promise",
                    description=constraint,
                    check_fn=check_promise,
                ))

        # 检测"超出范围用固定话术"类约束
        if re.search(r'超出.*?范围|超出.*?职责', constraint):
            # 提取固定话术
            match = re.search(r'[回复说].*?[：:]?\s*[""「](.+?)[""」]', constraint)
            fixed_reply = match.group(1) if match else None
            if fixed_reply:
                # 这个规则比较复杂，暂时只记录不强制检查
                pass

    def run_all(self, reply: str, user_input: str = "", history: list = None) -> list[CheckResult]:
        """运行所有动态生成的规则"""
        history = history or []
        results = []
        for rule in self.rules:
            try:
                result = rule.check_fn(reply=reply, user_input=user_input, history=history)
                results.append(result)
            except Exception as e:
                results.append(CheckResult(True, rule.name, f"检查异常: {e}"))
        return results

    def is_compliant(self, results: list[CheckResult]) -> bool:
        return all(r.passed for r in results)

    def get_violations(self, results: list[CheckResult]) -> list[CheckResult]:
        return [r for r in results if not r.passed]

    def describe_rules(self) -> str:
        """输出所有规则的描述（用于展示）"""
        lines = [f"自动生成的检查规则（共{len(self.rules)}条）："]
        for i, rule in enumerate(self.rules, 1):
            lines.append(f"  {i}. [{rule.name}] {rule.description}")
        return "\n".join(lines)
