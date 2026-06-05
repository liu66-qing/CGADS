import { ChevronDown, Database, FileUp, Play, Sparkles, Square } from 'lucide-react'
import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { useEvaluationSse } from '../hooks/useEvaluationSse'
import { useEvaluationStore } from '../store/evaluationStore'
import { defaultOfficialExample, officialExamples } from '../data/officialExamples'
import { ThemeIcon } from './ThemeIcon'
import { compileDslPreview } from '../api'

export function InputPanel() {
  const [open, setOpen] = useState(true)
  const [fileName, setFileName] = useState('')
  const instruction = useEvaluationStore((s) => s.instruction)
  const setInstruction = useEvaluationStore((s) => s.setInstruction)
  const running = useEvaluationStore((s) => s.running)
  const { start, stop } = useEvaluationSse()
  const [selectedId, setSelectedId] = useState(defaultOfficialExample.id)
  const [previewing, setPreviewing] = useState(false)
  const selectedExample = officialExamples.find((item) => item.id === selectedId) ?? defaultOfficialExample
  const setDslPreview = useEvaluationStore((s) => s.setDslPreview)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)

  const useExample = (id: string) => {
    const next = officialExamples.find((item) => item.id === id) ?? defaultOfficialExample
    setSelectedId(next.id)
    setFileName('')
    setInstruction(next.instruction)
  }

  const uploadInstruction = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    const text = await file.text()
    setInstruction(text)
  }

  const previewDsl = async () => {
    setPreviewing(true)
    try {
      const result = await compileDslPreview(instruction || selectedExample.instruction)
      setDslPreview(result.states ?? [], result.edges ?? [])
      setBackendStatus('ok')
    } catch {
      setBackendStatus('offline')
    } finally {
      setPreviewing(false)
    }
  }

  return (
    <section className="panel input-panel">
      <button className="panel-title" onClick={() => setOpen(!open)}>
        <span className="title-icon"><ThemeIcon name="report" size={18} /></span>
        <span>输入区</span>
        <span className="muted">上传文件、粘贴文本或选择官方示例后即可开始</span>
        <ChevronDown className={open ? 'chevron open' : 'chevron'} size={18} />
      </button>
      {open && (
        <div className="input-grid polished-input-grid">
          <label className="instruction-box">
            <span>任务指令文本</span>
            <textarea
              value={instruction}
              onChange={(event) => {
                setFileName('')
                setInstruction(event.target.value)
              }}
              placeholder={selectedExample.instruction}
              maxLength={8000}
            />
            <em>{instruction.length} / 8000</em>
          </label>

          <div className="example-box input-source-box">
            <span>输入来源</span>
            <label className="upload-drop">
              <FileUp size={18} />
              <strong>{fileName || '上传任务文件'}</strong>
              <small>.md / .txt / .csv / .gmb / .json</small>
              <input type="file" accept=".md,.txt,.csv,.gmb,.json" onChange={uploadInstruction} />
            </label>
            <div className="official-select-wrap">
              <small>官方示例</small>
              <select value={selectedId} onChange={(event) => useExample(event.target.value)}>
                {officialExamples.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
            <p><Database size={16} /> {selectedExample.badge}</p>
            <p><Sparkles size={16} /> 评测会自动推进到完整报告</p>
          </div>

          <aside className="input-action-box">
            <b>准备就绪</b>
            <span>{fileName ? `已载入：${fileName}` : instruction ? '已输入任务文本' : '可直接使用官方示例'}</span>
            <button
              className={running ? 'start-button stop' : 'start-button'}
              onClick={() => (running ? stop() : start(instruction || selectedExample.instruction))}
            >
              {running ? <Square size={20} /> : <Play size={22} fill="currentColor" />}
              {running ? '停止评测' : '开始评测'}
            </button>
            <button className="preview-button" onClick={previewDsl} disabled={previewing || running}>
              {previewing ? '编译中...' : '预览状态机'}
            </button>
          </aside>
        </div>
      )}
    </section>
  )
}
