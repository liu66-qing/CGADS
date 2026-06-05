import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

export function EvidenceTimeline() {
  const timeline = useEvaluationStore((s) => s.timeline)
  const items = timeline.length ? timeline : [
    { id: 'empty-1', kind: 'round', title: '等待第一条证据', detail: '开始评测后，场景生成、覆盖命中、违规与转移都会写入这里。', meta: 'idle' },
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
              <span>{item.meta}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
