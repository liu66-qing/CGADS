type IconName = 'state' | 'coverage' | 'score' | 'timeline' | 'report' | 'scenario' | 'team' | 'bell' | 'chat'

interface ThemeIconProps {
  name: IconName
  size?: number
  className?: string
}

export function ThemeIcon({ name, size = 24, className = '' }: ThemeIconProps) {
  return (
    <svg className={`theme-icon ${className}`} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <defs>
        <linearGradient id={`orange-blue-${name}`} x1="10" y1="8" x2="54" y2="56">
          <stop stopColor="#ff9d1b" />
          <stop offset="1" stopColor="#2196f3" />
        </linearGradient>
      </defs>
      {name === 'state' && (
        <>
          <path d="M13 18h14v14H13zM37 12h14v14H37zM37 38h14v14H37z" fill="#071322" stroke={`url(#orange-blue-${name})`} strokeWidth="4" />
          <path d="M27 25h10M27 25c8 0 10 13 10 20" stroke="#ff8a00" strokeWidth="4" strokeLinecap="round" />
        </>
      )}
      {name === 'coverage' && (
        <>
          <circle cx="32" cy="32" r="20" fill="none" stroke="#071322" strokeWidth="9" />
          <path d="M32 12a20 20 0 1 1-18 28" fill="none" stroke="#ff8a00" strokeWidth="9" strokeLinecap="round" />
          <circle cx="32" cy="32" r="7" fill="#2196f3" />
        </>
      )}
      {name === 'score' && (
        <>
          <path d="m32 9 22 16v24H10V25L32 9Z" fill="#071322" stroke={`url(#orange-blue-${name})`} strokeWidth="4" />
          <path d="m20 43 8-12 8 7 9-16" fill="none" stroke="#ffb020" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {name === 'timeline' && (
        <>
          <path d="M18 10v44" stroke="#071322" strokeWidth="6" strokeLinecap="round" />
          <circle cx="18" cy="16" r="7" fill="#ff8a00" /><circle cx="18" cy="32" r="7" fill="#2196f3" /><circle cx="18" cy="48" r="7" fill="#16a34a" />
          <path d="M30 16h20M30 32h17M30 48h22" stroke="#071322" strokeWidth="5" strokeLinecap="round" />
        </>
      )}
      {name === 'report' && (
        <>
          <path d="M18 8h22l8 8v40H18z" fill="#071322" stroke={`url(#orange-blue-${name})`} strokeWidth="4" />
          <path d="M39 9v10h10M25 30h16M25 40h12" stroke="#ffb020" strokeWidth="4" strokeLinecap="round" />
        </>
      )}
      {name === 'scenario' && (
        <>
          <path d="M13 38c8-18 27-28 39-20-1 18-14 31-33 33l5-12-11-1Z" fill="#071322" stroke={`url(#orange-blue-${name})`} strokeWidth="4" />
          <circle cx="40" cy="24" r="4" fill="#ff8a00" />
          <path d="M16 17h10M21 12v10" stroke="#2196f3" strokeWidth="4" strokeLinecap="round" />
        </>
      )}
      {name === 'team' && (
        <>
          <circle cx="24" cy="23" r="9" fill="#071322" stroke="#ff8a00" strokeWidth="4" />
          <circle cx="42" cy="27" r="7" fill="#071322" stroke="#2196f3" strokeWidth="4" />
          <path d="M11 52c3-12 22-16 31-5 4-5 12-6 17 1" fill="none" stroke="#071322" strokeWidth="6" strokeLinecap="round" />
        </>
      )}
      {name === 'bell' && (
        <>
          <path d="M20 43V28c0-8 5-14 12-14s12 6 12 14v15l6 7H14l6-7Z" fill="#071322" stroke={`url(#orange-blue-${name})`} strokeWidth="4" />
          <path d="M27 53c2 5 8 5 10 0" stroke="#ffb020" strokeWidth="4" strokeLinecap="round" />
        </>
      )}
      {name === 'chat' && (
        <>
          <path d="M12 14h40v28H26l-10 10V42H12V14Z" fill="#071322" stroke={`url(#orange-blue-${name})`} strokeWidth="4" />
          <path d="M22 26h20M22 34h14" stroke="#ff8a00" strokeWidth="4" strokeLinecap="round" />
        </>
      )}
    </svg>
  )
}
