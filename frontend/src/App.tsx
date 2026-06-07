import { useEffect } from 'react'
import { getEvaluations, getHealth, getStateNames } from './api'
import { DialogueViewer } from './components/DialogueViewer'
import { EvidenceTimeline } from './components/EvidenceTimeline'
import { HistoryStrip } from './components/HistoryStrip'
import { InputPanel } from './components/InputPanel'
import { PipelineTracker } from './components/PipelineTracker'
import { ReportPanel } from './components/ReportPanel'
import { ScoreCard } from './components/ScoreCard'
import { StateMachineGraph } from './components/StateMachineGraph'
import { ThemeIcon } from './components/ThemeIcon'
import { useEvaluationStore } from './store/evaluationStore'

export function App() {
  const backendStatus = useEvaluationStore((s) => s.backendStatus)
  const setMappings = useEvaluationStore((s) => s.setMappings)
  const setEvaluations = useEvaluationStore((s) => s.setEvaluations)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)

  useEffect(() => {
    let alive = true
    Promise.all([getHealth(), getStateNames(), getEvaluations()])
      .then(([, mappings, evaluations]) => {
        if (!alive) return
        setMappings(mappings.state_names ?? {}, mappings.dimension_labels ?? {})
        setEvaluations(evaluations.evaluations ?? [])
        setBackendStatus('ok')
      })
      .catch(() => {
        if (alive) setBackendStatus('offline')
      })

    return () => {
      alive = false
    }
  }, [setBackendStatus, setEvaluations, setMappings])

  const backendText =
    backendStatus === 'ok' ? 'API 已连接' : backendStatus === 'offline' ? '离线预览' : '连接中'

  return (
    <main>
      <nav className="topbar no-logo">
        <div className="brand-text">
          <h1>外呼对话评测系统</h1>
          <p>对对队 · 多轮指令遵循自动评测</p>
        </div>
        <span className={`backend-chip ${backendStatus}`}>{backendText}</span>
        <div className="team"><ThemeIcon name="team" size={28} /> 对对队</div>
      </nav>

      <div className="workspace">
        <InputPanel />
        <details className="pipeline-collapsible" open>
          <summary>评测进度</summary>
          <PipelineTracker />
        </details>
        <div className="main-grid results-primary">
          <ScoreCard />
        </div>
        <EvidenceTimeline />
        <DialogueViewer />
        <ReportPanel />
        <details className="state-machine-collapsible">
          <summary>状态机可视化（辅助分析）</summary>
          <StateMachineGraph />
        </details>
        <HistoryStrip />
      </div>
    </main>
  )
}
