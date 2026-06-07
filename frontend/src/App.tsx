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
      <nav className="topbar">
        <h1>外呼对话评测系统</h1>
        <span className="topbar-sub">对对队 · 多轮指令遵循自动评测</span>
        <span className={`backend-chip ${backendStatus}`}>{backendText}</span>
      </nav>

      <div className="workspace">
        {/* 顶部：输入 + 进度 */}
        <InputPanel />
        <PipelineTracker />

        {/* 核心结论区 — 首屏 */}
        <ScoreCard />

        {/* 证据 + 对话 */}
        <EvidenceTimeline />
        <DialogueViewer />

        {/* 完整报告 */}
        <ReportPanel />

        {/* 辅助分析 — 折叠 */}
        <details className="auxiliary-section">
          <summary>状态机可视化（辅助分析）</summary>
          <StateMachineGraph />
        </details>
        <HistoryStrip />
      </div>
    </main>
  )
}
