import { useRef } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'
import { API_BASE, cancelEvaluationJob, createEvaluationJob, getEvaluations, getReportJson, getReportMarkdown } from '../api'

async function streamEvents(response: Response, onEvent: (event: string, data: any) => void) {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('SSE stream is unavailable')
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''

    for (const chunk of chunks) {
      const event = chunk.match(/^event:\s*(.+)$/m)?.[1]?.trim()
      const dataLine = chunk.match(/^data:\s*(.+)$/m)?.[1]
      if (!event || !dataLine) continue
      onEvent(event, JSON.parse(dataLine))
    }
  }
}

export function useEvaluationSse() {
  const abortRef = useRef<AbortController | null>(null)
  const jobRef = useRef<string | null>(null)
  const resetRun = useEvaluationStore((s) => s.resetRun)
  const setRunning = useEvaluationStore((s) => s.setRunning)
  const handleEvent = useEvaluationStore((s) => s.handleEvent)
  const setReportMarkdown = useEvaluationStore((s) => s.setReportMarkdown)
  const setReportJson = useEvaluationStore((s) => s.setReportJson)
  const setEvaluations = useEvaluationStore((s) => s.setEvaluations)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)

  const start = async (instruction: string, demoMode: boolean = false) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    resetRun()

    try {
      let response: Response
      let evalId: string | undefined

      if (demoMode) {
        response = await fetch(`${API_BASE}/api/demo?task_id=task_001_rider_flying_leg`, {
          method: 'GET',
          signal: controller.signal,
        })
      } else {
        try {
          const job = await createEvaluationJob(instruction)
          jobRef.current = job.job_id
          response = await fetch(`${API_BASE}/api/evaluate/jobs/${encodeURIComponent(job.job_id)}/events`, {
            method: 'GET',
            signal: controller.signal,
          })
        } catch {
          response = await fetch(`${API_BASE}/api/evaluate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instruction, budget: 12, warmup_ratio: 0.35, max_turns: 8 }),
            signal: controller.signal,
          })
        }
      }

      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await streamEvents(response, (event, data) => {
        if (event === 'pipeline_complete' && data?.eval_id) evalId = data.eval_id
        handleEvent(event, data)
      })

      try {
        const [report, reportJson, evaluations] = await Promise.all([
          getReportMarkdown(evalId),
          getReportJson(evalId),
          getEvaluations(),
        ])
        setReportMarkdown(report.markdown ?? '')
        setReportJson(reportJson)
        setEvaluations(evaluations.evaluations ?? [])
        setBackendStatus('ok')
      } catch {
        setBackendStatus('offline')
      }
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        handleEvent('stage_error', { stage: 'pipeline', error: (error as Error).message })
      }
    } finally {
      jobRef.current = null
      setRunning(false)
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    if (jobRef.current) {
      void cancelEvaluationJob(jobRef.current).catch(() => undefined)
      jobRef.current = null
    }
    setRunning(false)
  }

  return { start, stop }
}
