import { ChevronDown, Download, FileDown } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { useEvaluationStore } from '../store/evaluationStore'

export function ReportPanel() {
  const open = useEvaluationStore((s) => s.reportOpen)
  const setOpen = useEvaluationStore((s) => s.setReportOpen)
  const score = useEvaluationStore((s) => s.score)
  const coverage = useEvaluationStore((s) => s.coverage)

  const markdown = `# 橙脉 CGADS 评测报告

## 总览
- 综合得分：${score.totalScore || '--'}/100
- 判定：${score.passStatus}
- 覆盖率：状态 ${coverage.state}% / 边 ${coverage.edge}% / 风险 ${coverage.risk}% / 要求 ${coverage.requirement}%

## 场景摘要
${score.scenarios.map((s) => `- ${s.id}: ${s.turns} 轮，${s.score} 分，P0 ${s.p0} / P1 ${s.p1}`).join('\n') || '- 暂无场景结果'}

## 优化建议
${(score.suggestions.length ? score.suggestions : ['等待 pipeline_complete 生成建议']).map((s) => `- ${s}`).join('\n')}
`

  const exportMarkdown = () => {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'orange-pulse-cgads-report.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="panel report-panel">
      <button className="panel-title" onClick={() => setOpen(!open)}>
        <span className="title-icon"><FileDown size={18} /></span>
        <span>完整评估报告</span>
        <span className="muted">完成后展开 · 包含评分详情 / 问题索引 / 改进建议</span>
        <ChevronDown className={open ? 'chevron open' : 'chevron'} size={18} />
      </button>
      {open && (
        <div className="report-body">
          <ReactMarkdown>{markdown}</ReactMarkdown>
          <button className="export-button" onClick={exportMarkdown}><Download size={16} /> 导出 Markdown</button>
        </div>
      )}
    </section>
  )
}
