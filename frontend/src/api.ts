import type { StateEdge, StateNode } from './types'

// 生产环境使用环境变量VITE_API_BASE，开发环境通过vite proxy走相对路径
export const API_BASE = import.meta.env.VITE_API_BASE || ''

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export interface StateNamesResponse {
  state_names?: Record<string, string>
  dimension_labels?: Record<string, string>
}

export interface DslCompileResponse {
  states?: StateNode[]
  edges?: StateEdge[]
  mermaid?: string
  rules?: unknown[]
  requirements?: unknown[]
}

export interface EvaluationsResponse {
  evaluations?: Array<Record<string, unknown>>
}

export function getHealth() {
  return requestJson<{ status: string; version: string }>('/api/health')
}

export function getExamples() {
  return requestJson<{ examples: Array<{ id: string; name: string; goal?: string }> }>('/api/examples')
}

export function getStateNames() {
  return requestJson<StateNamesResponse>('/api/dsl/state-names')
}

export function compileDslPreview(instruction: string) {
  return requestJson<DslCompileResponse>('/api/dsl/compile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction }),
  })
}

export function getReportMarkdown(evalId?: string) {
  const suffix = evalId ? `?eval_id=${encodeURIComponent(evalId)}` : ''
  return requestJson<{ markdown: string }>(`/api/report${suffix}`)
}

export function getReportJson(evalId?: string) {
  const params = new URLSearchParams({ format: 'json' })
  if (evalId) params.set('eval_id', evalId)
  return requestJson<Record<string, unknown>>(`/api/report?${params.toString()}`)
}

export function getReportDownloadUrl(format: 'markdown' | 'json') {
  return `${API_BASE}/api/report/download?format=${format}`
}

export function getEvaluations() {
  return requestJson<EvaluationsResponse>('/api/evaluations')
}

export function getEvaluation(id: string) {
  return requestJson<Record<string, unknown>>(`/api/evaluations/${encodeURIComponent(id)}`)
}

export function createEvaluationJob(instruction: string) {
  return requestJson<{ job_id: string; status: string }>('/api/evaluate/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction, budget: 4, warmup_ratio: 0.5, max_turns: 6 }),
  })
}

export function cancelEvaluationJob(jobId: string) {
  return requestJson<{ job_id: string; status: string }>(`/api/evaluate/jobs/${encodeURIComponent(jobId)}`, {
    method: 'DELETE',
  })
}
