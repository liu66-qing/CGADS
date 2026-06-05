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
      const states = (detail.states ?? detail.dsl?.states ?? detail.pipeline_output?.states ?? []) as any[]
      const edges = (detail.edges ?? detail.dsl?.edges ?? detail.pipeline_output?.edges ?? []) as any[]
      if (states.length || edges.length) setDslPreview(states, edges)
    } catch {
      // History is optional; keep the current dashboard if loading fails.
    }
  }

  return (
    <section className="history-strip">
      <b>历史评测</b>
      {evaluations.slice(0, 4).map((item, index) => (
        <button key={String(item.id ?? index)} onClick={() => loadEvaluation(item)}>
          {String(item.name ?? item.task_id ?? item.id ?? `评测 ${index + 1}`)}
        </button>
      ))}
    </section>
  )
}
