import { ChevronDown, Copy, Download, RefreshCw } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getReportDownloadUrl, getReportJson, getReportMarkdown } from '../api'
import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

const fallbackMarkdown = '> 评测尚未完成。请先运行评测，报告将在完成后自动生成。'

export function ReportPanel() {
  const open = useEvaluationStore((s) => s.reportOpen)
  const setOpen = useEvaluationStore((s) => s.setReportOpen)
  const backendMarkdown = useEvaluationStore((s) => s.reportMarkdown)
  const setReportMarkdown = useEvaluationStore((s) => s.setReportMarkdown)
  const setReportJson = useEvaluationStore((s) => s.setReportJson)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)

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
            <p>评分、覆盖、违规和建议会在完成后汇总为最终交付物。</p>
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
          <div className="report-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
          </div>
        </div>
      )}
    </section>
  )
}
