import { useEffect, useRef, useState, type TouchEvent } from 'react'
import { useTranslation } from 'react-i18next'

// Sprint 8.x-4a: переиспользуемая игровая часть cipher (solo + team).
// Получает готовые данные игры (drums, correctCode, timeLimitSeconds) и НЕ
// знает про mission/cipherSession — подготовку данных держит экран-владелец
// (CipherScreen / TeamSessionScreen). Стили — глобальные классы cipher-* /
// repair-* из App.css (переиспользуются, новых не вводим).
//
// Владеет: вращением барабанов (свайп), показом правильного кода открыто
// (игра на скорость), кнопкой «ГОТОВО →» и таймером попытки. При истечении
// timeLimitSeconds сам отправляет пустую последовательность (гарантированный
// промах для cipher_match → attempt += 1) и оповещает onTimeout.

export interface CipherGameProps {
  drums: string[][]
  correctCode: string[]
  timeLimitSeconds: number | null
  onSubmit: (sequence: string[]) => void
  isSubmitting?: boolean
  // Внешний сигнал пересборки (новая сессия/волна, «заново», новая попытка
  // после промаха): сбрасывает позиции барабанов и таймер попытки.
  resetSignal?: number
  // Стартовые позиции барабанов на момент сброса (из buildDrums; default 0).
  initialIndices?: number[]
  onTimeout?: () => void
  // «ЗАНОВО»: владелец пересобирает барабаны (buildDrums) и инкрементит
  // resetSignal; без колбэка — локальный сброс позиций в 0.
  onReset?: () => void
  // Опциональные тексты для team-экрана (solo их не передаёт).
  title?: string
  // Текст ошибки последней попытки (рендерится как в CipherScreen solo).
  error?: string | null
}

export function CipherGame({
  drums,
  correctCode,
  timeLimitSeconds,
  onSubmit,
  isSubmitting = false,
  resetSignal = 0,
  initialIndices,
  onTimeout,
  onReset,
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

  // Пересборка по resetSignal: смена волны/сессии/«заново»/после промаха.
  useEffect(() => {
    const starts =
      initialIndices && initialIndices.length === drums.length
        ? initialIndices
        : drums.map(() => 0)
    setIndices(starts)
    setTimeLeft(timeLimitSeconds)
    setTimedOut(false)
    timeoutFiredRef.current = false
    // drums/timeLimitSeconds/initialIndices меняются только вместе с
    // инкрементом resetSignal (эффект инициализации владельца).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal])

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
    const id = setInterval(
      () => setTimeLeft((current) => (current === null ? null : current - 1)),
      1000,
    )
    return () => clearInterval(id)
  }, [timeLeft, timedOut, onTimeout])

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
        <button
          className="repair-clear-button"
          onClick={() => {
            if (onReset) {
              onReset()
            } else {
              setIndices(drums.map(() => 0))
            }
          }}
        >
          {t('cipher:buttons.reset')}
        </button>
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
