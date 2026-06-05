"""Plotly 图表生成：雷达图、覆盖率环、对比曲线。"""

from __future__ import annotations
from typing import Any

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


def radar_chart_html(dimension_scores: dict[str, int | float], title: str = "评测维度雷达图") -> str:
    """6维度雷达图，返回HTML字符串。"""
    if not HAS_PLOTLY:
        return _fallback_radar_markdown(dimension_scores)

    labels_map = {
        "task_completion": "任务完成",
        "flow_state_adherence": "流程遵循",
        "constraint_compliance": "约束合规",
        "branch_handling": "分支处理",
        "context_consistency": "上下文一致",
        "communication_experience": "沟通体验",
    }
    labels = [labels_map.get(k, k) for k in dimension_scores.keys()]
    values = list(dimension_scores.values())
    # 闭合
    labels.append(labels[0])
    values.append(values[0])

    fig = go.Figure(data=go.Scatterpolar(
        r=values,
        theta=labels,
        fill='toself',
        line=dict(color='#1f77b4'),
        fillcolor='rgba(31,119,180,0.2)',
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 5])),
        showlegend=False,
        title=title,
        height=400,
        margin=dict(l=60, r=60, t=60, b=40),
    )
    return fig.to_html(include_plotlyjs="cdn", full_html=False)


def coverage_bars_html(coverage_report: dict[str, Any]) -> str:
    """4类覆盖率柱状图。"""
    if not HAS_PLOTLY:
        return _fallback_coverage_markdown(coverage_report)

    categories = ["状态", "转移边", "风险规则", "业务需求"]
    keys = ["state_coverage", "transition_coverage", "risk_coverage", "requirement_coverage"]
    ratios = [coverage_report.get(k, {}).get("ratio", 0) * 100 for k in keys]

    colors = ['#2196F3' if r >= 80 else '#FF9800' if r >= 60 else '#F44336' for r in ratios]

    fig = go.Figure(data=go.Bar(
        x=categories,
        y=ratios,
        marker_color=colors,
        text=[f"{r:.0f}%" for r in ratios],
        textposition='outside',
    ))
    fig.update_layout(
        title="CGADS 四类覆盖率",
        yaxis=dict(title="覆盖率 (%)", range=[0, 105]),
        height=350,
        margin=dict(l=50, r=30, t=50, b=40),
    )
    # 添加阈值线
    thresholds = [80, 60, 80, 70]
    for i, (cat, th) in enumerate(zip(categories, thresholds)):
        fig.add_shape(type="line", x0=i-0.4, x1=i+0.4, y0=th, y1=th,
                      line=dict(color="red", width=2, dash="dash"))

    return fig.to_html(include_plotlyjs="cdn", full_html=False)


def ablation_comparison_html(data: dict[str, Any]) -> str:
    """CGADS消融对比曲线。"""
    if not HAS_PLOTLY:
        return "<p>plotly未安装，无法显示图表</p>"

    methods = data.get("methods", ["Random", "Stratified", "CGADS"])
    coverage = data.get("coverage", [45, 55, 72])
    p0_rate = data.get("p0_discovery", [30, 40, 65])

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Coverage@8 (%)", x=methods, y=coverage, marker_color='#2196F3'))
    fig.add_trace(go.Bar(name="P0发现率 (%)", x=methods, y=p0_rate, marker_color='#F44336'))
    fig.update_layout(
        barmode='group',
        title="CGADS 消融实验对比",
        yaxis=dict(title="百分比 (%)", range=[0, 100]),
        height=400,
    )
    return fig.to_html(include_plotlyjs="cdn", full_html=False)


def _fallback_radar_markdown(scores: dict[str, int | float]) -> str:
    """无plotly时的文本降级。"""
    lines = ["### 评测维度得分\n"]
    for k, v in scores.items():
        bar = "█" * int(v) + "░" * (5 - int(v))
        lines.append(f"- {k}: {bar} ({v}/5)")
    return "\n".join(lines)


def _fallback_coverage_markdown(report: dict[str, Any]) -> str:
    """无plotly时的文本降级。"""
    lines = ["### 覆盖率统计\n"]
    for k in ["state_coverage", "transition_coverage", "risk_coverage", "requirement_coverage"]:
        r = report.get(k, {}).get("ratio", 0)
        lines.append(f"- {k}: {r:.1%}")
    return "\n".join(lines)
