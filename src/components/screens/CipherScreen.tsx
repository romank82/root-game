import { useEffect, useRef, useState, type TouchEvent } from 'react'
import type { EngineMission, MissionSubmission } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { useActiveMission } from '../../hooks/useActiveMission'
import { MissionTimer } from '../MissionTimer'

// Sprint 8.13: мини-игра «кодовый замок с барабанами».
// Контракт: docs/minigame-cipher.md, разделы 3 (поток) и 4 (UI).

// Один барабан: набор символов + позиция текущего (выделенного) символа.
type Drum = {
  symbols: string[]
  currentIndex: number
}

// Публичный контент миссии (mission.content.ui, приходит через bootstrap).
type CipherContent = {
  label: string | null
  instruction: string | null
  drumCount: number
  alphabet: string[]
  falseChoicesPerDrum: number | null
  combination: string
  timeLimitSeconds: number | null
  successTitle: string | null
  successText: string | null
  wrongAnswerText: string | null
}

interface CipherScreenProps {
  missions: EngineMission[]
  onScreenChange: (screen: Screen) => void
  onSubmitMission: (
    missionId: string,
    payload: { sequence?: string[] },
  ) => Promise<MissionSubmission | null>
  onExpireMission: (missionId: string) => void
}

// ---------- Хелперы чтения неструктурированного контента ----------
// (локальная копия паттерна ScannerScreen — общих утилит в проекте нет)

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function asNumber(
  value: unknown,
  minimum: number,
  maximum: number,
): number | null {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum
  ) {
    return null
  }
  return value
}

// ---------- Парсинг content.ui ----------

function parseCipherContent(mission: EngineMission): CipherContent | null {
  if (mission.missionType !== 'cipher') return null

  const root = asRecord(mission.content)
  const ui = asRecord(root?.ui)
  if (!ui) return null

  const drumCount = asNumber(ui.drumCount, 2, 12)
  const combination = asText(ui.combination)
  const alphabetRaw = ui.alphabet
  const alphabet = Array.isArray(alphabetRaw)
    ? alphabetRaw.filter((symbol): symbol is string => typeof symbol === 'string')
    : []

  if (drumCount === null || !combination || alphabet.length === 0) {
    return null
  }

  const timeLimitRaw = ui.timeLimitSeconds
  const timeLimitSeconds =
    timeLimitRaw === null || timeLimitRaw === undefined
      ? null
      : asNumber(timeLimitRaw, 1, 3600)

  return {
    label: asText(ui.label),
    instruction: asText(ui.instruction),
    drumCount,
    alphabet,
    falseChoicesPerDrum: asNumber(ui.falseChoicesPerDrum, 0, 10),
    combination,
    timeLimitSeconds,
    successTitle: asText(ui.successTitle),
    successText: asText(ui.successText),
    wrongAnswerText: asText(ui.wrongAnswerText),
  }
}

// ---------- Генерация барабанов ----------

function shuffle<T>(items: T[]): T[] {
  const copy = [...items]
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[copy[i], copy[j]] = [copy[j], copy[i]]
  }
  return copy
}

function buildDrums(content: CipherContent): Drum[] | null {
  const combinationChars = Array.from(content.combination)
  if (combinationChars.length !== content.drumCount) return null

  const drums: Drum[] = []
  const falseChoicesCount = content.falseChoicesPerDrum ?? 0

  for (let i = 0; i < content.drumCount; i += 1) {
    const correctChar = combinationChars[i]
    // Ложные символы: из alphabet без правильного, без повторов внутри барабана.
    const pool = content.alphabet.filter((symbol) => symbol !== correctChar)
    const falseChoices = shuffle(pool).slice(0, falseChoicesCount)
    const symbols = shuffle([correctChar, ...falseChoices])

    // Начальная позиция — не на правильном символе (получать ответ
    // бесплатно игрок не должен). Если есть альтернативы — сдвигаемся на 1.
    const startIndex =
      symbols.length > 1 && symbols[0] === correctChar ? 1 : 0
    drums.push({ symbols, currentIndex: startIndex })
  }

  return drums
}

// ---------- Оформление награды ----------

function formatAwarded(response: MissionSubmission): string {
  const parts: string[] = []

  if (response.awarded.root > 0) {
    parts.push(`${response.awarded.root} ROOT`)
  }

  for (const item of response.awarded.items) {
    parts.push(`${item.title} ×${item.quantity}`)
  }

  return parts.length > 0
    ? parts.join(' · ')
    : 'Прогресс подтверждён сервером.'
}
export function CipherScreen({
  missions,
  onScreenChange,
  onSubmitMission,
  onExpireMission,
}: CipherScreenProps) {
  const [drums, setDrums] = useState<Drum[]>([])
  const [timeLeft, setTimeLeft] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successAward, setSuccessAward] = useState<string | null>(null)
  const [successTitle, setSuccessTitle] = useState<string | null>(null)
  const [successText, setSuccessText] = useState<string | null>(null)
  const [timedOut, setTimedOut] = useState(false)

  // Единый выбор активной миссии (ближайшая in_progress со spawn)
  // среди миссий именно типа cipher — фильтруем ДО выбора.
  const cipherMissions = missions.filter((m) => m.missionType === 'cipher')
  const mission = useActiveMission(cipherMissions, null)
  const content = mission ? parseCipherContent(mission) : null

  // Хранилище стартовой точки свайпа по вертикали.
  const startYRef = useRef<number | null>(null)

  // Инициализация барабанов при смене миссии.
  useEffect(() => {
    const active = mission ? parseCipherContent(mission) : null
    if (!active) {
      setDrums([])
      return
    }
    const next = buildDrums(active)
    setDrums(next ?? [])
    setError(null)
    setSuccessAward(null)
    setSuccessTitle(null)
    setSuccessText(null)
    setSubmitting(false)
    setTimedOut(false)
    setTimeLeft(active.timeLimitSeconds)
  }, [mission?.id])

  // Обратный отсчёт. timeLeft <= 0 → тайм-аут = промах (не expire миссии).
  useEffect(() => {
    if (timeLeft === null || timedOut) return
    if (timeLeft <= 0) {
      setTimedOut(true)
      // Sprint 8.14 (fix): тайм-аут = промах (не expire миссии).
      // Пустая последовательность гарантированно False для cipher_match.
      // Это даёт attempt_count += 1 и новую попытку (или 409 + expired
      // при исчерпании max_attempts).
      if (mission) {
        void handleTimeout()
      }
      return
    }
    const id = setInterval(
      () => setTimeLeft((current) => (current === null ? null : current - 1)),
      1000,
    )
    // Примечание: handleTimeout намеренно НЕ в списке зависимостей — функция
    // пересоздаётся каждый рендер, и её добавление в deps перезапускало бы
    // интервал на каждом рендере (замедление отсчёта). Тайм-аут — one-shot.
    return () => clearInterval(id)
  }, [timeLeft, timedOut, mission?.id])

  function stepDrum(drumIndex: number, direction: -1 | 1) {
    setDrums((current) =>
      current.map((drum, index) => {
        if (index !== drumIndex) return drum
        const length = drum.symbols.length
        const next = (drum.currentIndex + direction + length) % length
        return { ...drum, currentIndex: next }
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

  // Тайм-аут попытки: пустая последовательность — гарантированный False для
  // cipher_match → промах (attempt_count += 1) и новая попытка. Всю обработку
  // ответа (null / !accepted / accepted) переиспользуем из handleSubmit.
  async function handleTimeout() {
    if (!mission) return
    if (submitting) return
    await handleSubmit([])
  }

  async function handleSubmit(sequenceOverride?: string[]) {
    if (!mission) return
    setSubmitting(true)
    setError(null)

    // Тайм-аут передаёт пустую последовательность (sequenceOverride=[]),
    // обычная отправка собирает текущую позицию барабанов.
    const sequence =
      sequenceOverride ?? drums.map((drum) => drum.symbols[drum.currentIndex])
    const response = await onSubmitMission(mission.id, { sequence })

    setSubmitting(false)
    if (!response) {
      setError('СЕРВЕР НЕДОСТУПЕН. ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ.')
      return
    }
    if (!response.accepted) {
      setError(response.message ?? content?.wrongAnswerText ?? 'НЕВЕРНО, ПОПРОБУЙ ЕЩЁ')
      // Sprint 8.14 (fix): новая попытка — свежий таймер мини-игры.
      if (content?.timeLimitSeconds != null) {
        setTimeLeft(content.timeLimitSeconds)
      }
      setTimedOut(false)
      return
    }

    setSuccessAward(formatAwarded(response))
    // Запоминаем тексты из content ДО того, как mission станет null
    setSuccessTitle(content?.successTitle ?? null)
    setSuccessText(content?.successText ?? null)
  }

  // 1. Сначала — финальные состояния (успех, тайм-аут).
  //    Они не зависят от mission — используют локальный state.
  if (successAward) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">АКТИВНАЯ МИССИЯ / ЗАВЕРШЕНА</p>
        <section className="mission-success-card">
          <span className="file-label">ЗАМОК ОТКРЫТ</span>
          <div className="mission-success-symbol">✓</div>
          <h3>{successTitle ?? 'Комбинация принята'}</h3>
          <p>
            {successText ?? 'Прогресс и награды подтверждены сервером.'}
          </p>
          <div className="mission-reward-grid">
            <div>
              <span>ПОЛУЧЕНО</span>
              <strong>{successAward}</strong>
            </div>
          </div>
          <button
            className="repair-submit-button"
            onClick={() => onScreenChange('terminal')}
          >
            В КОНТУР →
          </button>
        </section>
      </section>
    )
  }

  if (timedOut) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">АКТИВНАЯ МИССИЯ / ВРЕМЯ ВЫШЛО</p>
        <section className="mission-success-card">
          <span className="file-label">ВРЕМЯ ВЫШЛО</span>
          <div className="mission-success-symbol">!</div>
          <h3>Комбинация не собрана</h3>
          <p>{content?.wrongAnswerText ?? 'Попытка не засчитана.'}</p>
          <button
            className="repair-submit-button"
            onClick={() => onScreenChange('terminal')}
          >
            В КОНТУР →
          </button>
        </section>
      </section>
    )
  }

  // 2. Только потом — проверка активной миссии.
  if (!mission || !content) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">CIPHER / МИНИ-ИГРА НЕДОСТУПНА</p>
        <section className="location-status">
          <span className="location-status-icon">⌖</span>
          <div>
            <strong>НЕТ АКТИВНОЙ МИССИИ CIPHER</strong>
            <p>
              Опубликованная миссия кодового замка ещё не получена из игрового
              bootstrap либо содержит некорректный public content.
            </p>
          </div>
        </section>
        <button className="back-button" onClick={() => onScreenChange('terminal')}>
          ← ВЕРНУТЬСЯ В КОНТУР
        </button>
      </section>
    )
  }

  // 3. Иначе — игровой UI.
  return (
    <section className="segment-screen">
      <p className="eyebrow">АКТИВНАЯ МИССИЯ / {mission.id.toUpperCase()}</p>

      {mission.deadlineAt && (
        <MissionTimer
          deadlineAt={mission.deadlineAt}
          label="до конца задания"
          onClick={() => onExpireMission(mission.id)}
        />
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>

      <div className="segment-heading">
        <div>
          <span className="segment-type">CIPHER</span>
          <h2>{mission.title}</h2>
          <p>{mission.description}</p>
        </div>
      </div>
      <div className="cipher-instruction">
        {content.label && <span className="file-label">{content.label}</span>}
        {content.instruction && <p>{content.instruction}</p>}
      </div>

      <div className="cipher-combination" aria-label="Правильная комбинация">
        {Array.from(content.combination).map((char, index) => (
          <span key={`${char}-${index}`} className="cipher-combination-char">
            {char}
          </span>
        ))}
      </div>

      {timeLeft !== null && (
        <div
          className={`cipher-timer${
            timeLeft <= 10 ? ' cipher-timer-critical' : ''
          }`}
        >
          ⏱ {Math.max(timeLeft, 0)} сек
        </div>
      )}

      <div className="cipher-drums">
        {drums.map((drum, drumIndex) => {
          const length = drum.symbols.length
          const prev =
            drum.symbols[(drum.currentIndex - 1 + length) % length]
          const current = drum.symbols[drum.currentIndex]
          const next = drum.symbols[(drum.currentIndex + 1) % length]
          return (
            <div
              key={`${drumIndex}-${drum.symbols.join('')}`}
              className="cipher-drum"
              style={{ touchAction: 'none' }}
              onTouchStart={(e) => handleTouchStart(e, drumIndex)}
              onTouchMove={(e) => handleTouchMove(e, drumIndex)}
              onTouchEnd={handleTouchEnd}
            >
              <span className="cipher-drum-symbol cipher-drum-muted">
                {prev}
              </span>
              <span className="cipher-drum-symbol cipher-drum-current">
                {current}
              </span>
              <span className="cipher-drum-symbol cipher-drum-muted">
                {next}
              </span>
            </div>
          )
        })}
      </div>

      {error && <p className="repair-error">{error}</p>}

      <div className="repair-actions">
        <button
          className="repair-clear-button"
          onClick={() => {
            const next = buildDrums(content)
            if (next) setDrums(next)
            setError(null)
          }}
        >
          ЗАНОВО
        </button>
        <button
          className="repair-submit-button"
          onClick={() => void handleSubmit()}
          disabled={submitting || drums.length === 0}
        >
          {submitting ? 'ПРОВЕРЯЕМ…' : 'ГОТОВО →'}
        </button>
      </div>
    </section>
  )
}