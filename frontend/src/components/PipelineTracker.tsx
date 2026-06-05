import { BarChart3, Bot, CheckCircle2, FlaskConical, GitBranch, Loader2, Wand2 } from 'lucide-react'
import { useEvaluationStore } from '../store/evaluationStore'

const icons = {
  parsing: Wand2,
  dsl_compile: GitBranch,
  scenario_gen: FlaskConical,
  dialogue: Bot,
  scoring: BarChart3,
}

export function PipelineTracker() {
  const pipeline = useEvaluationStore((s) => s.pipeline)
  return (
    <section className="panel pipeline-panel">
      <h2>评测流程追踪</h2>
      <div className="pipeline">
        {pipeline.map((step, index) => {
          const Icon = icons[step.id]
          return (
            <div className={`pipe-node ${step.status}`} key={step.id}>
              <div className="pipe-card">
                <Icon size={22} />
                <strong>{step.title}</strong>
                <span>{step.subtitle}</span>
                <small>
                  {step.status === 'running' && <Loader2 className="spin" size={14} />}
                  {step.status === 'done' && <CheckCircle2 size={14} />}
                  {step.status === 'done' ? `${step.duration ?? 0}s` : step.status}
                </small>
              </div>
              {index < pipeline.length - 1 && <i />}
            </div>
          )
        })}
      </div>
    </section>
  )
}
