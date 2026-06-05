import type { StateEdge, StateNode } from '../types'
import { useEvaluationStore } from '../store/evaluationStore'
import { useShallow } from 'zustand/react/shallow'
import { ThemeIcon } from './ThemeIcon'

const fallbackStates: StateNode[] = [
  { id: 'opening', label: '身份确认', entry: true },
  { id: 'auth_or_trust', label: '建立信任' },
  { id: 'inform', label: '信息说明' },
  { id: 'faq_handling', label: '疑问解答' },
  { id: 'intent_confirm', label: '意图确认' },
  { id: 'busy_handling', label: '忙碌处理' },
  { id: 'refusal_exit', label: '拒绝退出', terminal: true },
  { id: 'closing', label: '合规结束', terminal: true },
  { id: 'handoff_or_escalation', label: '转人工' },
]

const fallbackEdges: StateEdge[] = [
  { from: 'opening', to: 'auth_or_trust', label: '可信' },
  { from: 'auth_or_trust', to: 'inform', label: '已建信任' },
  { from: 'inform', to: 'faq_handling', label: '用户提问' },
  { from: 'faq_handling', to: 'intent_confirm', label: '解释完成' },
  { from: 'intent_confirm', to: 'closing', label: '达成' },
  { from: 'opening', to: 'busy_handling', label: '忙碌' },
  { from: 'busy_handling', to: 'refusal_exit', label: '拒绝' },
  { from: 'intent_confirm', to: 'handoff_or_escalation', label: '升级' },
]

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
  const storeStates = useEvaluationStore(useShallow((s) => s.states))
  const storeEdges = useEvaluationStore(useShallow((s) => s.edges))
  const coverage = useEvaluationStore(useShallow((s) => s.coverage))
  const stateNames = useEvaluationStore(useShallow((s) => s.stateNames))
  const timeline = useEvaluationStore((s) => s.timeline)
  const states = storeStates.length ? storeStates : fallbackStates
  const edges = storeEdges.length ? storeEdges : fallbackEdges
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
            <p>交互式状态节点图 · 支持覆盖、违规、路径回放</p>
          </div>
        </div>
      </header>

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
        <article><ThemeIcon name="report" size={32} /><span>违规节点</span><strong>{terminalCount}</strong></article>
        <article><ThemeIcon name="timeline" size={32} /><span>当前路径长度</span><strong>{Math.max(1, coveredEdgeCount)}</strong></article>
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
          <div className="canvas-controls"><button>-</button><button>+</button><button>⛶</button><button>▶ 回放路径</button></div>
        </div>

        <aside className="state-side">
          <section className="state-detail-card">
            <header><b>节点详情</b><span>{active ? '已覆盖' : '待探索'}</span></header>
            <h3>{active ? (stateNames[active.id] ?? active.label) : '等待生成'} <small>({active?.id ?? 'pending'})</small></h3>
            <dl>
              <dt>状态ID</dt><dd>{active?.id ?? '-'}</dd>
              <dt>状态说明</dt><dd>向客户说明产品方案、权益、费用或关键信息</dd>
              <dt>进入条件</dt><dd>已建立信任 / 用户询问产品信息</dd>
              <dt>出边条件</dt><dd>去意图确认 / 去疑问解答 / 去拒绝退出</dd>
              <dt>风险提示</dt><dd className="risk-text">信息缺失、解释不清、夸大承诺</dd>
            </dl>
          </section>

          <section className="state-events-card">
            <header><b>事件与证据时间线</b></header>
            {(timeline.length ? timeline.slice(-4) : [
              { id: 'e1', kind: 'coverage', title: '状态迁移', detail: '建立信任 → 信息说明', meta: '00:02:18' },
              { id: 'e2', kind: 'coverage', title: '覆盖命中', detail: '命中脚本节点：信息说明', meta: '00:02:20' },
              { id: 'e3', kind: 'p1', title: '违规触发', detail: '信息缺失：未说明费用细则', meta: '00:02:45' },
              { id: 'e4', kind: 'coverage', title: '状态迁移', detail: '信息说明 → 疑问解答', meta: '00:03:02' },
            ]).map((item) => (
              <article className={`state-event ${item.kind}`} key={item.id}>
                <i />
                <time>{item.meta}</time>
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
              </article>
            ))}
          </section>
        </aside>
      </div>
    </section>
  )
}
