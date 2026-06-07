import { CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'

const stageLabels: Record<string, string> = {
  parsing: '指令解析',
  dsl_compile: 'DSL编译',
  scenario_gen: '场景生成',
  dialogue: '对话执行',
  scoring: '评分汇总',
}

const formatDuration = (s: number) => {
  if (s < 0.1) return '<0.1s'
  if (s < 60) return `${s.toFixed(1)}s`
  return `${Math.floor(s / 60)}m${Math.round(s % 60)}s`
}

export function PipelineTracker() {
  const running = useEvaluationStore((s) => s.running)
  const pipeline = useEvaluationStore((s) => s.pipeline)
  const runStartedAt = useEvaluationStore((s) => s.runStartedAt)
  const lastEventName = useEvaluationStore((s) => s.lastEventName)
  const coverage = useEvaluationStore((s) => s.coverage)
  const score = useEvaluationStore((s) => s.score)
  const [now, setNow] = useState(Date.now())

  const elapsedSeconds = runStartedAt ? Math.max(0, Math.floor((now - runStartedAt) / 1000)) : 0
  const activeStep = pipeline.find((s) => s.status === 'running')
  const doneCount = pipeline.filter((s) => s.status === 'done').length
  const scenarioCount = score.scenarios.length

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  const statusText = useMemo(() => {
    if (!running && doneCount === 0) return '等待开始'
    if (!running && doneCount > 0) return '评测完成'
    return activeStep ? stageLabels[activeStep.id] || activeStep.title : '处理中'
  }, [running, doneCount, activeStep])

  // Don't render at all if nothing happened yet and not running
  if (!running && doneCount === 0 && scenarioCount === 0) return null

  return (
    <section className="pipeline-tracker">
      <div className="pt-header">
        <div className="pt-status">
          {running ? <Loader2 size={16} className="spin" /> : <CheckCircle2 size={16} />}
          <strong>{statusText}</strong>
          {elapsedSeconds > 0 && <span className="pt-elapsed">{formatDuration(elapsedSeconds)}</span>}
        </div>
        <div className="pt-metrics">
          <span>场景 {scenarioCount}/{score.scenarios.length || '—'}</span>
          {lastEventName && <span className="pt-event">{lastEventName}</span>}
        </div>
      </div>

      {/* Stage progress dots */}
      <div className="pt-stages">
        {pipeline.map((step) => (
          <div key={step.id} className={`pt-stage ${step.status}`}>
            <div className="pt-dot" />
            <span className="pt-label">{stageLabels[step.id] || step.title}</span>
            {step.status === 'done' && step.duration != null && (
              <span className="pt-time">{formatDuration(step.duration)}</span>
            )}
          </div>
        ))}
      </div>

      {/* Live coverage bar (only during/after dialogue) */}
      {(coverage.state > 0 || coverage.edge > 0) && (
        <div className="pt-coverage">
          <span>状态 {Math.round(coverage.state)}%</span>
          <span>边 {Math.round(coverage.edge)}%</span>
          <span>风险 {Math.round(coverage.risk)}%</span>
          <span>需求 {Math.round(coverage.requirement)}%</span>
        </div>
      )}
    </section>
  )
}
