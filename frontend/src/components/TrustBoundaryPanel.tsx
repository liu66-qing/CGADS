import { ShieldCheck } from 'lucide-react'
import { useEvaluationStore } from '../store/evaluationStore'

export function TrustBoundaryPanel() {
  const score = useEvaluationStore((s) => s.score)
  const coverage = useEvaluationStore((s) => s.coverage)
  const scenarioCount = score.scenarios.length
  const riskOk = coverage.risk >= 70
  const requirementOk = coverage.requirement >= 80
  const passOk = score.passStatus === 'PASS'
  const canTrust = scenarioCount > 0 && riskOk && requirementOk && passOk

  return (
    <section className="panel trust-boundary-panel">
      <header className="section-head">
        <div>
          <h2><ShieldCheck size={22} /> 采信边界</h2>
          <p>明确这份报告可以支持什么判断，哪些结论还需要补测后再采信</p>
        </div>
        <span className={canTrust ? 'trust-chip pass' : 'trust-chip warn'}>{canTrust ? '可采信' : '需补测'}</span>
      </header>
      <div className="trust-grid">
        <article>
          <span>可直接采信</span>
          <strong>{canTrust ? '上线前质量判断与优化优先级' : '已命中的证据链和明确违规样本'}</strong>
          <p>{scenarioCount ? `已完成 ${scenarioCount} 个场景，业务需求覆盖 ${coverage.requirement}%，风险覆盖 ${coverage.risk}%。` : '尚未开始评测，暂无可采信结论。'}</p>
        </article>
        <article>
          <span>暂不采信</span>
          <strong>{riskOk ? '低频长尾风险仍建议抽检' : 'P0/P1 风险结论不能直接作为放行依据'}</strong>
          <p>{riskOk ? '风险覆盖达到基础门槛后，仍应抽检真实 ASR 样本确认稳定性。' : '需补齐身份真实性、官方渠道、拒绝退出、敏感信息和承诺类话术。'}</p>
        </article>
      </div>
    </section>
  )
}
