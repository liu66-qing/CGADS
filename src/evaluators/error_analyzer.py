"""错误分析器 - 自动归类错误类型、统计分布、输出改进建议"""

from dataclasses import dataclass, asdict
from collections import Counter


# 错误类型定义
ERROR_TYPES = {
    "length_violation": "字数超限",
    "forbidden_word": "使用禁用词",
    "repeat_reply": "重复回复",
    "end_condition_miss": "未正确处理结束条件",
    "promise_violation": "违规承诺",
    "low_cohesion": "对话不连贯",
    "knowledge_hallucination": "知识幻觉/编造信息",
    "flow_skip": "跳过流程步骤",
    "flow_wrong_branch": "走错分支",
    "task_incomplete": "任务未完成",
    "unnatural_tone": "语气不自然",
}


@dataclass
class ErrorInstance:
    """单个错误实例"""
    error_type: str
    turn: int
    user_input: str
    agent_reply: str
    detail: str
    severity: str  # "high" / "medium" / "low"


class ErrorAnalyzer:
    def __init__(self):
        self.errors: list[ErrorInstance] = []

    def analyze_from_results(self, dialogue_result: dict, eval_result: dict = None) -> list[ErrorInstance]:
        """从对话结果和评测结果中提取错误"""
        self.errors = []

        # 1. 从硬约束检查中提取错误
        for turn_data in dialogue_result.get("turns", []):
            if not turn_data.get("compliant", True):
                violations = turn_data.get("violations", [])
                for v in violations:
                    self.errors.append(ErrorInstance(
                        error_type=self._map_rule_to_error(v.get("rule", "")),
                        turn=turn_data["turn"],
                        user_input=turn_data.get("user", ""),
                        agent_reply=turn_data.get("agent", ""),
                        detail=v.get("msg", ""),
                        severity="high",
                    ))

        # 2. 从 LLM 裁判评分中提取错误（低分项）
        if eval_result:
            for turn_score in eval_result.get("turn_scores", []):
                if turn_score.get("cohesion", 5) <= 2:
                    self.errors.append(ErrorInstance(
                        error_type="low_cohesion",
                        turn=turn_score["turn"],
                        user_input=turn_score.get("user_input", ""),
                        agent_reply=turn_score.get("agent_reply", ""),
                        detail=turn_score.get("comment", ""),
                        severity="medium",
                    ))
                if turn_score.get("knowledge", 5) <= 2:
                    self.errors.append(ErrorInstance(
                        error_type="knowledge_hallucination",
                        turn=turn_score["turn"],
                        user_input=turn_score.get("user_input", ""),
                        agent_reply=turn_score.get("agent_reply", ""),
                        detail=turn_score.get("comment", ""),
                        severity="high",
                    ))
                if turn_score.get("compliance", 5) <= 2:
                    self.errors.append(ErrorInstance(
                        error_type="flow_wrong_branch",
                        turn=turn_score["turn"],
                        user_input=turn_score.get("user_input", ""),
                        agent_reply=turn_score.get("agent_reply", ""),
                        detail=turn_score.get("comment", ""),
                        severity="high",
                    ))
                if turn_score.get("progress", 5) <= 2:
                    self.errors.append(ErrorInstance(
                        error_type="flow_skip",
                        turn=turn_score["turn"],
                        user_input=turn_score.get("user_input", ""),
                        agent_reply=turn_score.get("agent_reply", ""),
                        detail=turn_score.get("comment", ""),
                        severity="medium",
                    ))

            # 整体评测错误
            ds = eval_result.get("dialogue_score", {})
            if not ds.get("task_completed", True):
                self.errors.append(ErrorInstance(
                    error_type="task_incomplete",
                    turn=0,
                    user_input="",
                    agent_reply="",
                    detail="整通电话未完成任务目标",
                    severity="high",
                ))

        return self.errors

    def _map_rule_to_error(self, rule_name: str) -> str:
        mapping = {
            "length_limit": "length_violation",
            "forbidden_words": "forbidden_word",
            "no_repeat": "repeat_reply",
            "end_condition": "end_condition_miss",
            "no_promise": "promise_violation",
        }
        return mapping.get(rule_name, rule_name)

    def get_summary(self) -> dict:
        """生成错误统计摘要"""
        if not self.errors:
            return {"total_errors": 0, "distribution": {}, "severity_dist": {}, "suggestions": []}

        type_counter = Counter(e.error_type for e in self.errors)
        severity_counter = Counter(e.severity for e in self.errors)

        # 生成改进建议
        suggestions = []
        for error_type, count in type_counter.most_common():
            suggestions.append(self._get_suggestion(error_type, count))

        return {
            "total_errors": len(self.errors),
            "distribution": {ERROR_TYPES.get(k, k): v for k, v in type_counter.items()},
            "severity_dist": dict(severity_counter),
            "top_errors": [
                {"type": ERROR_TYPES.get(t, t), "count": c}
                for t, c in type_counter.most_common(5)
            ],
            "suggestions": suggestions,
            "errors": [asdict(e) for e in self.errors],
        }

    def _get_suggestion(self, error_type: str, count: int) -> str:
        suggestion_map = {
            "length_violation": f"字数超限出现{count}次 → 在prompt中强调字数限制，或在生成后截断+重写",
            "forbidden_word": f"禁用词出现{count}次 → 在prompt中加粗禁用词列表，或增加后处理过滤",
            "repeat_reply": f"重复回复出现{count}次 → 在prompt中注入历史回复摘要，要求换种表达",
            "end_condition_miss": f"结束条件处理错误{count}次 → 增加结束条件的显式检测逻辑",
            "promise_violation": f"违规承诺出现{count}次 → 在约束中明确列出不可承诺的内容",
            "low_cohesion": f"对话不连贯出现{count}次 → 改进状态跟踪，确保回复接住用户上文",
            "knowledge_hallucination": f"知识幻觉出现{count}次 → 限制模型只能使用FAQ中的信息回答",
            "flow_skip": f"跳过流程出现{count}次 → 增强流程状态跟踪，明确当前步骤",
            "flow_wrong_branch": f"走错分支出现{count}次 → 改进意图识别，增加分支条件判断",
            "task_incomplete": f"任务未完成出现{count}次 → 检查是否过早结束通话",
            "unnatural_tone": f"语气不自然出现{count}次 → 调整prompt中的语气要求，增加口语化示例",
        }
        return suggestion_map.get(error_type, f"{error_type}出现{count}次")


def format_report(summary: dict, scenario_name: str = "") -> str:
    """格式化输出评测报告"""
    lines = []
    lines.append(f"{'='*50}")
    lines.append(f"错误分析报告" + (f" - {scenario_name}" if scenario_name else ""))
    lines.append(f"{'='*50}")
    lines.append(f"")
    lines.append(f"总错误数: {summary['total_errors']}")
    lines.append(f"严重程度分布: {summary.get('severity_dist', {})}")
    lines.append(f"")

    if summary.get("top_errors"):
        lines.append("错误类型分布:")
        for item in summary["top_errors"]:
            lines.append(f"  - {item['type']}: {item['count']}次")
        lines.append("")

    if summary.get("suggestions"):
        lines.append("改进建议:")
        for i, s in enumerate(summary["suggestions"], 1):
            lines.append(f"  {i}. {s}")
        lines.append("")

    return "\n".join(lines)
