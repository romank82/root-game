import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

// Sprint Memory-2b: переиспользуемая игровая часть memory (пары карточек).
// Получает готовую раскладку (pairs) и размер сетки и НЕ знает про
// mission/bootstrap — подготовку данных держит экран-владелец (MemoryScreen),
// как в CipherGame/CipherScreen.
//
// Владеет: открытием карточек (клик), локальной проверкой пар (визуально),
// историей открытий (sequence для сервера) и таймером попытки. При истечении
// timeLimitSeconds сам отправляет пустую последовательность (гарантированный
// промах для memory_match → attempt += 1) и оповещает onTimeout.
// Окончательную проверку порядка открытий делает сервер (MemoryHandler).

export interface MemoryGameProps {
  gridSize: number
  // Значение каждой карточки (id пары); длина = gridSize * gridSize,
  // каждый id встречается ровно 2 раза.
  pairs: number[]
  timeLimitSeconds: number | null
  onSubmit: (sequence: string[]) => void
  isSubmitting?: boolean
  // Внешний сигнал пересборки (новая сессия, «заново», новая попытка после
  // промаха): сбрасывает открытые карточки, историю открытий и таймер.
  resetSignal?: number
  onTimeout?: () => void
  // «ЗАНОВО»: владелец пересобирает раскладку и инкрементит resetSignal;
  // без колбэка — локальный сброс поля.
  onReset?: () => void
  // Опциональный заголовок (MemoryScreen передаёт его при необходимости).
  title?: string
  // Текст ошибки последней попытки (рендерится как в CipherScreen).
  error?: string | null
}

// Сколько миллисекунд несовпавшая пара остаётся открытой.
const MISMATCH_HIDE_DELAY_MS = 800

export function MemoryGame({
  gridSize,
  pairs,
  timeLimitSeconds,
  onSubmit,
  isSubmitting = false,
  resetSignal = 0,
  onTimeout,
  onReset,
  title,
  error,
}: MemoryGameProps) {
  const { t } = useTranslation(['cipher'])
  // Открытые (ещё не проверенные) и совпавшие карточки — внутреннее состояние.
  const [openCards, setOpenCards] = useState<number[]>([])
  const [matchedCards, setMatchedCards] = useState<Set<number>>(new Set())
  const [timeLeft, setTimeLeft] = useState<number | null>(null)
  const [timedOut, setTimedOut] = useState(false)

  // onSubmit не включаем в deps таймера (функция пересоздаётся каждый рендер —
  // интервал бы перезапускался; как в CipherGame).
  const onSubmitRef = useRef(onSubmit)
  useEffect(() => {
    onSubmitRef.current = onSubmit
  })
  const timeoutFiredRef = useRef(false)

  // История открытий в порядке кликов: сервер проверяет пары (2i, 2i+1).
  const historyRef = useRef<number[]>([])
  // Таймер скрытия несовпавшей пары — чистим при сбросе/размонтировании.
  const hideTimerRef = useRef<number | null>(null)

  function clearHideTimer() {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }

  // Пересборка по resetSignal: смена миссии/сессии, «заново», после промаха.
  useEffect(() => {
    clearHideTimer()
    historyRef.current = []
    setOpenCards([])
    setMatchedCards(new Set())
    setTimeLeft(timeLimitSeconds)
    setTimedOut(false)
    timeoutFiredRef.current = false
    // timeLimitSeconds/pairs меняются только вместе с инкрементом
    // resetSignal (эффект инициализации владельца).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal])

  // Чистка отложенного скрытия пары при размонтировании.
  useEffect(() => () => clearHideTimer(), [])

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

  const boardLocked = isSubmitting || timedOut
  const boardComplete = pairs.length > 0 && matchedCards.size >= pairs.length

  function handleCardClick(index: number) {
    if (boardLocked) return
    // Уже открыта/совпала — игнор. Пока открыты две карточки и ждём скрытия
    // промаха — клики тоже игнорируем.
    if (matchedCards.has(index) || openCards.includes(index)) return
    if (openCards.length >= 2) return

    const nextOpen = [...openCards, index]
    setOpenCards(nextOpen)
    if (nextOpen.length < 2) return

    const first = nextOpen[0]
    const second = nextOpen[1]
    // История открытий для сервера: порядок кликов, по две карточки на ход.
    const history = [...historyRef.current, first, second]
    historyRef.current = history

    if (pairs[first] === pairs[second]) {
      const nextMatched = new Set(matchedCards)
      nextMatched.add(first)
      nextMatched.add(second)
      setMatchedCards(nextMatched)
      setOpenCards([])
      // Все карточки собраны → отправляем порядок открытий. Строки — формат
      // MissionSubmitPayload.sequence (бэкенд принимает цифровые строки).
      if (pairs.length > 0 && nextMatched.size >= pairs.length) {
        onSubmit(history.map(String))
      }
      return
    }

    // Промах: вторая карточка показывается, затем пара закрывается через паузу.
    clearHideTimer()
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null
      setOpenCards([])
    }, MISMATCH_HIDE_DELAY_MS)
  }

  // Размер сетки передаём в CSS (grid-template-columns: repeat(var(--grid-size))).
  const gridStyle = { '--grid-size': gridSize } as CSSProperties

  return (
    <>
      {title && (
        <div className="cipher-instruction">
          <span className="file-label">{title}</span>
        </div>
      )}

      {timeLeft !== null && !timedOut && (
        <div
          className={`cipher-timer${timeLeft <= 10 ? ' cipher-timer-critical' : ''}`}
        >
          {t('cipher:timer.seconds', { seconds: Math.max(timeLeft, 0) })}
        </div>
      )}

      <div className="memory-grid" style={gridStyle}>
        {pairs.map((value, index) => {
          const isMatched = matchedCards.has(index)
          const isOpen = isMatched || openCards.includes(index)
          return (
            <button
              key={`${index}-${value}`}
              type="button"
              className={`memory-card${isOpen ? ' is-flipped' : ''}${
                isMatched ? ' is-matched' : ''
              }`}
              onClick={() => handleCardClick(index)}
              disabled={boardLocked}
            >
              <span
                className="memory-card-face memory-card-front"
                aria-hidden="true"
              >
                ?
              </span>
              <span className="memory-card-face memory-card-back">{value}</span>
            </button>
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
              clearHideTimer()
              historyRef.current = []
              setOpenCards([])
              setMatchedCards(new Set())
              setTimeLeft(timeLimitSeconds)
              setTimedOut(false)
              timeoutFiredRef.current = false
            }
          }}
        >
          {t('cipher:buttons.reset')}
        </button>
        <button
          className="repair-submit-button"
          // Повторная отправка уже собранного порядка (например, после обрыва
          // сети): сервер идемпотентен, повтор безопасен.
          onClick={() => onSubmit(historyRef.current.map(String))}
          disabled={boardLocked || !boardComplete}
        >
          {isSubmitting
            ? t('cipher:buttons.submitting')
            : t('cipher:buttons.submit')}
        </button>
      </div>
    </>
  )
}
