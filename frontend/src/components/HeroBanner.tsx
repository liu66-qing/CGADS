import { useEffect, useState } from 'react'

export function HeroBanner() {
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    const onScroll = () => setCollapsed(window.scrollY > 96)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <section className={`hero-stage ${collapsed ? 'collapsed' : ''}`} aria-label="外呼评测系统 作品封面">
      <div className="hero-safe-frame" />
    </section>
  )
}
