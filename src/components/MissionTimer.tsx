import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface MissionTimerProps {
  deadlineAt: string | null
  // Режим отсчёта:
  // 'deadline' — общий дедлайн выполнения миссии (по умолчанию);
  // 'cancel' — окно отказа (cancel_deadline_at): после истечения отказ
  //   больше не возвращает плату, текст меняется на «ВРЕМЯ НА ОТКАЗ ИСТЕКЛО».
  mode?: 'deadline' | 'cancel'
  // Опциональная подпись (например, «до конца задания»).
  label?: string
  // Опциональный обработчик: если задан и время вышло — таймер кликабелен.
  onClick?: () => void
}

function formatRemaining(ms: number): string {
  if (ms <= 0) return '00:00'
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (h > 0) {
    return `${h}:${pad(m)}:${pad(s)}`
  }
  return `${pad(m)}:${pad(s)}`
}

export function MissionTimer({
  deadlineAt,
  mode = 'deadline',
  label,
  onClick,
}: MissionTimerProps) {
  const { t } = useTranslation(['terminal'])
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!deadlineAt) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [deadlineAt])

  if (!deadlineAt) return null

  const deadlineMs = new Date(deadlineAt).getTime()
  if (!Number.isFinite(deadlineMs)) return null

  const remaining = deadlineMs - now
  const isExpired = remaining <= 0
  const isCritical = !isExpired && remaining < 60_000

  const className = [
    'mission-timer',
    isExpired ? 'mission-timer-expired' : '',
    isCritical ? 'mission-timer-critical' : '',
  ].filter(Boolean).join(' ')

  const isClickable = isExpired && onClick !== undefined

  // В режиме 'cancel' — отдельный текст: после истечения окна отказ
  // уже не возвращает плату.
  const expiredLabel =
    mode === 'cancel'
      ? t('terminal:timer.expiredRefund')
      : t('terminal:timer.expired')
  const actionLabel = mode === 'cancel'
    ? t('terminal:timer.refuseAction')
    : t('terminal:timer.removeAction')

  return (
    <div
      className={`${className}${isClickable ? ' mission-timer-clickable' : ''}`}
      onClick={isClickable ? onClick : undefined}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
    >
      <span className="mission-timer-icon">⏱</span>
      <span className="mission-timer-value">
        {isExpired ? expiredLabel : formatRemaining(remaining)}
      </span>
      {isClickable && <span className="mission-timer-action">{actionLabel}</span>}
      {label && <span className="mission-timer-label">{label}</span>}
    </div>
  )
}
