import { Bell, Circle, Users } from 'lucide-react'
import { InputPanel } from './components/InputPanel'
import { PipelineTracker } from './components/PipelineTracker'
import { StepDetailPanel } from './components/StepDetailPanel'
import { StateMachineGraph } from './components/StateMachineGraph'
import { ScoreCard } from './components/ScoreCard'
import { EvidenceTimeline } from './components/EvidenceTimeline'
import { ReportPanel } from './components/ReportPanel'
import { useEvaluationStore } from './store/evaluationStore'

export function App() {
  const running = useEvaluationStore((s) => s.running)
  return (
    <main>
      <nav className="topbar">
        <div className="brand-mark">橙</div>
        <div>
          <h1>橙脉 CGADS</h1>
          <p>外呼指令状态机试炼场 · HACKATHON</p>
        </div>
        <div className="status-pill">
          <span><Circle size={10} fill="#667085" /> idle</span>
          <span className={running ? 'active' : ''}><Circle size={10} fill="#FF8A00" /> running</span>
          <span><Circle size={10} fill="#667085" /> done</span>
        </div>
        <Bell className="nav-icon" size={20} />
        <div className="team"><Users size={20} /> 产品小队</div>
      </nav>

      <div className="workspace">
        <InputPanel />
        <PipelineTracker />
        <StepDetailPanel />
        <div className="main-grid">
          <StateMachineGraph />
          <ScoreCard />
        </div>
        <EvidenceTimeline />
        <ReportPanel />
      </div>
    </main>
  )
}
