import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

// Sprint Memory-2b: переиспользуемая игровая часть memory (пары карточек).
// Получает готовую раскладку (pairs) и размер сетки и НЕ знает про
// mission/bootstrap — подготовку данных держит экран-владелец (MemoryScreen),
// как в CipherGame/CipherScreen.
//
// Владеет: открытием карточек (клик), локальной проверкой пар (визуально),
// историей открытий (sequence для сервера) и таймером попытки. Таймер считает
// от серверного attemptDeadlineAt (Sprint 8.x-attempt-deadline: кнопка
// «ЗАНОВО» удалена, время попытки продлить нельзя), при его отсутствии —
// legacy-countdown от timeLimitSeconds. При истечении времени сам отправляет
// пустую последовательность (гарантированный
// промах для memory_match → attempt += 1) и оповещает onTimeout.
// Окончательную проверку порядка открытий делает сервер (MemoryHandler).

export interface MemoryGameProps {
  gridSize: number
  // Значение каждой карточки (id пары); длина = gridSize * gridSize,
  // каждый id встречается ровно 2 раза.
  pairs: number[]
  timeLimitSeconds: number | null
  // Sprint 8.x-attempt-deadline: абсолютный момент окончания ТЕКУЩЕЙ попытки
  // (mission.attemptDeadlineAt из bootstrap). Приоритетнее timeLimitSeconds:
  // пересчитывается от Date.now(), поэтому повторный рендер и повторный вход на
  // экран не продлевают время попытки. null/undefined — legacy-countdown от
  // timeLimitSeconds (миссии без лимита).
  attemptDeadlineAt?: string | null
  onSubmit: (sequence: string[]) => void
  isSubmitting?: boolean
  // Внешний сигнал пересборки (новая сессия, новая попытка после промаха):
  // сбрасывает открытые карточки, историю открытий и пересчитывает таймер от
  // attemptDeadlineAt (а не «на полный лимит»).
  resetSignal?: number
  onTimeout?: () => void
  // @deprecated Sprint 8.x-attempt-deadline: кнопка «ЗАНОВО» удалена, пропс
  // больше не читается (сохранён в интерфейсе для совместимости).
  onReset?: () => void
  // Опциональный заголовок (MemoryScreen передаёт его при необходимости).
  title?: string
  // Текст ошибки последней попытки (рендерится как в CipherScreen).
  error?: string | null
}

// Сколько миллисекунд несовпавшая пара остаётся открытой.
const MISMATCH_HIDE_DELAY_MS = 800

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

export function MemoryGame({
  gridSize,
  pairs,
  timeLimitSeconds,
  attemptDeadlineAt = null,
  onSubmit,
  isSubmitting = false,
  resetSignal = 0,
  onTimeout,
  title,
  error,
}: MemoryGameProps) {
  const { t } = useTranslation(['memory'])
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

  // Пересборка по resetSignal: смена миссии/сессии, после промаха. Таймер
  // всегда пересчитывается от серверного attemptDeadlineAt (а не «на полный
  // лимит»): новая попытка приходит с новым дедлайном, а повторный вход на
  // экран время не продлевает.
  useEffect(() => {
    clearHideTimer()
    historyRef.current = []
    setOpenCards([])
    setMatchedCards(new Set())
    setTimeLeft(remainingSeconds(attemptDeadlineAt, timeLimitSeconds))
    setTimedOut(false)
    timeoutFiredRef.current = false
    // timeLimitSeconds/pairs меняются только вместе с инкрементом
    // resetSignal (эффект инициализации владельца).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal, attemptDeadlineAt])

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

    if (pairs[first] === pairs[second]) {
      // История для сервера содержит только найденные пары.
      const history = [...historyRef.current, first, second]
      historyRef.current = history

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
          {t('memory:timer.seconds', { seconds: Math.max(timeLeft, 0) })}
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
        {/* Sprint 8.x-attempt-deadline: кнопка «ЗАНОВО» удалена — она
            перезапускала локальный таймер попытки (и позволяла запоминать
            раскладку между перезапусками), не тратя попыток. */}
        <button
          className="repair-submit-button"
          // Повторная отправка уже собранного порядка (например, после обрыва
          // сети): сервер идемпотентен, повтор безопасен.
          onClick={() => onSubmit(historyRef.current.map(String))}
          disabled={boardLocked || !boardComplete}
        >
          {isSubmitting
            ? t('memory:buttons.submitting')
            : t('memory:buttons.submit')}
        </button>
      </div>
    </>
  )
}
