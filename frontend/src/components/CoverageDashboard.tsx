import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { useEvaluationStore } from '../store/evaluationStore'

const labels = [
  ['state', '状态覆盖'],
  ['edge', '边覆盖'],
  ['risk', '风险覆盖'],
  ['requirement', '要求覆盖'],
] as const

const colorFor = (value: number) => (value >= 80 ? '#FF8C00' : value >= 60 ? '#64748b' : '#94a3b8')

export function CoverageDashboard() {
  const coverage = useEvaluationStore((s) => s.coverage)
  return (
    <div className="coverage-grid">
      {labels.map(([key, label]) => {
        const value = coverage[key]
        return (
          <article className="coverage-ring" key={key}>
            <ResponsiveContainer width="100%" height={80}>
              <PieChart>
                <Pie data={[{ value }, { value: 100 - value }]} innerRadius={26} outerRadius={34} startAngle={90} endAngle={-270} dataKey="value">
                  <Cell fill={colorFor(value)} />
                  <Cell fill="#E5E7EB" />
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <b>{value}%</b>
            <span>{label}</span>
          </article>
        )
      })}
    </div>
  )
}
