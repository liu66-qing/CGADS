"""Markdown/JSON reports for gold-standard calibration cases."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.calibration.audit import audit_cases, compute_raw_weighted_score
from src.checkers.severity_rules import get_rule


DIMENSION_LABELS = {
    "task_completion": "任务完成度",
    "flow_state_adherence": "流程状态遵循",
    "constraint_compliance": "约束遵循",
    "branch_handling": "分支处理",
    "context_consistency": "上下文一致性",
    "communication_experience": "沟通体验",
}

STATUS_LABELS = {
    "PASS": "正常通过",
    "CAPPED_P1": "P1封顶",
    "FAIL_P0": "P0失败",
}


def build_dataset_summary(cases: list[dict[str, Any]], strict30: bool = True) -> dict[str, Any]:
    audit = audit_cases(cases, strict30=strict30)
    status_counter = Counter(c["human_annotation"]["pass_status"] for c in cases)
    task_counter = Counter(c["task_id"] for c in cases)
    persona_counter = Counter(c["persona"] for c in cases)
    boundary_counter = Counter(
        c["human_annotation"].get("boundary_flag")
        for c in cases
        if c["human_annotation"].get("boundary_flag") is not None
    )
    p0_counter = Counter(
        v["rule_id"]
        for c in cases
        for v in c["human_annotation"].get("p0_violations", [])
    )
    p1_counter = Counter(
        v["rule_id"]
        for c in cases
        for v in c["human_annotation"].get("p1_violations", [])
    )

    score_by_status: dict[str, list[float]] = defaultdict(list)
    for case in cases:
        ann = case["human_annotation"]
        score_by_status[ann["pass_status"]].append(float(ann["total_score"]))

    return {
        "audit_passed": audit.passed,
        "audit_issues": [issue.__dict__ for issue in audit.issues],
        "total_cases": len(cases),
        "status_distribution": dict(status_counter),
        "task_distribution": dict(task_counter),
        "persona_distribution": dict(persona_counter),
        "boundary_distribution": dict(boundary_counter),
        "p0_rule_distribution": dict(p0_counter),
        "p1_rule_distribution": dict(p1_counter),
        "score_by_status": {
            status: {
                "count": len(scores),
                "min": min(scores),
                "max": max(scores),
                "avg": round(sum(scores) / len(scores), 2),
            }
            for status, scores in score_by_status.items()
        },
    }


def build_dataset_markdown(cases: list[dict[str, Any]], strict30: bool = True) -> str:
    summary = build_dataset_summary(cases, strict30=strict30)
    lines: list[str] = [
        "# 金标校准集证据链报告",
        "",
        "## 总体结论",
        "",
        f"- 审计状态：{'通过' if summary['audit_passed'] else '未通过'}",
        f"- 样本数：{summary['total_cases']}",
    ]

    lines.extend(_counter_lines("判定分布", summary["status_distribution"], STATUS_LABELS))
    lines.extend(_counter_lines("任务分布", summary["task_distribution"]))
    lines.extend(_counter_lines("用户画像分布", summary["persona_distribution"]))
    lines.extend(_counter_lines("边界样本分布", summary["boundary_distribution"]))
    lines.extend(_counter_lines("P0规则覆盖", summary["p0_rule_distribution"]))
    lines.extend(_counter_lines("P1规则覆盖", summary["p1_rule_distribution"]))

    lines.append("## 分数概览")
    lines.append("")
    lines.append("| 判定 | 数量 | 最低分 | 最高分 | 平均分 |")
    lines.append("|---|---:|---:|---:|---:|")
    for status, item in sorted(summary["score_by_status"].items()):
        lines.append(
            f"| {status} | {item['count']} | {item['min']:g} | {item['max']:g} | {item['avg']:g} |"
        )
    lines.append("")

    if summary["audit_issues"]:
        lines.append("## 审计问题")
        lines.append("")
        for issue in summary["audit_issues"]:
            lines.append(f"- `{issue['case_id']}` {issue['message']}")
        lines.append("")

    lines.append("## 样本详情")
    lines.append("")
    for case in cases:
        lines.extend(build_case_markdown(case, heading_level=3))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_case_markdown(case: dict[str, Any], heading_level: int = 2) -> list[str]:
    ann = case["human_annotation"]
    raw_score = compute_raw_weighted_score(ann["dimension_scores"])
    heading = "#" * heading_level
    lines = [
        f"{heading} {case['case_id']} | {case['task_id']} | {ann['pass_status']}",
        "",
        f"- 用户画像：`{case['persona']}`",
        f"- 场景：{case['scenario_description']}",
        f"- 总分：{ann['total_score']}，原始加权分：{raw_score:g}",
        f"- 边界标记：`{ann.get('boundary_flag')}`",
        f"- 对抗特征：{', '.join(case.get('adversarial_traits', [])) or '无'}",
        "",
        "维度分：",
    ]
    for key, label in DIMENSION_LABELS.items():
        lines.append(f"- {label} `{key}`：{ann['dimension_scores'][key]}/5")

    if ann.get("p0_violations"):
        lines.extend(["", "P0证据："])
        lines.extend(_violation_lines(ann["p0_violations"]))
    if ann.get("p1_violations"):
        lines.extend(["", "P1证据："])
        lines.extend(_violation_lines(ann["p1_violations"]))

    lines.extend(["", "关键失败轮次："])
    if ann.get("failed_turns"):
        lines.append("- " + ", ".join(f"Turn {t}" for t in ann["failed_turns"]))
    else:
        lines.append("- 无")

    lines.extend(["", "修复建议："])
    if ann.get("suggestions"):
        for suggestion in ann["suggestions"]:
            lines.append(f"- {suggestion}")
    else:
        lines.append("- 无")

    lines.extend(["", "状态轨迹摘录："])
    for item in case.get("state_trace_expected", []):
        slots = json.dumps(item.get("slots", {}), ensure_ascii=False, separators=(",", ":"))
        lines.append(f"- Turn {item['turn']} -> `{item['state']}` {slots}")

    lines.extend(["", "覆盖目标："])
    for target in case.get("coverage_targets", []):
        lines.append(f"- `{target}`")

    if case.get("annotator_notes"):
        lines.extend(["", f"标注备注：{case['annotator_notes']}"])

    return lines


def write_gold_report(
    cases: list[dict[str, Any]],
    output_dir: str | Path,
    strict30: bool = True,
    prefix: str = "calibration_gold_report",
) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary = build_dataset_summary(cases, strict30=strict30)
    markdown = build_dataset_markdown(cases, strict30=strict30)

    markdown_path = out / f"{prefix}.md"
    summary_path = out / f"{prefix}.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"markdown": str(markdown_path), "summary": str(summary_path)}


def _counter_lines(title: str, counter: dict[str, int], labels: dict[str, str] | None = None) -> list[str]:
    lines = [f"## {title}", ""]
    if not counter:
        lines.extend(["- 无", ""])
        return lines
    for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        label = labels.get(key, key) if labels else key
        lines.append(f"- `{key}` {label}：{count}")
    lines.append("")
    return lines


def _violation_lines(violations: list[dict[str, Any]]) -> list[str]:
    lines = []
    for violation in violations:
        rule = get_rule(violation["rule_id"])
        title = f" {rule.title}" if rule else ""
        lines.append(
            f"- `{violation['rule_id']}`{title} Turn {violation['evidence_turn']}："
            f"{violation['evidence_text']}；原因：{violation['rationale']}"
        )
    return lines
