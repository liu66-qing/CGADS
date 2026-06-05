export type PipelineStage = 'parsing' | 'dsl_compile' | 'scenario_gen' | 'dialogue' | 'scoring'
export type StepStatus = 'idle' | 'running' | 'done' | 'error'

export type SseEvent =
  | 'stage_start'
  | 'stage_complete'
  | 'stage_error'
  | 'cgads_round'
  | 'cgads_gaps'
  | 'coverage_update'
  | 'scenario_complete'
  | 'pipeline_complete'

export interface StateNode {
  id: string
  label: string
  terminal?: boolean
  entry?: boolean
}

export interface StateEdge {
  from: string
  to: string
  label?: string
}

export interface PipelineStep {
  id: PipelineStage
  title: string
  subtitle: string
  status: StepStatus
  duration?: number
  result?: Record<string, unknown>
  error?: string
}

export interface CoverageState {
  state: number
  edge: number
  risk: number
  requirement: number
}

export interface ScenarioSummary {
  id: string
  turns: number
  score: number
  p0: number
  p1: number
}

export interface TimelineItem {
  id: string
  kind: 'p0' | 'p1' | 'transition' | 'coverage' | 'round' | 'gap'
  title: string
  detail: string
  meta?: string
}

export interface ScoreState {
  totalScore: number
  passStatus: string
  dimensionScores: Record<string, number>
  violations: Array<Record<string, unknown>>
  scenarios: ScenarioSummary[]
  suggestions: string[]
}
