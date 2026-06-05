import { useEvaluationStore } from '../store/evaluationStore'

export function EvidenceTimeline() {
  const timeline = useEvaluationStore((s) => s.timeline)
  const items = timeline.length ? timeline : [
    { id: 'empty-1', kind: 'round', title: '等待第一条证据', detail: '开始评测后，场景生成、覆盖命中、违规与转移都会写入这里。', meta: 'idle' },
  ]
  return (
    <section className="panel timeline-panel">
      <h2>证据时间轴</h2>
      <div className="timeline">
        {items.slice(-12).map((item) => (
          <article className={`timeline-item ${item.kind}`} key={item.id}>
            <i />
            <div>
              <strong>{item.title}</strong>
              <p>{item.detail}</p>
              <span>{item.meta}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
