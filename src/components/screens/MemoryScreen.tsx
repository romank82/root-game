import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { EngineMission, MissionSubmission } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { useActiveMission } from '../../hooks/useActiveMission'
import { MissionTimer } from '../MissionTimer'
import { MemoryGame } from '../MemoryGame'

// Sprint Memory-2b: мини-игра «память» (пары карточек). Экран-клон CipherScreen:
// раскладку берёт из серверной сессии mission.memorySession (bootstrap,
// Sprint Memory-2a), порядок открытий отправляет общим submit миссии —
// окончательная проверка на сервере (validator memory_match, MemoryHandler).

// Публичный контент миссии (mission.content.ui) — только тексты: сложность
// memory живёт в профиле мини-игры / серверной сессии, а не в content.ui.
type MemoryContent = {
  label: string | null
  instruction: string | null
  gridSize: number
  pairs: number[]
  timeLimitSeconds: number | null
  successTitle: string | null
  successText: string | null
  wrongAnswerText: string | null
}

// Backend-сессия memory (mission.memorySession, Sprint Memory-2a).
type MemorySession =
  | { gridSize: number; pairs: number[]; timeLimitSeconds: number | null }
  | null

interface MemoryScreenProps {
  missions: EngineMission[]
  onScreenChange: (screen: Screen) => void
  onSubmitMission: (
    missionId: string,
    payload: { sequence?: string[] },
  ) => Promise<MissionSubmission | null>
  onExpireMission: (missionId: string) => void
}

// ---------- Хелперы чтения неструктурированного контента ----------
// (локальная копия паттерна CipherScreen/ScannerScreen — общих утилит нет)

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

// ---------- Парсинг сессии ----------

function parseMemoryContent(mission: EngineMission): MemoryContent | null {
  if (mission.missionType !== 'memory') return null

  const ui = asRecord(asRecord(mission.content)?.ui)
  const session: MemorySession = mission.memorySession ?? null
  // gridSize приходит чётным 4..8 (валидация профиля: Memory-2a).
  const gridSize = asNumber(session?.gridSize, 4, 8)
  const sessionPairs = session?.pairs

  // Без валидной серверной сессии играть нечем: у memory нет legacy-пути
  // через content.ui (сложность появилась только с профилем/сессией).
  if (
    gridSize === null ||
    gridSize % 2 !== 0 ||
    !Array.isArray(sessionPairs) ||
    sessionPairs.length !== gridSize * gridSize ||
    !sessionPairs.every(
      (value) => typeof value === 'number' && Number.isFinite(value),
    )
  ) {
    return null
  }

  // Лимит времени: приоритет у серверной сессии (profile.settings), затем
  // content.ui (если админ задал текст-контент с таймером).
  const sessionTimeLimit = session?.timeLimitSeconds
  const timeLimitRaw = sessionTimeLimit ?? ui?.timeLimitSeconds
  const timeLimitSeconds =
    timeLimitRaw === null || timeLimitRaw === undefined
      ? null
      : asNumber(timeLimitRaw, 1, 3600)

  return {
    label: asText(ui?.label),
    instruction: asText(ui?.instruction),
    gridSize,
    pairs: sessionPairs as number[],
    timeLimitSeconds,
    successTitle: asText(ui?.successTitle),
    successText: asText(ui?.successText),
    wrongAnswerText: asText(ui?.wrongAnswerText),
  }
}

// ---------- Оформление награды ----------

function formatAwarded(response: MissionSubmission, t: TFunction): string {
  const parts: string[] = []

  if (response.awarded.root > 0) {
    parts.push(`${response.awarded.root} ROOT`)
  }

  for (const item of response.awarded.items) {
    parts.push(`${item.title} ×${item.quantity}`)
  }

  return parts.length > 0
    ? parts.join(' · ')
    : t('memory:success.noAwards')
}

export function MemoryScreen({
  missions,
  onScreenChange,
  onSubmitMission,
  onExpireMission,
}: MemoryScreenProps) {
  const { t } = useTranslation(['memory', 'common'])
  const [resetSignal, setResetSignal] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successAward, setSuccessAward] = useState<string | null>(null)
  const [successTitle, setSuccessTitle] = useState<string | null>(null)
  const [successText, setSuccessText] = useState<string | null>(null)
  const [timedOut, setTimedOut] = useState(false)

  // Единый выбор активной миссии (ближайшая in_progress со spawn) среди миссий
  // именно типа memory — фильтруем ДО выбора.
  const memoryMissions = missions.filter((m) => m.missionType === 'memory')
  const mission = useActiveMission(memoryMissions, null)
  const content = mission ? parseMemoryContent(mission) : null

  // Пересборка поля при смене миссии и при новой серверной сессии: после
  // промаха сервер пересоздаёт memorySession → deps перезапускают эффект, поле
  // и таймер начинаются заново (MemoryGame пересобирается по resetSignal).
  useEffect(() => {
    const active = mission ? parseMemoryContent(mission) : null
    if (!active) return
    setResetSignal((value) => value + 1)
    setError(null)
    setSuccessAward(null)
    setSuccessTitle(null)
    setSuccessText(null)
    setSubmitting(false)
    setTimedOut(false)
  }, [mission?.id, mission?.memorySession])

  // Таймаут попытки обрабатывает MemoryGame (внутренний таймер): при
  // timeLeft <= 0 он вызывает onSubmit([]) — пустая последовательность
  // гарантированный False для memory_match → промах (attempt_count += 1)
  // и новая попытка. Экран здесь только обрабатывает ответ сервера.
  async function handleSubmit(sequence: string[]) {
    if (!mission) return
    setSubmitting(true)
    setError(null)

    const response = await onSubmitMission(mission.id, { sequence })

    setSubmitting(false)
    if (!response) {
      setError(t('memory:errors.serverUnavailable'))
      return
    }
    if (!response.accepted) {
      setError(
        response.message ??
          content?.wrongAnswerText ??
          t('memory:game.wrongFallback'),
      )
      // Новая попытка — свежий таймер и закрытое поле (MemoryGame
      // пересобирается по resetSignal).
      setTimedOut(false)
      setResetSignal((value) => value + 1)
      return
    }

    setSuccessAward(formatAwarded(response, t))
    // Запоминаем тексты из content ДО того, как mission станет null
    setSuccessTitle(content?.successTitle ?? null)
    setSuccessText(content?.successText ?? null)
  }

  // Sprint 8.x-attempt-deadline: handleReset («ЗАНОВО») удалён вместе с
  // кнопкой. Время попытки теперь серверное (attemptDeadlineAt), поэтому
  // локальный перезапуск поля больше не нужен и не должен продлевать таймер.

  // 1. Сначала — финальные состояния (успех, тайм-аут).
  //    Они не зависят от mission — используют локальный state.
  if (successAward) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">{t('memory:header.completedEyebrow')}</p>
        <section className="mission-success-card">
          <span className="file-label">{t('memory:success.label')}</span>
          <div className="mission-success-symbol">✓</div>
          <h3>{successTitle ?? t('memory:success.titleFallback')}</h3>
          <p>{successText ?? t('memory:success.textFallback')}</p>
          <div className="mission-reward-grid">
            <div>
              <span>{t('memory:success.receivedLabel')}</span>
              <strong>{successAward}</strong>
            </div>
          </div>
          <button
            className="repair-submit-button"
            onClick={() => onScreenChange('terminal')}
          >
            {t('memory:buttons.backToContour')}
          </button>
        </section>
      </section>
    )
  }

  if (timedOut) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">{t('memory:header.timeUpEyebrow')}</p>
        <section className="mission-success-card">
          <span className="file-label">{t('memory:timeUp.label')}</span>
          <div className="mission-success-symbol">!</div>
          <h3>{t('memory:timeUp.title')}</h3>
          <p>{content?.wrongAnswerText ?? t('memory:timeUp.wrongFallback')}</p>
          <button
            className="repair-submit-button"
            onClick={() => onScreenChange('terminal')}
          >
            {t('memory:buttons.backToContour')}
          </button>
        </section>
      </section>
    )
  }

  // 2. Только потом — проверка активной миссии и серверной сессии memory.
  if (!mission || !content) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">{t('memory:errors.noMissionEyebrow')}</p>
        <section className="location-status">
          <span className="location-status-icon">⌖</span>
          <div>
            <strong>{t('memory:errors.noMissionTitle')}</strong>
            <p>{t('memory:errors.noMissionBody')}</p>
          </div>
        </section>
        <button className="back-button" onClick={() => onScreenChange('terminal')}>
          {t('common:backToContour')}
        </button>
      </section>
    )
  }

  // Счётчик попыток: attemptCount инкрементится сервером при каждом промахе,
  // поэтому текущая попытка = attemptCount + 1. maxAttempts — из published
  // MissionRuntimePolicy; legacy без policy → null.
  const currentAttempt = mission.attemptCount + 1
  const maxAttempts = mission.maxAttempts ?? null
  const isLastAttempt = maxAttempts !== null && currentAttempt === maxAttempts

  const attemptLabel =
    maxAttempts !== null
      ? `${t('memory:timer.attemptOfMax', {
          current: currentAttempt,
          max: maxAttempts,
        })}${isLastAttempt ? t('memory:timer.attemptLastMark') : ''}`
      : t('memory:timer.attemptCurrent', { current: currentAttempt })

  // 3. Иначе — игровой UI.
  return (
    <section className="segment-screen">
      <p className="eyebrow">{t('memory:header.activeMissionEyebrow')}</p>

      {mission.deadlineAt && (
        <MissionTimer
          deadlineAt={mission.deadlineAt}
          label={t('memory:header.timerLabel')}
          onClick={() => onExpireMission(mission.id)}
        />
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        {t('common:backToContour')}
      </button>

      <div className="segment-heading">
        <div>
          <span className="segment-type">MEMORY</span>
          <h2>{mission.title}</h2>
          <p>{mission.description}</p>
        </div>
      </div>
      <div className="cipher-instruction">
        {content.label && <span className="file-label">{content.label}</span>}
        {content.instruction && <p>{content.instruction}</p>}
      </div>

      {/* Игровая часть вынесена в переиспользуемый MemoryGame: подготовка
          данных (parseMemoryContent) и обработка ответа остаются здесь. */}
      <div className="cipher-timer">{attemptLabel}</div>

      <MemoryGame
        gridSize={content.gridSize}
        pairs={content.pairs}
        timeLimitSeconds={content.timeLimitSeconds}
        attemptDeadlineAt={mission.attemptDeadlineAt}
        onSubmit={handleSubmit}
        isSubmitting={submitting}
        resetSignal={resetSignal}
        onTimeout={() => setTimedOut(true)}
        error={error}
      />
    </section>
  )
}

