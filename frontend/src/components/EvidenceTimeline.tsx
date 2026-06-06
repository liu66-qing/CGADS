import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

export function EvidenceTimeline() {
  const timeline = useEvaluationStore((s) => s.timeline)
  const items = timeline.length ? timeline : [
    { id: 'empty-1', kind: 'round' as const, title: '等待评测', detail: '启动评测后此处实时展示证据链。', meta: '' },
  ]
  return (
    <section className="panel timeline-panel plugin-panel">
      <header className="section-head">
        <div>
          <h2><ThemeIcon name="timeline" size={26} /> 证据时间轴</h2>
          <p>每条分数都要能回到一次场景、一次覆盖或一次违规</p>
        </div>
        <span className="next-cue">下一步看：完整报告</span>
      </header>
      <div className="timeline">
        {items.slice(-12).map((item) => (
          <article className={`timeline-item ${item.kind} plugin-card`} key={item.id}>
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
