import { useEvaluationStore } from '../store/evaluationStore'
import { useShallow } from 'zustand/react/shallow'
import { ThemeIcon } from './ThemeIcon'

const positions = [
  { x: 14, y: 16 },
  { x: 14, y: 42 },
  { x: 43, y: 33 },
  { x: 70, y: 26 },
  { x: 72, y: 52 },
  { x: 15, y: 72 },
  { x: 34, y: 82 },
  { x: 50, y: 72 },
  { x: 86, y: 78 },
]

export function StateMachineGraph() {
  const states = useEvaluationStore(useShallow((s) => s.states))
  const edges = useEvaluationStore(useShallow((s) => s.edges))
  const coverage = useEvaluationStore(useShallow((s) => s.coverage))
  const stateNames = useEvaluationStore(useShallow((s) => s.stateNames))
  const timeline = useEvaluationStore((s) => s.timeline)
  const coveredStateCount = Math.ceil(states.length * coverage.state / 100)
  const coveredEdgeCount = Math.ceil(edges.length * coverage.edge / 100)
  const active = states[Math.min(Math.max(coveredStateCount - 1, 0), states.length - 1)] ?? states[0]
  const terminalCount = states.filter((state) => state.terminal).length

  return (
    <section className="panel state-viz-panel">
      <header className="state-viz-head">
        <div className="module-title">
          <ThemeIcon name="state" size={34} />
          <div>
            <h2>状态机可视化</h2>
            <p>交互式状态节点图，评测完成后展示覆盖、违规与路径回放。</p>
          </div>
        </div>
      </header>

      {states.length === 0 ? (
        <div className="state-empty">
          <strong>等待评测</strong>
          <span>DSL编译后生成状态图</span>
        </div>
      ) : (
        <>
          <div className="state-legend">
            <b>节点状态</b>
            <span><i className="unvisited" />未访问</span>
            <span><i className="covered" />已覆盖</span>
            <span><i className="risk" />有违规</span>
            <span><i className="current" />当前节点</span>
            <em />
            <b>边状态</b>
            <span><i className="edge-hit" />已触发</span>
            <span><i className="edge-idle" />未触发</span>
            <span><i className="edge-risk" />触发但违规</span>
          </div>

          <div className="state-stat-grid">
            <article><ThemeIcon name="coverage" size={32} /><span>状态覆盖</span><strong>{coveredStateCount}<em>/{states.length}</em></strong></article>
            <article><ThemeIcon name="state" size={32} /><span>边覆盖</span><strong>{coveredEdgeCount}<em>/{edges.length}</em></strong></article>
            <article><ThemeIcon name="report" size={32} /><span>终止节点</span><strong>{terminalCount}</strong></article>
            <article><ThemeIcon name="timeline" size={32} /><span>当前路径长度</span><strong>{coveredEdgeCount}</strong></article>
          </div>

          <div className="state-viz-body">
            <div className="machine-canvas">
              <div className="canvas-hint">Hover 查看条件，点击节点看详情；当前路径高亮回放。</div>
              <div className="machine-filter"><button>全部</button><button>仅覆盖</button><button>仅违规</button><button>当前路径</button></div>
              <svg className="machine-links" viewBox="0 0 100 100" preserveAspectRatio="none">
                {edges.map((edge, index) => {
                  const fromIndex = Math.max(0, states.findIndex((s) => s.id === edge.from))
                  const toIndex = Math.max(0, states.findIndex((s) => s.id === edge.to))
                  const from = positions[fromIndex % positions.length]
                  const to = positions[toIndex % positions.length]
                  const covered = index < coveredEdgeCount
                  const risk = edge.to.includes('refusal') || edge.to.includes('handoff')
                  return (
                    <g key={`${edge.from}-${edge.to}-${index}`}>
                      <path className={`machine-link ${covered ? 'covered' : ''} ${risk ? 'risk' : ''}`} d={`M${from.x} ${from.y} C${(from.x + to.x) / 2} ${from.y + 6}, ${(from.x + to.x) / 2} ${to.y - 6}, ${to.x} ${to.y}`} />
                      {edge.label && <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 2}>{edge.label}</text>}
                    </g>
                  )
                })}
              </svg>
              {states.map((state, index) => {
                const pos = positions[index % positions.length]
                const covered = index < coveredStateCount
                const current = state.id === active?.id
                return (
                  <article
                    key={state.id}
                    className={`machine-node ${covered ? 'covered' : ''} ${current ? 'current' : ''} ${state.terminal ? 'terminal' : ''}`}
                    style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
                  >
                    <b>{stateNames[state.id] ?? state.label}</b>
                    <span>{state.id}</span>
                  </article>
                )
              })}
              <div className="canvas-controls"><button>-</button><button>+</button><button>⟲</button><button>▶ 回放路径</button></div>
            </div>

            <aside className="state-side">
              <section className="state-detail-card">
                <header><b>节点详情</b><span>{active ? '已覆盖' : '待探索'}</span></header>
                <h3>{active ? (stateNames[active.id] ?? active.label) : '等待生成'} <small>({active?.id ?? 'pending'})</small></h3>
                <dl>
                  <dt>状态ID</dt><dd>{active?.id ?? '-'}</dd>
                  <dt>状态名称</dt><dd>{active ? (stateNames[active.id] ?? active.label) : '-'}</dd>
                  <dt>进入条件</dt><dd>{active?.entry ? '入口节点' : '-'}</dd>
                  <dt>终止状态</dt><dd>{active?.terminal ? '是' : '否'}</dd>
                </dl>
              </section>

              <section className="state-events-card">
                <header><b>事件与证据时间线</b></header>
                {timeline.length ? timeline.slice(-4).map((item) => (
                  <article className={`state-event ${item.kind}`} key={item.id}>
                    <i />
                    <time>{item.meta}</time>
                    <strong>{item.title}</strong>
                    <p>{item.detail}</p>
                  </article>
                )) : <p className="state-events-empty">等待评测启动后生成事件日志</p>}
              </section>
            </aside>
          </div>
        </>
      )}
    </section>
  )
}
