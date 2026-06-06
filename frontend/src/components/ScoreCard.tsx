import { ShieldAlert } from 'lucide-react'
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer } from 'recharts'
import { useEvaluationStore } from '../store/evaluationStore'
import { CoverageDashboard } from './CoverageDashboard'
import { ThemeIcon } from './ThemeIcon'

const dimensionMap: Record<string, string> = {
  task_completion: '任务完成',
  flow_state_adherence: '流程遵循',
  constraint_compliance: '约束合规',
  branch_handling: '分支处理',
  context_consistency: '上下文一致',
  communication_experience: '沟通体验',
}

const toHundred = (value: number) => (value <= 5 ? value * 20 : value)

export function ScoreCard() {
  const score = useEvaluationStore((s) => s.score)
  const coverage = useEvaluationStore((s) => s.coverage)
  const data = Object.entries(dimensionMap).map(([key, label]) => ({
    subject: label,
    value: toHundred(score.dimensionScores[key] ?? 0),
  }))
  const passClass = score.passStatus === 'PASS' ? 'pass' : score.passStatus === 'WAITING' ? 'waiting' : 'fail'

  return (
    <section className="panel score-panel plugin-panel">
      <header className="section-head">
        <div>
          <h2>评测结论</h2>
          <p>数字人本次评测的综合得分、维度分析和覆盖率</p>
        </div>
      </header>
      <div className="score-layout">
        <div className="score-total plugin-card">
          <ThemeIcon name="score" size={42} />
          <span>综合得分</span>
          <strong>{score.totalScore || '--'}<em>/100</em></strong>
          <b className={passClass}>{score.passStatus}</b>
          <small>结合覆盖率 {Math.round((coverage.state + coverage.edge + coverage.risk + coverage.requirement) / 4)}%</small>
        </div>
        <div className="radar-box plugin-card">
          <ResponsiveContainer width="100%" height={220}>
            <RadarChart data={data}>
              <PolarGrid />
              <PolarAngleAxis dataKey="subject" tick={{ fontSize: 12, fill: '#344054' }} />
              <Radar dataKey="value" stroke="#2563eb" fill="#2563eb" fillOpacity={0.18} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <div className="dimension-bars plugin-card">
          {data.map((item) => (
            <label key={item.subject}>
              <span>{item.subject}</span>
              <i><b style={{ width: `${item.value}%` }} /></i>
              <em>{item.value}</em>
            </label>
          ))}
        </div>
      </div>
      <CoverageDashboard />
      <div className="violation-table plugin-card">
        <h3><ShieldAlert size={16} /> 评分详情</h3>
        {score.violations.length ? score.violations.slice(0, 5).map((item, index) => (
          <div key={index}>
            <span className={index === 0 ? 'hot' : ''}>违规</span>
            <b>{String(item.rule_id ?? 'rule')}</b>
            <small>{String(item.scenario ?? 'scenario')}</small>
          </div>
        )) : (
          <div className="violation-empty">
            <span>待测</span>
            <b>等待评测完成</b>
            <small />
          </div>
        )}
      </div>
    </section>
  )
}
