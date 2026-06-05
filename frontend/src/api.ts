import type { StateEdge, StateNode } from './types'

export const API_BASE = 'http://localhost:8000'

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

export function getReportMarkdown() {
  return requestJson<{ markdown: string }>('/api/report')
}

export function getReportJson() {
  return requestJson<Record<string, unknown>>('/api/report?format=json')
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
