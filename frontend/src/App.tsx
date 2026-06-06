import { Circle } from 'lucide-react'
import { useEffect } from 'react'
import { getEvaluations, getHealth, getStateNames } from './api'
import { DialogueViewer } from './components/DialogueViewer'
import { EvidenceTimeline } from './components/EvidenceTimeline'
import { HeroBanner } from './components/HeroBanner'
import { HistoryStrip } from './components/HistoryStrip'
import { InputPanel } from './components/InputPanel'
import { PipelineTracker } from './components/PipelineTracker'
import { ReportPanel } from './components/ReportPanel'
import { ScoreCard } from './components/ScoreCard'
import { StateMachineGraph } from './components/StateMachineGraph'
import { StepDetailPanel } from './components/StepDetailPanel'
import { ThemeIcon } from './components/ThemeIcon'
import { useEvaluationStore } from './store/evaluationStore'

export function App() {
  const running = useEvaluationStore((s) => s.running)
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
          <h1>橙脉 CGADS</h1>
          <p>对对队 · 外呼任务对话模型评测</p>
        </div>
        <div className="status-pill">
          <span><Circle size={10} fill="#667085" /> idle</span>
          <span className={running ? 'active' : ''}><Circle size={10} fill="#FF8A00" /> running</span>
          <span><Circle size={10} fill="#667085" /> done</span>
        </div>
        <span className={`backend-chip ${backendStatus}`}>{backendText}</span>
        <ThemeIcon name="bell" size={30} />
        <div className="team"><ThemeIcon name="team" size={28} /> 对对队</div>
      </nav>

      <HeroBanner />

      <div className="workspace">
        <InputPanel />
        <PipelineTracker />
        <HistoryStrip />
        <StepDetailPanel />
        <div className="main-grid results-primary">
          <ScoreCard />
        </div>
        <details className="state-machine-collapsible" open>
          <summary>状态机可视化（点击折叠）</summary>
          <StateMachineGraph />
        </details>
        <EvidenceTimeline />
        <DialogueViewer />
        <ReportPanel />
      </div>
    </main>
  )
}
