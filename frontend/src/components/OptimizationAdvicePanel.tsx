import { Lightbulb } from 'lucide-react'
import { useEvaluationStore } from '../store/evaluationStore'

const suggestionToText = (suggestion: unknown) => {
  if (!suggestion) return ''
  if (typeof suggestion === 'string') return suggestion
  if (typeof suggestion !== 'object') return String(suggestion)
  const item = suggestion as Record<string, unknown>
  return [item.title, item.problem, item.action]
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .join('：')
}

export function OptimizationAdvicePanel() {
  const suggestions = useEvaluationStore((s) => s.score.suggestions)
  const coverage = useEvaluationStore((s) => s.coverage)
  const items = suggestions.map(suggestionToText).filter(Boolean)
  const fallback = [
    coverage.risk < 70 ? '优先补齐身份真实性、官方渠道、拒绝后继续营销、敏感信息和承诺诱导风险场景。' : '',
    coverage.requirement < 80 ? '补充完整流程型用户画像，验证合同通知、配送要求、疑问处理和合规结束是否全部完成。' : '',
    '将每条扣分映射到原始对话 turn、规则 ID、扣分原因和 prompt 修改建议。',
  ].filter(Boolean)

  return (
    <section className="panel optimization-panel">
      <header className="section-head">
        <div>
          <h2><Lightbulb size={22} /> 优化建议</h2>
          <p>直接面向数字人团队的 prompt、状态机和兜底策略修改方向</p>
        </div>
      </header>
      <div className="advice-list">
        {(items.length ? items : fallback).slice(0, 5).map((item, index) => (
          <article key={`${item}-${index}`}>
            <span>{index + 1}</span>
            <p>{item}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
