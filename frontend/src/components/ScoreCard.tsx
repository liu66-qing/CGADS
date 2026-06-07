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
const suggestionToText = (suggestion: unknown) => {
  if (!suggestion) return ''
  if (typeof suggestion === 'string') return suggestion
  if (typeof suggestion !== 'object') return String(suggestion)
  const item = suggestion as Record<string, unknown>
  return [item.title, item.problem, item.action]
    .filter((part): part is string => typeof part === 'string' && part.trim().length > 0)
    .join('：')
}

export function ScoreCard() {
  const score = useEvaluationStore((s) => s.score)
  const coverage = useEvaluationStore((s) => s.coverage)
  const dialogues = useEvaluationStore((s) => s.dialogues)
  const running = useEvaluationStore((s) => s.running)
  const data = Object.entries(dimensionMap).map(([key, label]) => ({
    subject: label,
    value: toHundred(score.dimensionScores[key] ?? 0),
  }))
  const passClass = score.passStatus === 'PASS' ? 'pass' : score.passStatus === 'WAITING' ? 'waiting' : 'fail'
  const scenarioCount = score.scenarios.length
  const personaCount = new Set(
    score.scenarios
      .map((scenario) => dialogues[scenario.id]?.persona)
      .filter((persona): persona is string => Boolean(persona)),
  ).size
  const requirementCoverage = Math.round(coverage.requirement)
  const riskCoverage = Math.round(coverage.risk)
  const sufficient = scenarioCount > 0 && requirementCoverage >= 70 && riskCoverage >= 60 && score.passStatus === 'PASS'
  const supplementHint = suggestionToText(score.suggestions[0]) || '需优先补充身份真实性、官方渠道、拒绝后继续营销等P0/P1风险场景。'
  const summaryText = scenarioCount
    ? `本次评测覆盖${scenarioCount}个场景/${personaCount || scenarioCount}类用户画像，业务需求覆盖${requirementCoverage}%，风险覆盖${riskCoverage}%，评测充分性：${sufficient ? '充分' : '未充分'}。${sufficient ? '当前结果可作为上线采信参考。' : supplementHint}`
    : running
      ? '评测进行中，场景正在执行，结论将在完成后自动更新。'
      : '本次评测尚未启动，暂无任务要求覆盖、风险覆盖和采信充分性结论。'

  return (
    <section className="panel score-panel plugin-panel">
      <header className="section-head">
        <div>
          <h2>评测结论</h2>
          <p>数字人本次评测的综合得分、维度分析和覆盖率</p>
        </div>
      </header>
      <div className="evaluation-summary plugin-card">
        <span>评测摘要</span>
        <strong>{summaryText}</strong>
      </div>
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
        )) : score.passStatus === 'PASS' ? (
          <div className="violation-empty">
            <span>通过</span>
            <b>未发现P0/P1违规</b>
            <small>仍建议结合风险覆盖率复核采信充分性</small>
          </div>
        ) : scenarioCount ? (
          <div className="violation-empty">
            <span>未充分</span>
            <b>暂无直接违规，需补齐风险覆盖</b>
            <small>重点检查身份验证、拒绝退出、承诺类话术</small>
          </div>
        ) : (
          <div className="violation-empty">
            <span>待测</span>
            <b>等待评测完成</b>
            <small />
          </div>
        )}
      </div>
      {score.scoringBreakdown && (
        <details className="scoring-breakdown plugin-card">
          <summary><h3 style={{ display: 'inline', fontSize: '14px' }}>评分计算明细</h3></summary>
          <p className="formula-hint">{score.scoringBreakdown.formula}</p>
          <table className="breakdown-table">
            <thead>
              <tr><th>维度</th><th>得分</th><th>权重</th><th>贡献</th></tr>
            </thead>
            <tbody>
              {score.scoringBreakdown.dimensions.map((d) => (
                <tr key={d.dimension}>
                  <td>{dimensionMap[d.dimension] ?? d.dimension}</td>
                  <td>{d.score}/{d.max}</td>
                  <td>{d.weight}%</td>
                  <td>{d.contribution}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr><td colSpan={3}>原始总分</td><td><strong>{score.scoringBreakdown.raw_score}</strong></td></tr>
              <tr><td colSpan={3}>封顶规则</td><td>{score.scoringBreakdown.cap_rule}</td></tr>
              <tr><td colSpan={3}>最终得分</td><td><strong>{score.scoringBreakdown.final_score}</strong></td></tr>
            </tfoot>
          </table>
        </details>
      )}
      {score.credibilityBoundary && (
        <div className="credibility-boundary plugin-card">
          <h3>采信边界</h3>
          {score.round2Info && score.round2Info.skipped_reason && (
            <div className="cb-section cb-info">
              <span>补测执行</span>
              <p>Round2 计划 {score.round2Info.planned} 场景，实际执行 {score.round2Info.executed} 场景（{score.round2Info.skipped_reason === 'timeout' ? '超时截断' : score.round2Info.skipped_reason}）</p>
            </div>
          )}
          {score.credibilityBoundary.can_conclude.length > 0 && (
            <div className="cb-section cb-can">
              <span>可采信</span>
              <ul>{score.credibilityBoundary.can_conclude.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}
          {score.credibilityBoundary.cannot_conclude.length > 0 && (
            <div className="cb-section cb-cannot">
              <span>需补测</span>
              <ul>{score.credibilityBoundary.cannot_conclude.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}
          <div className="cb-recommendation">
            <strong>{score.credibilityBoundary.recommendation}</strong>
          </div>
        </div>
      )}
    </section>
  )
}
