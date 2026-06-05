import { CheckCircle2, Loader2 } from 'lucide-react'
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
  parsing: '选择任务后自动解析字段',
  dsl_compile: '生成可测状态机',
  scenario_gen: '从缺口反推场景',
  dialogue: '执行多轮对话试炼',
  scoring: '汇总报告与证据链',
} as const

export function PipelineTracker() {
  const pipeline = useEvaluationStore((s) => s.pipeline)
  const activeIndex = Math.max(0, pipeline.findIndex((step) => step.status === 'running'))
  const doneFallback = Math.max(0, pipeline.filter((step) => step.status === 'done').length - 1)
  const litIndex = pipeline.some((step) => step.status === 'running') ? activeIndex : doneFallback

  return (
    <section className="panel route-panel">
      <header className="module-head">
        <div className="module-title">
          <ThemeIcon name="state" size={30} />
          <div>
            <h2>评测路线地图</h2>
            <p>一站式自动推进，橙色节点表示当前该看哪里</p>
          </div>
        </div>
        <span className="route-status">当前节点：{pipeline[litIndex]?.title ?? '等待开始'}</span>
      </header>

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
                {step.status === 'done' ? `${step.duration ?? 0}s` : step.status}
              </small>
            </article>
          )
        })}
      </div>
    </section>
  )
}
