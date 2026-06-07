import { useEvaluationStore } from '../store/evaluationStore'

export function EvidenceTimeline() {
  const timeline = useEvaluationStore((s) => s.timeline)
  const items = timeline.length ? timeline : [
    { id: 'empty-1', kind: 'round' as const, title: '等待评测', detail: '启动评测后此处实时展示证据链。', meta: '' },
  ]
  return (
    <section className="panel timeline-panel">
      <header className="panel-head">
        <h2>P0/P1 证据</h2>
        <p>每条高风险扣分回溯到具体场景、对话轮次和规则</p>
      </header>
      <div className="timeline">
        {items.slice(-12).map((item) => (
          <article className={`timeline-item ${item.kind}`} key={item.id}>
            <i />
            <div>
              <strong>{item.title}</strong>
              <p>{item.detail}</p>
              {item.dialogueExcerpt && (
                <div className="evidence-excerpt">
                  <div className="excerpt-turn">Turn {item.dialogueExcerpt.turn}</div>
                  <div className="excerpt-line user-line">用户: {item.dialogueExcerpt.userUtterance}</div>
                  <div className="excerpt-line agent-line">客服: {item.dialogueExcerpt.agentUtterance}</div>
                  {item.dialogueExcerpt.ruleName && (
                    <div className="excerpt-rule">
                      {item.dialogueExcerpt.ruleName}: {item.dialogueExcerpt.ruleMessage}
                    </div>
                  )}
                </div>
              )}
              <span>{item.meta}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
