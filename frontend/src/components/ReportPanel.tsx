import { ChevronDown, Copy, Download, RefreshCw } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { getReportDownloadUrl, getReportJson, getReportMarkdown } from '../api'
import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

export function ReportPanel() {
  const open = useEvaluationStore((s) => s.reportOpen)
  const setOpen = useEvaluationStore((s) => s.setReportOpen)
  const score = useEvaluationStore((s) => s.score)
  const coverage = useEvaluationStore((s) => s.coverage)
  const backendMarkdown = useEvaluationStore((s) => s.reportMarkdown)
  const setReportMarkdown = useEvaluationStore((s) => s.setReportMarkdown)
  const setReportJson = useEvaluationStore((s) => s.setReportJson)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)

  const fallbackMarkdown = `# 橙脉 CGADS 完整评估报告

## 总览
- 综合得分：${score.totalScore || '--'}/100
- 评测判定：${score.passStatus}
- 覆盖率：状态 ${coverage.state}% / 边 ${coverage.edge}% / 风险 ${coverage.risk}% / 要求 ${coverage.requirement}%

## 场景摘要
${score.scenarios.map((s) => `- ${s.id}: ${s.turns} 轮，${s.score} 分，P0 ${s.p0} / P1 ${s.p1}`).join('\n') || '- 暂无场景结果'}

## 优化建议
${(score.suggestions.length ? score.suggestions : ['等待 pipeline_complete 生成正式建议']).map((s) => `- ${s}`).join('\n')}
`
  const markdown = backendMarkdown || fallbackMarkdown

  const copyText = async () => {
    if (!backendMarkdown) {
      try {
        const report = await getReportMarkdown()
        const text = report.markdown ?? ''
        setReportMarkdown(text)
        await navigator.clipboard.writeText(text || fallbackMarkdown)
        setBackendStatus('ok')
        return
      } catch {
        setBackendStatus('offline')
      }
    }
    await navigator.clipboard.writeText(markdown)
  }

  const refreshReport = async () => {
    try {
      const [report, reportJson] = await Promise.all([getReportMarkdown(), getReportJson()])
      setReportMarkdown(report.markdown ?? '')
      setReportJson(reportJson)
      setBackendStatus('ok')
    } catch {
      setBackendStatus('offline')
    }
  }

  const downloadReport = (format: 'markdown' | 'json') => {
    window.location.href = getReportDownloadUrl(format)
  }

  return (
    <section className="panel report-panel final-report-panel">
      <button className="final-report-head" onClick={() => setOpen(!open)}>
        <div className="module-title">
          <ThemeIcon name="report" size={38} />
          <div>
            <h2>完整评估报告</h2>
            <p>赛题最终交付物 · 评分、覆盖、违规、建议一页汇总</p>
          </div>
        </div>
        <div className="report-head-actions">
          <span>{open ? '收起报告' : '展开报告'}</span>
          <ChevronDown className={open ? 'chevron open' : 'chevron'} size={20} />
        </div>
      </button>

      <div className="report-delivery-bar">
        <button onClick={copyText}><Copy size={16} /> 复制文本</button>
        <button onClick={refreshReport}><RefreshCw size={16} /> 刷新报告</button>
        <button onClick={() => downloadReport('markdown')}><Download size={16} /> 下载 Markdown</button>
        <button onClick={() => downloadReport('json')}><Download size={16} /> 下载 JSON</button>
      </div>

      {open && (
        <div className="report-body prominent-report-body">
          <div className="report-markdown"><ReactMarkdown>{markdown}</ReactMarkdown></div>
        </div>
      )}
    </section>
  )
}
