import { CheckCircle2, Loader2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

const icons = {
  parsing: 'report',
  dsl_compile: 'state',
  scenario_gen: 'scenario',
  dialogue: 'timeline',
  scoring: 'score',
} as const

const guideText = {
  parsing: '提取角色、目标和约束',
  dsl_compile: '生成可测状态机',
  scenario_gen: '从覆盖缺口反推场景',
  dialogue: '执行多轮对话试炼',
  scoring: '汇总报告与证据链',
} as const

const formatSeconds = (seconds: number) => {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}m ${rest}s`
}

export function PipelineTracker() {
  const running = useEvaluationStore((s) => s.running)
  const pipeline = useEvaluationStore((s) => s.pipeline)
  const runStartedAt = useEvaluationStore((s) => s.runStartedAt)
  const lastEventAt = useEvaluationStore((s) => s.lastEventAt)
  const lastEventName = useEvaluationStore((s) => s.lastEventName)
  const eventCount = useEvaluationStore((s) => s.eventCount)
  const [now, setNow] = useState(Date.now())
  const activeIndex = Math.max(0, pipeline.findIndex((step) => step.status === 'running'))
  const doneFallback = Math.max(0, pipeline.filter((step) => step.status === 'done').length - 1)
  const litIndex = pipeline.some((step) => step.status === 'running') ? activeIndex : doneFallback
  const activeStep = pipeline[litIndex]
  const elapsedSeconds = runStartedAt ? Math.max(0, Math.floor((now - runStartedAt) / 1000)) : 0
  const quietSeconds = lastEventAt ? Math.max(0, Math.floor((now - lastEventAt) / 1000)) : 0
  const runHint = useMemo(() => {
    if (!running) {
      if (pipeline.some((step) => step.status === 'error')) return '已停止：请查看失败阶段的错误信息'
      if (pipeline.some((step) => step.status === 'done')) return '已完成：结果和报告已生成'
      return '等待开始'
    }
    if (quietSeconds >= 20) return '后端仍在处理，LLM 调用可能需要更久'
    if (eventCount === 0) return '正在连接后端并创建评测任务'
    return '正在接收后端实时进度'
  }, [eventCount, pipeline, quietSeconds, running])

  useEffect(() => {
    if (!running) {
      setNow(Date.now())
      return
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [running])

  return (
    <section className="panel route-panel">
      <header className="module-head">
        <div className="module-title">
          <ThemeIcon name="state" size={30} />
          <div>
            <h2>评测路线地图</h2>
            <p>实时展示后端进度，长时间等待时也会提示当前状态</p>
          </div>
        </div>
        <span className="route-status">当前节点：{activeStep?.title ?? '等待开始'}</span>
      </header>

      <div className={`run-progress ${running ? 'running' : ''} ${quietSeconds >= 20 && running ? 'quiet' : ''}`}>
        <div className="run-pulse">{running ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}</div>
        <div className="run-copy">
          <strong>{runHint}</strong>
          <span>
            当前阶段：{activeStep?.title ?? '未开始'} · 已运行 {formatSeconds(elapsedSeconds)} · 最近更新 {quietSeconds}s 前
          </span>
        </div>
        <div className="run-metrics">
          <b>{eventCount}</b>
          <span>{lastEventName ?? '暂无事件'}</span>
        </div>
      </div>

      <div className="route-map">
        <div className="route-line" />
        {pipeline.map((step, index) => {
          const lit = index <= litIndex || step.status === 'done'
          const current = step.status === 'running' || index === litIndex
          return (
            <article className={`route-stop ${lit ? 'lit' : ''} ${current ? 'current' : ''}`} key={step.id}>
              <div className="route-dot">
                <ThemeIcon name={icons[step.id]} size={28} />
              </div>
              <strong>{index + 1}. {step.title}</strong>
              <span>{guideText[step.id]}</span>
              <small>
                {step.status === 'running' && <Loader2 className="spin" size={14} />}
                {step.status === 'done' && <CheckCircle2 size={14} />}
                {step.status === 'done' ? (step.duration != null && step.duration < 0.1 ? '<0.1s' : `${step.duration ?? 0}s`) : step.status}
              </small>
            </article>
          )
        })}
      </div>
    </section>
  )
}
