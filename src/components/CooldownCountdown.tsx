import { useEffect, useState } from 'react'

interface CooldownCountdownProps {
  availableAgainAt: string
}

function formatCountdown(ms: number): string {
  if (ms <= 0) return '00:00:00:00'
  const total = Math.floor(ms / 1000)
  const d = Math.floor(total / 86400)
  const h = Math.floor((total % 86400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d)}:${pad(h)}:${pad(m)}:${pad(s)}`
}

/**
 * Тикающий обратный отсчёт до момента, когда миссия снова станет доступна.
 * После истечения показывает «00:00:00:00» (bootstrap при следующем
 * обращении переведёт миссию в available).
 */
export function CooldownCountdown({
  availableAgainAt,
}: CooldownCountdownProps) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const targetMs = new Date(availableAgainAt).getTime()
  if (!Number.isFinite(targetMs)) return null

  return (
    <span className="cooldown-countdown">
      {formatCountdown(targetMs - now)}
    </span>
  )
}