import { create } from 'zustand'
import type { CoverageState, PipelineStage, PipelineStep, ScoreState, StateEdge, StateNode, StepStatus, TimelineItem } from '../types'

const stages: PipelineStep[] = [
  { id: 'parsing', title: '指令解析', subtitle: '提取角色 / 目标 / 约束', status: 'idle' },
  { id: 'dsl_compile', title: 'DSL 编译', subtitle: '任务变状态机', status: 'idle' },
  { id: 'scenario_gen', title: '场景生成', subtitle: 'CGADS 覆盖补洞', status: 'idle' },
  { id: 'dialogue', title: '对话模拟', subtitle: '多画像多轮试炼', status: 'idle' },
  { id: 'scoring', title: '评测评分', subtitle: '证据链裁决', status: 'idle' },
]

const emptyScore: ScoreState = {
  totalScore: 0,
  passStatus: 'WAITING',
  dimensionScores: {},
  violations: [],
  scenarios: [],
  suggestions: [],
}

interface EvaluationStore {
  instruction: string
  running: boolean
  activeStage: PipelineStage
  pipeline: PipelineStep[]
  coverage: CoverageState
  states: StateNode[]
  edges: StateEdge[]
  visitedStates: Set<string>
  currentState?: string
  score: ScoreState
  timeline: TimelineItem[]
  rounds: Array<Record<string, unknown>>
  gaps: unknown[]
  reportOpen: boolean
  setInstruction: (instruction: string) => void
  resetRun: () => void
  setRunning: (running: boolean) => void
  setReportOpen: (open: boolean) => void
  handleEvent: (event: string, data: any) => void
}

const normalizeStage = (stage: string): PipelineStage => {
  if (stage === 'dsl') return 'dsl_compile'
  if (stage === 'scenario') return 'scenario_gen'
  if (stage === 'dialogue') return 'dialogue'
  return stage as PipelineStage
}

const setStep = (pipeline: PipelineStep[], stage: PipelineStage, status: StepStatus, patch: Partial<PipelineStep> = {}) =>
  pipeline.map((step) => (step.id === stage ? { ...step, status, ...patch } : step))

const pct = (value: unknown) => {
  const n = typeof value === 'number' ? value : Number(value ?? 0)
  return n > 1 ? Math.round(n) : Math.round(n * 100)
}

export const useEvaluationStore = create<EvaluationStore>((set) => ({
  instruction: '',
  running: false,
  activeStage: 'parsing',
  pipeline: stages,
  coverage: { state: 0, edge: 0, risk: 0, requirement: 0 },
  states: [],
  edges: [],
  visitedStates: new Set(),
  score: emptyScore,
  timeline: [],
  rounds: [],
  gaps: [],
  reportOpen: false,
  setInstruction: (instruction) => set({ instruction }),
  setRunning: (running) => set({ running }),
  setReportOpen: (reportOpen) => set({ reportOpen }),
  resetRun: () =>
    set({
      running: true,
      activeStage: 'parsing',
      pipeline: stages.map((s) => ({ ...s, status: 'idle', duration: undefined, result: undefined, error: undefined })),
      coverage: { state: 0, edge: 0, risk: 0, requirement: 0 },
      states: [],
      edges: [],
      visitedStates: new Set(),
      currentState: undefined,
      score: emptyScore,
      timeline: [],
      rounds: [],
      gaps: [],
      reportOpen: false,
    }),
  handleEvent: (event, data) => {
    const stage = normalizeStage(data?.stage)
    if (event === 'stage_start') {
      set((state) => ({ activeStage: stage, pipeline: setStep(state.pipeline, stage, 'running') }))
      return
    }
    if (event === 'stage_error') {
      set((state) => ({ running: false, activeStage: stage, pipeline: setStep(state.pipeline, stage, 'error', { error: data.error }) }))
      return
    }
    if (event === 'stage_complete') {
      set((state) => {
        const next: Partial<EvaluationStore> = {
          pipeline: setStep(state.pipeline, stage, 'done', { duration: data.duration_s, result: data.result }),
        }
        if (stage === 'dsl_compile') {
          next.states = data.result?.states ?? []
          next.edges = data.result?.edges ?? []
        }
        if (stage === 'scenario_gen') {
          next.pipeline = setStep(next.pipeline!, 'dialogue', 'done', { result: { scenario_count: data.result?.total_scenarios } })
        }
        if (stage === 'scoring') {
          next.score = {
            ...state.score,
            totalScore: data.result?.total_score ?? 0,
            passStatus: data.result?.pass_status ?? 'WAITING',
            dimensionScores: data.result?.dimension_scores ?? {},
            violations: data.result?.violations ?? [],
          }
        }
        return next
      })
      return
    }
    if (event === 'cgads_round') {
      set((state) => ({
        rounds: [...state.rounds, data],
        timeline: [
          ...state.timeline,
          {
            id: `round-${data.round}-${state.timeline.length}`,
            kind: 'round',
            title: `Round ${data.round} ${data.type === 'warmup' ? '热身探路' : '定向补洞'}`,
            detail: `生成 ${data.scenario_count} 个场景，目标覆盖 ${(data.scenarios ?? []).slice(0, 3).map((s: any) => s.name).join('、')}`,
            meta: 'CGADS',
          },
        ],
      }))
      return
    }
    if (event === 'cgads_gaps') {
      set((state) => ({
        gaps: data.gaps ?? [],
        timeline: [...state.timeline, { id: `gap-${state.timeline.length}`, kind: 'gap', title: `发现 ${data.gap_count} 个覆盖缺口`, detail: '系统将反向生成用户画像和话术分支补测。', meta: 'gap scan' }],
      }))
      return
    }
    if (event === 'coverage_update') {
      set((state) => ({
        coverage: { state: pct(data.state), edge: pct(data.edge), risk: pct(data.risk), requirement: pct(data.requirement) },
        timeline: [...state.timeline, { id: `coverage-${state.timeline.length}`, kind: 'coverage', title: `覆盖命中 ${data.scenario_id}`, detail: `状态 ${pct(data.state)}% / 边 ${pct(data.edge)}% / 风险 ${pct(data.risk)}% / 要求 ${pct(data.requirement)}%`, meta: 'coverage' }],
      }))
      return
    }
    if (event === 'scenario_complete') {
      set((state) => ({
        score: {
          ...state.score,
          scenarios: [...state.score.scenarios, { id: data.scenario_id, turns: data.turns, score: data.score, p0: data.p0_count, p1: data.p1_count }],
        },
        timeline: [
          ...state.timeline,
          { id: `scenario-${state.timeline.length}`, kind: data.p0_count ? 'p0' : data.p1_count ? 'p1' : 'transition', title: `${data.scenario_id} 完成`, detail: `${data.turns} 轮对话，得分 ${data.score}，P0 ${data.p0_count} / P1 ${data.p1_count}`, meta: 'scenario' },
        ],
      }))
      return
    }
    if (event === 'pipeline_complete') {
      set((state) => ({
        running: false,
        reportOpen: true,
        score: {
          totalScore: data.total_score ?? 0,
          passStatus: data.pass_status ?? 'WAITING',
          dimensionScores: data.dimension_scores ?? {},
          violations: data.violations ?? [],
          scenarios: data.scenarios ?? state.score.scenarios,
          suggestions: data.suggestions ?? [],
        },
      }))
    }
  },
}))
