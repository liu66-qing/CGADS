import ReactFlow, { Background, Controls } from 'reactflow'
import type { Edge, Node } from 'reactflow'
import type { StateEdge, StateNode } from '../types'
import { useMemo } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'
import { useShallow } from 'zustand/react/shallow'

const fallbackStates: StateNode[] = [
  { id: 'opening', label: '身份确认' },
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
  { from: 'opening', to: 'auth_or_trust' },
  { from: 'auth_or_trust', to: 'inform' },
  { from: 'inform', to: 'faq_handling' },
  { from: 'faq_handling', to: 'intent_confirm' },
  { from: 'intent_confirm', to: 'closing' },
  { from: 'opening', to: 'busy_handling' },
  { from: 'busy_handling', to: 'refusal_exit' },
  { from: 'intent_confirm', to: 'handoff_or_escalation' },
]

export function StateMachineGraph() {
  const storeStates = useEvaluationStore(useShallow((s) => s.states))
  const storeEdges = useEvaluationStore(useShallow((s) => s.edges))
  const coverage = useEvaluationStore(useShallow((s) => s.coverage))
  const states = storeStates.length ? storeStates : fallbackStates
  const edges = storeEdges.length ? storeEdges : fallbackEdges

  const nodes: Node[] = useMemo(() => states.map((state, index) => ({
    id: state.id,
    data: { label: `${state.label}\n(${state.id})` },
    position: { x: (index % 5) * 170 + 30, y: Math.floor(index / 5) * 145 + 40 },
    className: state.terminal ? 'rf-node danger' : index < Math.ceil(states.length * coverage.state / 100) ? 'rf-node covered' : 'rf-node',
  })), [states, coverage.state])

  const flowEdges: Edge[] = useMemo(() => edges.map((edge, index) => ({
    id: `${edge.from}-${edge.to}-${index}`,
    source: edge.from,
    target: edge.to,
    label: edge.label,
    animated: index < Math.ceil(edges.length * coverage.edge / 100),
    className: index < Math.ceil(edges.length * coverage.edge / 100) ? 'covered-edge' : '',
  })), [edges, coverage.edge])
  const graphKey = `${states.map((s) => s.id).join('|')}::${edges.map((e) => `${e.from}-${e.to}`).join('|')}::${coverage.state}-${coverage.edge}`

  return (
    <section className="panel graph-panel">
      <header>
        <h2>状态机可视化</h2>
        <p>交互式节点地图 · 蓝色已覆盖，红色为终止/风险路径</p>
      </header>
      <div className="flow-wrap">
        <ReactFlow key={graphKey} defaultNodes={nodes} defaultEdges={flowEdges} fitView nodesDraggable={false}>
          <Background gap={18} color="#dfe7f3" />
          <Controls />
        </ReactFlow>
      </div>
    </section>
  )
}
