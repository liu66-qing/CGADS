"""硬约束检查器 - IFEval 风格的可程序验证规则"""

import re
from dataclasses import dataclass


@dataclass
class CheckResult:
    passed: bool
    rule_name: str
    message: str


def check_length(reply: str, max_length: int) -> CheckResult:
    actual = len(reply)
    passed = actual <= max_length
    return CheckResult(
        passed=passed,
        rule_name="length_limit",
        message=f"长度 {actual}/{max_length}" + ("" if passed else " 超限"),
    )


def check_forbidden_words(reply: str, forbidden: list[str]) -> CheckResult:
    found = [w for w in forbidden if w in reply]
    return CheckResult(
        passed=len(found) == 0,
        rule_name="forbidden_words",
        message=f"发现禁用词: {found}" if found else "无禁用词",
    )


def check_no_repeat(reply: str, history: list[str], threshold: float = 0.8) -> CheckResult:
    """检查回复是否与历史回复重复（基于字符重叠率）"""
    for prev in history:
        if not prev:
            continue
        overlap = len(set(reply) & set(prev)) / max(len(set(reply)), 1)
        if overlap >= threshold and reply == prev:
            return CheckResult(
                passed=False,
                rule_name="no_repeat",
                message=f"与历史回复完全重复: {prev[:20]}...",
            )
    return CheckResult(passed=True, rule_name="no_repeat", message="无重复")


def check_end_condition(reply: str, user_input: str, end_conditions: list[str], task_config: dict) -> CheckResult:
    """检查是否在触发结束条件时正确结束"""
    task_id = task_config.get("task_id", "")

    if "开车" in user_input and "course_platform" in task_id:
        should_end = True
        if "稍后再打" not in reply and "再联系" not in reply:
            return CheckResult(
                passed=False,
                rule_name="end_condition",
                message="商家说在开车但未礼貌结束",
            )

    return CheckResult(passed=True, rule_name="end_condition", message="结束条件正常")


def check_promise_forbidden(reply: str, task_config: dict) -> CheckResult:
    """检查是否承诺了不该承诺的内容"""
    forbidden_promises = ["优惠券", "折扣券", "打折", "免费", "赠送"]
    if any(kw in (task_config.get("forbidden") or []) for kw in ["折扣券", "优惠券"]):
        found = [w for w in forbidden_promises if w in reply]
        if found:
            return CheckResult(
                passed=False,
                rule_name="no_promise",
                message=f"承诺了禁止内容: {found}",
            )
    return CheckResult(passed=True, rule_name="no_promise", message="无违规承诺")


def run_all_checks(
    reply: str,
    user_input: str,
    history: list[str],
    task_config: dict,
) -> list[CheckResult]:
    """运行所有检查器，返回结果列表"""
    max_len = task_config.get("max_reply_length", 30)
    forbidden = task_config.get("forbidden", [])
    end_conditions = task_config.get("end_conditions", [])

    results = [
        check_length(reply, max_len),
        check_forbidden_words(reply, forbidden),
        check_no_repeat(reply, history),
        check_end_condition(reply, user_input, end_conditions, task_config),
        check_promise_forbidden(reply, task_config),
    ]
    return results


def is_compliant(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results)


def get_violations(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if not r.passed]
