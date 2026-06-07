import { useState } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'

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
    <section className="panel dialogue-panel">
      <header className="panel-head">
        <h2>模拟对话明细</h2>
        <p>每个场景完整的用户-客服多轮对话，违规处标红</p>
      </header>

      <div className="dialogue-tabs">
        {scenarioIds.map((id) => {
          const meta = scenarios.find((s) => s.id === id)
          return (
            <button
              key={id}
              className={`dtab ${id === active ? 'active' : ''} ${meta?.p0 ? 'has-p0' : meta?.p1 ? 'has-p1' : ''}`}
              onClick={() => setSelectedId(id)}
            >
              <span className="dtab-name">{id}</span>
              {meta && <span className="dtab-score">{meta.score}</span>}
            </button>
          )
        })}
      </div>

      {dialogue.persona && (
        <div className="dialogue-persona">用户画像：{dialogue.persona}</div>
      )}

      {scenarioMeta && (
        <div className="dialogue-meta">
          {scenarioMeta.turns} 轮 · 得分 {scenarioMeta.score} · P0 {scenarioMeta.p0} / P1 {scenarioMeta.p1}
        </div>
      )}

      <div className="chat-messages">
        {dialogue.messages.map((msg, i) => {
          const turnNum = Math.ceil((i + 1) / 2)
          const violationOnTurn = dialogue.violationDetails?.find(
            (v) => v.turn === turnNum
          )
          const isViolation = violationOnTurn && msg.role === 'assistant'

          return (
            <div key={i} className={`chat-row ${msg.role} ${isViolation ? 'violation' : ''}`}>
              <div className="chat-avatar">
                {msg.role === 'user' ? '👤' : '🤖'}
              </div>
              <div className="chat-bubble-wrap">
                <div className="chat-meta-line">
                  <span className="chat-role-label">
                    {msg.role === 'user' ? '用户' : '客服'}
                  </span>
                  <span className="chat-turn">T{turnNum}</span>
                </div>
                <div className={`chat-bubble ${msg.role} ${isViolation ? 'violation' : ''}`}>
                  {msg.content}
                </div>
                {isViolation && violationOnTurn.violations.map((v, vi) => (
                  <div key={vi} className="chat-violation-tag">
                    <span className="viol-rule">{v.rule_name}</span>
                    <span className="viol-msg">{v.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
