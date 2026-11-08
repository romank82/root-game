import { useEffect, useRef, useState, type TouchEvent } from 'react'
import { useTranslation } from 'react-i18next'

// Sprint 8.x-4a: переиспользуемая игровая часть cipher (solo + team).
// Получает готовые данные игры (drums, correctCode, timeLimitSeconds) и НЕ
// знает про mission/cipherSession — подготовку данных держит экран-владелец
// (CipherScreen / TeamSessionScreen). Стили — глобальные классы cipher-* /
// repair-* из App.css (переиспользуются, новых не вводим).
//
// Владеет: вращением барабанов (свайп), показом правильного кода открыто
// (игра на скорость), кнопкой «ГОТОВО →» и таймером попытки. Таймер считает от
// серверного attemptDeadlineAt (Sprint 8.x-attempt-deadline: кнопка «ЗАНОВО»
// удалена, время попытки продлить нельзя), а при его отсутствии — legacy-
// countdown от timeLimitSeconds. При истечении времени сам отправляет пустую
// последовательность (гарантированный
// промах для cipher_match → attempt += 1) и оповещает onTimeout.

export interface CipherGameProps {
  drums: string[][]
  correctCode: string[]
  timeLimitSeconds: number | null
  // Sprint 8.x-attempt-deadline: абсолютный момент окончания ТЕКУЩЕЙ попытки
  // (mission.attemptDeadlineAt из bootstrap). Приоритетнее timeLimitSeconds:
  // пересчитывается от Date.now(), поэтому повторный рендер, повторный вход на
  // экран и смена сессии не продлевают время попытки. null/undefined —
  // legacy-countdown от timeLimitSeconds (миссии без лимита, team-волны).
  attemptDeadlineAt?: string | null
  onSubmit: (sequence: string[]) => void
  isSubmitting?: boolean
  // Внешний сигнал пересборки (новая сессия/волна, новая попытка после
  // промаха): сбрасывает позиции барабанов и пересчитывает таймер от
  // attemptDeadlineAt (а не «на полный лимит»).
  resetSignal?: number
  // Стартовые позиции барабанов на момент сброса (из buildDrums; default 0).
  initialIndices?: number[]
  onTimeout?: () => void
  // @deprecated Sprint 8.x-attempt-deadline: кнопка «ЗАНОВО» удалена, пропс
  // больше не читается. Оставлен только для совместимости с
  // TeamSessionScreen (там он передаётся) — удалить отдельным шагом вместе с
  // handleResetWave.
  onReset?: () => void
  // Опциональные тексты для team-экрана (solo их не передаёт).
  title?: string
  // Текст ошибки последней попытки (рендерится как в CipherScreen solo).
  error?: string | null
}

// Sprint 8.x-attempt-deadline: оставшееся время попытки в секундах.
// Приоритет — серверный attemptDeadlineAt (абсолютный момент): пересчёт от
// Date.now() не позволяет «продлить» попытку повторным рендером или повторным
// входом на экран. null → legacy-countdown от timeLimitSeconds.
function remainingSeconds(
  attemptDeadlineAt: string | null,
  timeLimitSeconds: number | null,
): number | null {
  if (attemptDeadlineAt) {
    const deadlineMs = new Date(attemptDeadlineAt).getTime()
    if (Number.isFinite(deadlineMs)) {
      return Math.max(0, Math.floor((deadlineMs - Date.now()) / 1000))
    }
  }
  return timeLimitSeconds
}

export function CipherGame({
  drums,
  correctCode,
  timeLimitSeconds,
  attemptDeadlineAt = null,
  onSubmit,
  isSubmitting = false,
  resetSignal = 0,
  initialIndices,
  onTimeout,
  title,
  error,
}: CipherGameProps) {
  const { t } = useTranslation(['cipher'])
  // Позиции барабанов и обратный отсчёт попытки — внутреннее состояние игры.
  const [indices, setIndices] = useState<number[]>([])
  const [timeLeft, setTimeLeft] = useState<number | null>(null)
  const [timedOut, setTimedOut] = useState(false)

  const startYRef = useRef<number | null>(null)
  // onSubmit не включаем в deps таймера (функция пересоздаётся каждый рендер —
  // интервал бы перезапускался; примечание из CipherScreen про handleTimeout).
  const onSubmitRef = useRef(onSubmit)
  useEffect(() => {
    onSubmitRef.current = onSubmit
  })
  const timeoutFiredRef = useRef(false)

  // Пересборка по resetSignal: смена волны/сессии/после промаха. Таймер всегда
  // пересчитывается от серверного attemptDeadlineAt (а не «на полный лимит»):
  // новая попытка приходит с новым дедлайном, а повторный вход на экран время
  // не продлевает.
  useEffect(() => {
    const starts =
      initialIndices && initialIndices.length === drums.length
        ? initialIndices
        : drums.map(() => 0)
    setIndices(starts)
    setTimeLeft(remainingSeconds(attemptDeadlineAt, timeLimitSeconds))
    setTimedOut(false)
    timeoutFiredRef.current = false
    // drums/timeLimitSeconds/initialIndices меняются только вместе с
    // инкрементом resetSignal (эффект инициализации владельца).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal, attemptDeadlineAt])

  // Обратный отсчёт попытки. timeLeft <= 0 → таймаут = промах.
  useEffect(() => {
    if (timeLeft === null || timedOut) return
    if (timeLeft <= 0) {
      setTimedOut(true)
      if (!timeoutFiredRef.current) {
        timeoutFiredRef.current = true
        onSubmitRef.current([])
        onTimeout?.()
      }
      return
    }
    const id = setInterval(() => {
      setTimeLeft((current) => {
        if (current === null) return null
        // С серверным дедлайном пересчитываем от Date.now(): декремент по
        // таймеру накапливал бы дрейф и «дарил» секунды.
        return attemptDeadlineAt
          ? remainingSeconds(attemptDeadlineAt, current)
          : current - 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [timeLeft, timedOut, onTimeout, attemptDeadlineAt])

  function stepDrum(drumIndex: number, direction: -1 | 1) {
    setIndices((current) =>
      current.map((index, i) => {
        if (i !== drumIndex) return index
        const length = drums[i]?.length ?? 1
        return (index + direction + length) % length
      }),
    )
  }

  function handleTouchStart(e: TouchEvent<HTMLDivElement>, _drumIndex: number) {
    startYRef.current = e.touches[0]?.clientY ?? null
  }

  function handleTouchMove(e: TouchEvent<HTMLDivElement>, drumIndex: number) {
    const startY = startYRef.current
    if (startY !== null) {
      const currentY = e.touches[0]?.clientY ?? startY
      const deltaY = currentY - startY
      if (Math.abs(deltaY) >= 30) {
        startYRef.current = currentY
        stepDrum(drumIndex, deltaY > 0 ? -1 : 1)
      }
    }
  }

  function handleTouchEnd() {
    startYRef.current = null
  }

  const sequence = drums.map((symbols, i) => {
    const current = indices[i] ?? 0
    return symbols[current] ?? symbols[0] ?? ''
  })

  return (
    <>
      {title && (
        <div className="cipher-instruction">
          <span className="file-label">{title}</span>
        </div>
      )}

      {/* Правильный код показан открыто — игра на скорость (не на угадывание). */}
      <div className="cipher-combination" aria-label={t('cipher:game.correctCombinationAria')}>
        {correctCode.map((char, index) => (
          <span key={`${char}-${index}`} className="cipher-combination-char">
            {char}
          </span>
        ))}
      </div>

      {timeLeft !== null && !timedOut && (
        <div
          className={`cipher-timer${timeLeft <= 10 ? ' cipher-timer-critical' : ''}`}
        >
          {t('cipher:timer.seconds', { seconds: Math.max(timeLeft, 0) })}
        </div>
      )}

      <div className="cipher-drums">
        {drums.map((symbols, drumIndex) => {
          const length = symbols.length
          const currentIndex = indices[drumIndex] ?? 0
          const prev = symbols[(currentIndex - 1 + length) % length]
          const current = symbols[currentIndex]
          const next = symbols[(currentIndex + 1) % length]
          return (
            <div
              key={`${drumIndex}-${symbols.join('')}`}
              className="cipher-drum"
              style={{ touchAction: 'none' }}
              onTouchStart={(e) => handleTouchStart(e, drumIndex)}
              onTouchMove={(e) => handleTouchMove(e, drumIndex)}
              onTouchEnd={handleTouchEnd}
            >
              <span className="cipher-drum-symbol cipher-drum-muted">{prev}</span>
              <span className="cipher-drum-symbol cipher-drum-current">
                {current}
              </span>
              <span className="cipher-drum-symbol cipher-drum-muted">{next}</span>
            </div>
          )
        })}
      </div>

      {error && <p className="repair-error">{error}</p>}

      <div className="repair-actions">
        {/* Sprint 8.x-attempt-deadline: кнопка «ЗАНОВО» удалена — она
            перезапускала локальный таймер попытки и позволяла играть
            бесконечно внутри одной попытки без её потери. */}
        <button
          className="repair-submit-button"
          onClick={() => onSubmit(sequence)}
          disabled={isSubmitting || drums.length === 0}
        >
          {isSubmitting ? t('cipher:buttons.submitting') : t('cipher:buttons.submit')}
        </button>
      </div>
    </>
  )
}
