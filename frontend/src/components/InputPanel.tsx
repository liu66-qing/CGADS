import { ChevronDown, Database, FileUp, Play, Sparkles, Square } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { compileDslPreview, getExamples } from '../api'
import { defaultOfficialExample, officialExamples, type OfficialExample } from '../data/officialExamples'
import { useEvaluationSse } from '../hooks/useEvaluationSse'
import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

export function InputPanel() {
  const [open, setOpen] = useState(true)
  const [fileName, setFileName] = useState('')
  const [selectedId, setSelectedId] = useState(defaultOfficialExample.id)
  const [previewing, setPreviewing] = useState(false)
  const [examples, setExamples] = useState<OfficialExample[]>(officialExamples)

  const instruction = useEvaluationStore((s) => s.instruction)
  const setInstruction = useEvaluationStore((s) => s.setInstruction)
  const running = useEvaluationStore((s) => s.running)
  const setDslPreview = useEvaluationStore((s) => s.setDslPreview)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)
  const { start, stop } = useEvaluationSse()

  // Auto-collapse when evaluation starts, auto-expand when done with results
  useEffect(() => {
    if (running) setOpen(false)
  }, [running])

  useEffect(() => {
    let alive = true
    getExamples()
      .then((payload) => {
        if (!alive || !payload.examples?.length) return
        const remoteExamples = payload.examples.map((item) => ({
          id: item.id,
          name: item.name,
          badge: item.goal ? '后端官方示例' : '官方示例',
          instruction: item.goal || item.name,
        }))
        setExamples(remoteExamples)
        setSelectedId(remoteExamples[0].id)
        setBackendStatus('ok')
      })
      .catch(() => setBackendStatus('offline'))

    return () => {
      alive = false
    }
  }, [setBackendStatus])

  const selectedExample = useMemo(
    () => examples.find((item) => item.id === selectedId) ?? examples[0] ?? defaultOfficialExample,
    [examples, selectedId],
  )

  const effectiveInstruction = instruction || selectedExample.instruction

  const useExample = (id: string) => {
    const next = examples.find((item) => item.id === id) ?? defaultOfficialExample
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
      const result = await compileDslPreview(effectiveInstruction)
      setDslPreview(result.states ?? [], result.edges ?? [])
      setBackendStatus('ok')
    } catch {
      setBackendStatus('offline')
    } finally {
      setPreviewing(false)
    }
  }

  const submitEvaluation = (event: FormEvent) => {
    event.preventDefault()
    if (running) {
      stop()
      return
    }
    void start(effectiveInstruction)
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
        <form className="input-grid polished-input-grid" onSubmit={submitEvaluation}>
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
                {examples.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
            <p><Database size={16} /> {selectedExample.badge}</p>
            <p><Sparkles size={16} /> 评测会自动推进到完整报告</p>
          </div>

          <aside className="input-action-box">
            <b>准备就绪</b>
            <span>{fileName ? `已载入：${fileName}` : instruction ? '已输入任务文本' : '可直接使用官方示例'}</span>
            <button
              type="submit"
              className={running ? 'start-button stop' : 'start-button'}
            >
              {running ? <Square size={20} /> : <Play size={22} fill="currentColor" />}
              {running ? '停止评测' : '开始评测'}
            </button>
            <button type="button" className="preview-button" onClick={previewDsl} disabled={previewing || running}>
              {previewing ? '编译中...' : '预览状态机'}
            </button>
            <div className="batch-hint">
              <small>支持批量评测：POST /api/batch-evaluate</small>
              <small>多任务并发 · JSON/API接入 · 最多20条/次</small>
            </div>
          </aside>

          <details className="api-docs-panel">
            <summary>API 接入文档 & 版本对比</summary>
            <div className="api-docs-content">
              <div className="api-section">
                <h4>批量评测 API</h4>
                <pre className="api-code">{`POST /api/batch-evaluate
Content-Type: application/json

{
  "tasks": [
    {"instruction": "任务指令文本1", "budget": 12},
    {"instruction": "任务指令文本2", "budget": 12}
  ],
  "config": {
    "max_turns": 6,
    "warmup_ratio": 0.6,
    "parallel": true
  }
}

Response 200:
{
  "batch_id": "batch_20260607_001",
  "status": "completed",
  "results": [
    {
      "task_id": "task_001",
      "score": 59.8,
      "pass_status": "CAPPED_P1",
      "coverage": {...},
      "report_url": "/reports/batch_20260607_001/task_001.json"
    }
  ],
  "summary": {
    "avg_score": 62.3,
    "pass_rate": 0.4,
    "common_failures": ["p1_no_verification_path"]
  }
}`}</pre>
              </div>
              <div className="api-section">
                <h4>A/B 版本对比评测</h4>
                <p className="api-desc">对比不同版本数字人在相同任务集下的覆盖率、违规数和评分差异</p>
                <pre className="api-code">{`POST /api/compare
{
  "instruction": "任务指令文本",
  "model_a": {"name": "v2.1", "endpoint": "..."},
  "model_b": {"name": "v2.2", "endpoint": "..."},
  "scenarios": 12
}

Response:
{
  "model_a": {"score": 48.5, "p0": 0, "p1": 2, "edge_coverage": 0.56},
  "model_b": {"score": 67.2, "p0": 0, "p1": 1, "edge_coverage": 0.72},
  "improvements": [
    "v2.2 新增身份验证话术 → p1_no_verification_path 消除",
    "v2.2 边覆盖提升16%：busy_handling→closing 路径打通"
  ]
}`}</pre>
              </div>
            </div>
          </details>
        </form>
      )}
    </section>
  )
}
