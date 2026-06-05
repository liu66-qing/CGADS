import { useEvaluationStore } from '../store/evaluationStore'

export function StepDetailPanel() {
  const active = useEvaluationStore((s) => s.pipeline.find((p) => p.status === 'running') ?? s.pipeline.find((p) => p.status === 'done') ?? s.pipeline[0])
  const rounds = useEvaluationStore((s) => s.rounds)
  const gaps = useEvaluationStore((s) => s.gaps)
  const coverage = useEvaluationStore((s) => s.coverage)

  return (
    <section className="panel step-detail">
      <div>
        <h3>当前执行步骤自动展开</h3>
        <strong>{active.title}</strong>
        <p>{active.error || active.subtitle}</p>
      </div>
      <div className="log-strip">
        <span>Round：{rounds.length || 0}</span>
        <span>识别缺口：{gaps.length}</span>
        <span>目标拓展数：{Math.max(0, gaps.length * 2)}</span>
        <span>状态覆盖：{coverage.state}%</span>
      </div>
      <div className="scenario-preview">
        {(rounds.at(-1)?.scenarios as any[] | undefined)?.slice(0, 3).map((scenario, index) => (
          <article key={`${scenario.name}-${index}`}>
            <b>{scenario.name || `场景 ${index + 1}`}</b>
            <small>{(scenario.targets ?? []).slice(0, 2).join(' / ') || '覆盖目标待生成'}</small>
          </article>
        )) ?? <article><b>等待 CGADS 编译日志</b><small>开始评测后这里会滚动展示补洞场景</small></article>}
      </div>
    </section>
  )
}
