import { useState } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

export function DialogueViewer() {
  const dialogues = useEvaluationStore((s) => s.dialogues)
  const scenarios = useEvaluationStore((s) => s.score.scenarios)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const scenarioIds = Object.keys(dialogues)
  if (scenarioIds.length === 0) return null

  const active = selectedId ?? scenarioIds[0]
  const dialogue = dialogues[active]
  if (!dialogue) return null

  const scenarioMeta = scenarios.find((s) => s.id === active)

  return (
    <section className="panel dialogue-panel plugin-panel">
      <header className="section-head">
        <div>
          <h2><ThemeIcon name="chat" size={26} /> 模拟对话明细</h2>
          <p>查看每个场景完整用户-客服对话</p>
        </div>
      </header>

      <div className="dialogue-tabs">
        {scenarioIds.map((id) => {
          const meta = scenarios.find((s) => s.id === id)
          return (
            <button
              key={id}
              className={`dialogue-tab ${id === active ? 'active' : ''} ${meta?.p0 ? 'has-p0' : meta?.p1 ? 'has-p1' : ''}`}
              onClick={() => setSelectedId(id)}
            >
              {id}
              {meta && <span className="tab-score">{meta.score}</span>}
            </button>
          )
        })}
      </div>

      {dialogue.persona && (
        <div className="dialogue-persona">
          用户画像: {dialogue.persona}
        </div>
      )}

      {scenarioMeta && (
        <div className="dialogue-meta">
          {scenarioMeta.turns} 轮 · 得分 {scenarioMeta.score} · P0 {scenarioMeta.p0} / P1 {scenarioMeta.p1}
        </div>
      )}

      <div className="dialogue-messages">
        {dialogue.messages.map((msg, i) => {
          const violationOnTurn = dialogue.violationDetails?.find(
            (v) => v.turn === Math.ceil((i + 1) / 2)
          )
          const isViolationTurn = violationOnTurn && msg.role === 'assistant'
          return (
            <div key={i} className={`msg msg-${msg.role} ${isViolationTurn ? 'msg-violation' : ''}`}>
              <div className="msg-role">{msg.role === 'user' ? '用户' : '客服'}</div>
              <div className="msg-content">{msg.content}</div>
              {isViolationTurn && violationOnTurn.violations.map((v, vi) => (
                <div key={vi} className="msg-violation-tag">
                  {v.rule_name}: {v.message}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </section>
  )
}
