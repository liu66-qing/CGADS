import { ChevronDown, Database, FileUp, Play, RefreshCw, Sparkles, Square } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
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
  const [batchJobs, setBatchJobs] = useState<Array<{job_id: string; status: string; instruction_preview: string; score?: number}>>([])
  const [jobsLoading, setJobsLoading] = useState(false)

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

  const fetchBatchJobs = useCallback(async () => {
    setJobsLoading(true)
    try {
      const baseUrl = import.meta.env.VITE_API_BASE || ''
      const resp = await fetch(`${baseUrl}/api/batch-evaluate/jobs`)
      if (resp.ok) {
        const data = await resp.json()
        setBatchJobs(data.jobs ?? [])
      }
    } catch { /* backend may not support this yet */ }
    setJobsLoading(false)
  }, [])

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
            <summary>批量评测控制台 & API 接入</summary>
            <div className="api-docs-content">
              <div className="api-section">
                <h4>批量提交</h4>
                <pre className="api-code">{`POST /api/batch-evaluate
{ "tasks": [{"instruction": "任务1"}, {"instruction": "任务2"}],
  "config": {"max_turns": 6, "warmup_ratio": 0.75} }
→ {"batch_id": "batch_001", "status": "queued", "task_count": 2}`}</pre>
              </div>
              <div className="api-section">
                <h4>状态查询 & 失败重试</h4>
                <pre className="api-code">{`GET /api/batch-evaluate/batch_001/status
→ {"status": "partial", "completed": 1, "failed": 1, "pending": 0}

POST /api/batch-evaluate/batch_001/retry
→ {"retried": 1, "status": "running"}`}</pre>
              </div>
              <div className="api-section">
                <h4>批量报告 & 版本对比</h4>
                <pre className="api-code">{`GET /api/batch-evaluate/batch_001/report
→ {"avg_score": 62.3, "pass_rate": 0.4,
   "common_failures": ["p1_no_verification_path"],
   "per_task": [{...}, {...}]}

POST /api/compare
{"instruction": "...", "model_a": "v2.1", "model_b": "v2.2"}
→ {"delta_score": +18.7, "delta_p1": -1,
   "improvements": ["新增身份验证话术→P1消除"]}`}</pre>
              </div>
              <div className="api-section">
                <h4>复测闭环</h4>
                <p className="api-desc">修改数字人prompt后一键复测，对比分数/违规/覆盖变化</p>
                <pre className="api-code">{`POST /api/retest
{"instruction": "...", "baseline_eval_id": "eval_xxx"}
→ {"before": {"score": 48.5, "p1": 2, "risk_cov": 0.75},
   "after":  {"score": 67.2, "p1": 1, "risk_cov": 0.88},
   "diff": "+18.7分, -1个P1, +13%风险覆盖"}`}</pre>
              </div>
            </div>
          </details>

          <details className="api-docs-panel batch-jobs-panel">
            <summary onClick={() => { if (!batchJobs.length) fetchBatchJobs() }}>批量任务列表 & Job 状态</summary>
            <div className="api-docs-content">
              <div className="batch-jobs-header">
                <small>{batchJobs.length} 个任务</small>
                <button type="button" className="refresh-jobs-btn" onClick={fetchBatchJobs} disabled={jobsLoading}>
                  <RefreshCw size={14} className={jobsLoading ? 'spin' : ''} /> 刷新
                </button>
              </div>
              {batchJobs.length > 0 ? (
                <table className="batch-jobs-table">
                  <thead><tr><th>Job ID</th><th>状态</th><th>指令预览</th><th>得分</th></tr></thead>
                  <tbody>
                    {batchJobs.map((job) => (
                      <tr key={job.job_id}>
                        <td className="job-id">{job.job_id.slice(0, 8)}</td>
                        <td><span className={`job-status job-${job.status === 'completed' ? 'done' : job.status === 'queued' ? 'pending' : job.status}`}>{job.status}</span></td>
                        <td className="job-preview">{job.instruction_preview}</td>
                        <td>{job.score != null ? `${job.score}分` : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="batch-empty">暂无批量任务。通过 POST /api/batch-evaluate 提交后，任务将显示在此列表中。</p>
              )}
            </div>
          </details>
        </form>
      )}
    </section>
  )
}
