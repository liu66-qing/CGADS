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
          <h2>结果面板</h2>
          <p>覆盖、评分和违规证据会在这里汇总</p>
        </div>
        <span className="next-cue">下一步看：证据时间轴</span>
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
              <Radar dataKey="value" stroke="#FF6B00" fill="#FF6B00" fillOpacity={0.22} />
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
        {(score.violations.length ? score.violations : [{ rule_id: '等待证据链', scenario: '评测启动后生成' }]).slice(0, 5).map((item, index) => (
          <div key={index}>
            <span className={index === 0 && score.violations.length ? 'hot' : ''}>{score.violations.length ? '违规' : '待测'}</span>
            <b>{String(item.rule_id ?? 'rule')}</b>
            <small>{String(item.scenario ?? 'scenario')}</small>
          </div>
        ))}
      </div>
    </section>
  )
}
