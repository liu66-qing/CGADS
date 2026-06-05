import { useRef } from 'react'
import { useEvaluationStore } from '../store/evaluationStore'
import { API_BASE, getEvaluations, getReportJson, getReportMarkdown } from '../api'

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
  const resetRun = useEvaluationStore((s) => s.resetRun)
  const setRunning = useEvaluationStore((s) => s.setRunning)
  const handleEvent = useEvaluationStore((s) => s.handleEvent)
  const setReportMarkdown = useEvaluationStore((s) => s.setReportMarkdown)
  const setReportJson = useEvaluationStore((s) => s.setReportJson)
  const setEvaluations = useEvaluationStore((s) => s.setEvaluations)
  const setBackendStatus = useEvaluationStore((s) => s.setBackendStatus)

  const start = async (instruction: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    resetRun()

    try {
      const response = await fetch(`${API_BASE}/api/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction, budget: 8, warmup_ratio: 0.5, max_turns: 10 }),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await streamEvents(response, handleEvent)
      try {
        const [report, reportJson, evaluations] = await Promise.all([
          getReportMarkdown(),
          getReportJson(),
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
        handleEvent('stage_error', { stage: 'parsing', error: (error as Error).message })
      }
    } finally {
      setRunning(false)
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    setRunning(false)
  }

  return { start, stop }
}
