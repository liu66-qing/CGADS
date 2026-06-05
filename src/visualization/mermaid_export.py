"""DSL → Mermaid 状态图导出。用于前端可视化。"""

from __future__ import annotations
from typing import Any

from ..dsl.schema import TaskDSL


def export_mermaid_statediagram(dsl: TaskDSL) -> str:
    """生成 Mermaid stateDiagram-v2 语法字符串。"""
    lines = ["stateDiagram-v2"]

    for state in dsl.states:
        # 状态描述
        desc = state.description[:20] if state.description else state.id
        lines.append(f"    {state.id} : {desc}")

        # Entry标记
        if state.entry:
            lines.append(f"    [*] --> {state.id}")

        # Terminal标记
        if state.terminal:
            lines.append(f"    {state.id} --> [*]")

        # 转移边
        for tr in state.transitions:
            label = tr.when.intent or ""
            if not label and tr.when.rule_keywords:
                label = tr.when.rule_keywords[0][:6]
            if not label and tr.when.slot_equals:
                label = list(tr.when.slot_equals.keys())[0][:10]
            lines.append(f"    {state.id} --> {tr.to} : {label}")

    return "\n".join(lines)


def export_mermaid_html(dsl: TaskDSL) -> str:
    """生成包含 Mermaid.js CDN 的完整 HTML 片段，可直接嵌入 gr.HTML。"""
    diagram = export_mermaid_statediagram(dsl)
    return f"""
<div class="mermaid" style="text-align:center;">
{diagram}
</div>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
</script>
"""


def dsl_summary_table(dsl: TaskDSL) -> str:
    """生成DSL摘要的Markdown表格。"""
    p0_count = sum(1 for r in dsl.severity_rules if r.level == "P0")
    p1_count = sum(1 for r in dsl.severity_rules if r.level == "P1")
    return f"""| 指标 | 值 |
|------|-----|
| 任务ID | `{dsl.task_id}` |
| 角色 | {dsl.role} |
| 目标 | {dsl.objective[:40]}... |
| 状态数 | **{len(dsl.states)}** |
| 转移边数 | **{len(dsl.all_edges)}** |
| P0规则 | **{p0_count}** |
| P1规则 | **{p1_count}** |
| 原子需求 | **{len(dsl.atomic_requirements)}** |
| 槽位数 | {len(dsl.slots)} |
| FAQ数 | {len(dsl.faq)} |
| 字数限制 | {dsl.global_constraints.max_reply_chars}字 |
"""


def coverage_targets_summary(dsl: TaskDSL) -> str:
    """覆盖目标总数统计。"""
    p0p1 = [r for r in dsl.severity_rules if r.level in ("P0", "P1")]
    return f"""### 评测空间 D = ⟨S, E, R, Q⟩

| 类型 | 数量 | 说明 |
|------|------|------|
| S (状态) | {len(dsl.states)} | 对话阶段节点 |
| E (边) | {len(dsl.all_edges)} | 状态转移路径 |
| R (风险) | {len(p0p1)} | P0/P1 合规规则 |
| Q (需求) | {len(dsl.atomic_requirements)} | 原子业务要求 |
| **总评测目标** | **{len(dsl.states) + len(dsl.all_edges) + len(p0p1) + len(dsl.atomic_requirements)}** | |
"""
