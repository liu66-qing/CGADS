import { Clock3 } from 'lucide-react'
import { getEvaluation } from '../api'
import { useEvaluationStore } from '../store/evaluationStore'

export function HistoryStrip() {
  const evaluations = useEvaluationStore((s) => s.evaluations)
  const setDslPreview = useEvaluationStore((s) => s.setDslPreview)

  if (!evaluations.length) return null

  const loadEvaluation = async (item: Record<string, unknown>) => {
    const id = String(item.id ?? item.evaluation_id ?? '')
    if (!id) return
    try {
      const detail = await getEvaluation(id)
      const output = (detail.pipeline_output ?? {}) as Record<string, any>
      const dsl = (detail.dsl ?? output.dsl ?? output.dsl_compile ?? {}) as Record<string, any>
      const states = (detail.states ?? dsl.states ?? output.states ?? []) as any[]
      const edges = (detail.edges ?? dsl.edges ?? output.edges ?? []) as any[]
      if (states.length || edges.length) setDslPreview(states, edges)
    } catch {
      // Loading history is a convenience path; keep the current dashboard if it fails.
    }
  }

  return (
    <section className="history-strip">
      <div className="history-title">
        <Clock3 size={16} />
        <b>历史评测</b>
      </div>
      <div className="history-list">
        {evaluations.slice(0, 4).map((item, index) => (
          <button key={String(item.id ?? index)} onClick={() => loadEvaluation(item)}>
            <span>{String(item.name ?? item.task_name ?? item.task_id ?? item.id ?? `评测 ${index + 1}`)}</span>
            <small>{String(item.pass_status ?? item.status ?? '可回放')}</small>
          </button>
        ))}
      </div>
    </section>
  )
}
