import { ChevronDown, FileText, Play, Sparkles, Square } from 'lucide-react'
import { useState } from 'react'
import { useEvaluationSse } from '../hooks/useEvaluationSse'
import { useEvaluationStore } from '../store/evaluationStore'

const examples = [
  '电话营销-套餐推荐-标准流程',
  '骑手权益通知-抽奖说明',
  '异议处理-用户质疑与合规结束',
]

const sampleInstruction = `请模拟坐席来电与用户交互。
评估坐席在身份确认、需求处理的确认、需求处理、产品介绍、异议处理与合规结束中的表现。
请根据业务场景生成对话并给出覆盖率与证据链。`

export function InputPanel() {
  const [open, setOpen] = useState(true)
  const instruction = useEvaluationStore((s) => s.instruction)
  const setInstruction = useEvaluationStore((s) => s.setInstruction)
  const running = useEvaluationStore((s) => s.running)
  const { start, stop } = useEvaluationSse()

  return (
    <section className="panel input-panel">
      <button className="panel-title" onClick={() => setOpen(!open)}>
        <span className="title-icon"><FileText size={18} /></span>
        <span>输入区</span>
        <span className="muted">折叠式 · 支持 .md/.txt/.csv/.gmb</span>
        <ChevronDown className={open ? 'chevron open' : 'chevron'} size={18} />
      </button>
      {open && (
        <div className="input-grid">
          <label className="instruction-box">
            <span>任务指令</span>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder={sampleInstruction}
              maxLength={5000}
            />
            <em>{instruction.length} / 5000</em>
          </label>
          <div className="example-box">
            <span>示例任务</span>
            <select onChange={(e) => setInstruction(`${sampleInstruction}\n\n示例：${e.target.value}`)} defaultValue={examples[0]}>
              {examples.map((item) => <option key={item}>{item}</option>)}
            </select>
            <p><Sparkles size={16} /> 作品名：橙脉 CGADS · 外呼指令状态机试炼场</p>
          </div>
          <button
            className={running ? 'start-button stop' : 'start-button'}
            onClick={() => (running ? stop() : start(instruction || sampleInstruction))}
          >
            {running ? <Square size={20} /> : <Play size={22} fill="currentColor" />}
            {running ? '停止评测' : '开始评测'}
          </button>
        </div>
      )}
    </section>
  )
}
