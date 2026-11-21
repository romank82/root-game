import { useEffect, useRef, useState } from 'react'

interface CooldownCountdownProps {
  availableAgainAt: string
  // Вызывается один раз, когда счётчик дошёл до нуля. Сервер снимает перерыв
  // ЛЕНИВО — только внутри запроса клиента, — поэтому без этого колбэка
  // «00:00:00:00» висит на экране, пока игрок не перезапустит приложение.
  onExpire?: () => void
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
 * На нуле вызывает onExpire (если передан): сервер переводит миссию в
 * available только по запросу клиента, поэтому счётчик обязан разбудить его
 * сам. Повторно не вызывает — на каждый availableAgainAt ровно один раз.
 */
export function CooldownCountdown({
  availableAgainAt,
  onExpire,
}: CooldownCountdownProps) {
  const [now, setNow] = useState(() => Date.now())
  const firedForRef = useRef<string | null>(null)

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const targetMs = new Date(availableAgainAt).getTime()
  const expired = Number.isFinite(targetMs) && targetMs - now <= 0

  useEffect(() => {
    if (!onExpire || !expired) return
    // Один вызов на конкретный availableAgainAt: новый перерыв — новое время,
    // значит счётчик снова имеет право сработать.
    if (firedForRef.current === availableAgainAt) return
    firedForRef.current = availableAgainAt
    onExpire()
  }, [expired, availableAgainAt, onExpire])

  if (!Number.isFinite(targetMs)) return null

  return (
    <span className="cooldown-countdown">
      {formatCountdown(targetMs - now)}
    </span>
  )
}
