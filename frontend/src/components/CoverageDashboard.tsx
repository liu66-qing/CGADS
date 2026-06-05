import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { useEvaluationStore } from '../store/evaluationStore'
import { ThemeIcon } from './ThemeIcon'

const labels = [
  ['state', '状态覆盖'],
  ['edge', '边覆盖'],
  ['risk', '风险覆盖'],
  ['requirement', '要求覆盖'],
] as const

const colorFor = (value: number) => (value >= 80 ? '#2196F3' : value >= 60 ? '#FF8A00' : '#F44336')

export function CoverageDashboard() {
  const coverage = useEvaluationStore((s) => s.coverage)
  return (
    <div className="coverage-grid">
      {labels.map(([key, label]) => {
        const value = coverage[key]
        return (
          <article className="coverage-ring plugin-card" key={key}>
            <ThemeIcon name="coverage" size={22} className="coverage-mini-icon" />
            <ResponsiveContainer width="100%" height={92}>
              <PieChart>
                <Pie data={[{ value }, { value: 100 - value }]} innerRadius={30} outerRadius={40} startAngle={90} endAngle={-270} dataKey="value">
                  <Cell fill={colorFor(value)} />
                  <Cell fill="#e8edf5" />
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
