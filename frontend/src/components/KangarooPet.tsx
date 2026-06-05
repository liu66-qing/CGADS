interface KangarooPetProps {
  mood?: 'idle' | 'working' | 'done'
}

export function KangarooPet({ mood = 'idle' }: KangarooPetProps) {
  return (
    <div className={`kangaroo-pet ${mood}`} aria-label="报告生成提示袋鼠">
      <svg viewBox="0 0 180 180" role="img">
        <path className="tail" d="M45 127c-18 11-31 15-39 9 20-3 31-14 41-31" />
        <path className="body" d="M64 123c-3-32 11-61 35-72 19-9 42 2 49 22 6 18-1 40-17 51l20 30h-28l-16-19c-13 4-27 2-43-12Z" />
        <path className="ear" d="M101 52 116 18l5 34M119 52l24-23-7 34" />
        <circle className="face" cx="116" cy="71" r="24" />
        <circle className="eye" cx="126" cy="65" r="4" />
        <path className="snout" d="M133 78c9 2 17 7 19 13-9 3-18 1-25-6" />
        <path className="leg" d="M78 130 59 163h28l20-26" />
        <path className="arm" d="M93 104c16 1 28 8 35 19" />
        <path className="helmet" d="M91 53c10-17 38-20 55-4-15-3-35-1-55 4Z" />
        <path className="headset" d="M146 73c10 7 11 20 2 28M145 101h-18" />
        <circle className="pulse" cx="46" cy="84" r="8" />
        <path className="node-link" d="M54 84h25l14 14" />
      </svg>
      <div className="pet-bubble">
        {mood === 'working' ? '报告正在生成，我会把证据链串起来。' : mood === 'done' ? '报告已就绪，可以展开查看。' : '开始评测后，我会在这里提示报告进度。'}
      </div>
    </div>
  )
}
