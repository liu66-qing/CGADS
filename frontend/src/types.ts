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
  dialogueExcerpt?: {
    turn: number
    agentUtterance: string
    userUtterance: string
    ruleName?: string
    ruleMessage?: string
  }
}

export interface DialogueMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ScenarioDialogue {
  scenarioId: string
  messages: DialogueMessage[]
  persona?: string
  violationDetails?: Array<{
    turn: number
    agentUtterance: string
    userUtterance: string
    state: string
    violations: Array<{ rule_name: string; message: string }>
  }>
}

export interface ScoreState {
  totalScore: number
  passStatus: string
  dimensionScores: Record<string, number>
  violations: Array<Record<string, unknown>>
  scenarios: ScenarioSummary[]
  suggestions: Array<string | Record<string, unknown>>
  credibilityBoundary?: {
    adequate: boolean
    can_conclude: string[]
    cannot_conclude: string[]
    uncovered_impact: Array<{ id: string; impact: string; reason: string }>
    recommendation: string
  }
  round2Info?: {
    planned: number
    executed: number
    skipped_reason: string
  }
  scoringBreakdown?: {
    dimensions: Array<{ dimension: string; score: number; max: number; weight: number; contribution: number }>
    raw_score: number
    p0_count: number
    p1_count: number
    cap_rule: string
    final_score: number
    formula: string
  }
}
