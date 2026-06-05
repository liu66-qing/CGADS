import { Gauge, GitBranch, ShieldCheck, Target } from 'lucide-react'

const traits = [
  { icon: GitBranch, title: '状态驱动', desc: '指令编译成可测状态机' },
  { icon: Gauge, title: '多维指标', desc: '覆盖率与质量同步读数' },
  { icon: ShieldCheck, title: '规则可控', desc: 'P0/P1 门槛可解释' },
  { icon: Target, title: '漏洞补测', desc: '从缺口反向生成场景' },
]

export function HeroBanner() {
  return (
    <section className="hero-stage" aria-label="橙脉 CGADS 作品封面">
      <div className="hero-copy">
        <p className="hack-tag">HACKATHON · 命题二 · 外呼任务对话模型评测</p>
        <h2>橙脉 CGADS</h2>
        <h3>外呼指令状态机试炼场</h3>
        <p className="hero-subtitle">Outbound Dialogue State-Machine Evaluation Arena</p>
        <div className="trait-row">
          {traits.map(({ icon: Icon, title, desc }) => (
            <article key={title}>
              <Icon size={24} />
              <b>{title}</b>
              <span>{desc}</span>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
