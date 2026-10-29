import { useEffect, useState } from 'react'
import type { EngineMission, MissionSubmission } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { useActiveMission } from '../../hooks/useActiveMission'
import { MissionTimer } from '../MissionTimer'
import { CipherGame } from '../CipherGame'

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

// Backend-сессия cipher (mission.cipherSession, Sprint 8.17, шаги 6-7).
// Создаётся при accept, пересоздаётся после каждого промаха на сервере.
// У старых миссий отсутствует → fallback на content.ui (шаг 8.17.10).
type CipherSession =
  | { drums: string[][]; correctCode: string[]; timeLimitSeconds: number | null }
  | null

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

// ---------- Парсинг content.ui (приоритет — backend-сессия) ----------

function parseCipherContent(mission: EngineMission): CipherContent | null {
  if (mission.missionType !== 'cipher') return null

  const root = asRecord(mission.content)
  const ui = asRecord(root?.ui)
  // Sprint 8.17 (шаги 6-7): готовая backend-сессия (барабаны + правильный код).
  // Sprint 8.17.17: если сессия есть — content.ui НЕ требуется: новые миссии
  // могут не иметь content.ui.drumCount/alphabet/combination. Отрисовка идёт
  // из сессии, content.ui даёт только опциональные тексты/таймер.
  const sessionDrums = mission.cipherSession?.drums
  const sessionCode = mission.cipherSession?.correctCode
  const sessionUsable =
    Array.isArray(sessionDrums) &&
    sessionDrums.length > 0 &&
    sessionDrums.every(
      (symbols) =>
        Array.isArray(symbols) &&
        symbols.length > 0 &&
        symbols.every((symbol) => typeof symbol === 'string'),
    ) &&
    Array.isArray(sessionCode) &&
    sessionCode.length > 0 &&
    sessionCode.every((symbol) => typeof symbol === 'string')

  // 8.17-timer: лимит времени на попытку — приоритет у backend-сессии
  // (cipherSession.timeLimitSeconds), legacy fallback — content.ui.timeLimitSeconds.
  const sessionTimeLimit = mission.cipherSession?.timeLimitSeconds
  const timeLimitRaw = sessionTimeLimit ?? ui?.timeLimitSeconds
  const timeLimitSeconds =
    timeLimitRaw === null || timeLimitRaw === undefined
      ? null
      : asNumber(timeLimitRaw, 1, 3600)

  // Приоритет — backend-сессия: обязательные поля CipherContent (drumCount,
  // combination) берём из сессии, alphabet собираем из её барабанов.
  if (sessionUsable) {
    const sessionSymbols = sessionDrums.flatMap((symbols) => symbols)
    return {
      label: asText(ui?.label),
      instruction: asText(ui?.instruction),
      drumCount: sessionDrums.length,
      alphabet: [...new Set(sessionSymbols)],
      falseChoicesPerDrum: asNumber(ui?.falseChoicesPerDrum, 0, 10),
      combination: sessionCode.join(''),
      timeLimitSeconds,
      successTitle: asText(ui?.successTitle),
      successText: asText(ui?.successText),
      wrongAnswerText: asText(ui?.wrongAnswerText),
    }
  }

  // Legacy: сессии нет (миссия до миграции) или она невалидна — старое
  // поведение без изменений: обязателен content.ui.drumCount/alphabet/combination.
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

function buildDrums(
  content: CipherContent,
  cipherSession: CipherSession,
): Drum[] | null {
  // Sprint 8.17 (шаг 7): приоритет — готовые барабаны с backend
  // (mission.cipherSession). Локальная генерация из content.ui — fallback
  // для старых миссий до миграции (шаг 8.17.10).
  if (cipherSession) {
    const drumsRaw = cipherSession.drums
    if (
      Array.isArray(drumsRaw) &&
      drumsRaw.length > 0 &&
      drumsRaw.every(
        (symbols) =>
          Array.isArray(symbols) &&
          symbols.length > 0 &&
          symbols.every((symbol) => typeof symbol === 'string'),
      )
    ) {
      return drumsRaw.map((symbols) => ({
        symbols: [...symbols],
        currentIndex: 0,
      }))
    }
  }

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
  const [gameDrums, setGameDrums] = useState<string[][]>([])
  const [gameIndices, setGameIndices] = useState<number[]>([])
  const [resetSignal, setResetSignal] = useState(0)
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
  // Sprint 8.17 (шаг 7): готовая backend-сессия (барабаны + правильный код)
  // приоритетнее content.ui; у старых миссий её нет → fallback на content.ui.
  const cipherSession = mission?.cipherSession ?? null
  // Правильный код для показа игроку (игра на внимательность, не на угадывание).
  const correctCodeChars =
    cipherSession?.correctCode ?? Array.from(content?.combination ?? '')

  // Инициализация барабанов при смене миссии И при новой backend-сессии:
  // после промаха сервер пересоздаёт cipherSession → deps перезапускают
  // эффект и игра пересобирается заново (Sprint 8.17, шаг 7). Сами барабаны
  // и позиции передаются в CipherGame; здесь пересобираем их из buildDrums.
  useEffect(() => {
    const active = mission ? parseCipherContent(mission) : null
    if (!active) {
      setGameDrums([])
      setGameIndices([])
      return
    }
    const built = buildDrums(active, mission?.cipherSession ?? null)
    setGameDrums(built?.map((drum) => drum.symbols) ?? [])
    setGameIndices(built?.map((drum) => drum.currentIndex) ?? [])
    setResetSignal((value) => value + 1)
    setError(null)
    setSuccessAward(null)
    setSuccessTitle(null)
    setSuccessText(null)
    setSubmitting(false)
    setTimedOut(false)
  }, [mission?.id, mission?.cipherSession])

  // Тайм-аут попытки обрабатывает CipherGame (внутренний таймер): при
  // timeLeft <= 0 он вызывает onSubmit([]) — пустая последовательность
  // гарантированный False для cipher_match → промах (attempt_count += 1)
  // и новая попытка. Экран здесь только обрабатывает ответ сервера.
  async function handleSubmit(sequence: string[]) {
    if (!mission) return
    setSubmitting(true)
    setError(null)

    const response = await onSubmitMission(mission.id, { sequence })

    setSubmitting(false)
    if (!response) {
      setError('СЕРВЕР НЕДОСТУПЕН. ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ.')
      return
    }
    if (!response.accepted) {
      setError(response.message ?? content?.wrongAnswerText ?? 'НЕВЕРНО, ПОПРОБУЙ ЕЩЁ')
      // Sprint 8.14 (fix): новая попытка — свежий таймер и позиции барабанов
      // (CipherGame пересобирается по resetSignal).
      setTimedOut(false)
      setResetSignal((value) => value + 1)
      return
    }

    setSuccessAward(formatAwarded(response))
    // Запоминаем тексты из content ДО того, как mission станет null
    setSuccessTitle(content?.successTitle ?? null)
    setSuccessText(content?.successText ?? null)
  }

  // «ЗАНОВО»: пересобрать барабаны из той же сессии/контента и перезапустить
  // игру (позиции + таймер) через resetSignal.
  function handleReset() {
    if (!content || !mission) return
    const rebuilt = buildDrums(content, mission.cipherSession ?? null)
    if (rebuilt) {
      setGameDrums(rebuilt.map((drum) => drum.symbols))
      setGameIndices(rebuilt.map((drum) => drum.currentIndex))
    }
    setError(null)
    setResetSignal((value) => value + 1)
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

  // Sprint 8.14 (ui): счётчик попыток. attemptCount инкрементится сервером
  // при каждом промахе, поэтому текущая попытка = attemptCount + 1.
  // maxAttempts — из published MissionRuntimePolicy; legacy без policy → null.
  const currentAttempt = (mission?.attemptCount ?? 0) + 1
  const maxAttempts = mission?.maxAttempts ?? null
  const isLastAttempt = maxAttempts !== null && currentAttempt === maxAttempts

  const attemptLabel =
    maxAttempts !== null
      ? `ПОПЫТКА ${currentAttempt} / ${maxAttempts}${
          isLastAttempt ? ' (ПОСЛЕДНЯЯ)' : ''
        }`
      : `ПОПЫТКА ${currentAttempt}`

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

      {/* Sprint 8.x-4a: игровая часть вынесена в переиспользуемый CipherGame.
          Подготовка данных (parseCipherContent/buildDrums) и обработка ответа
          остаются здесь; поведение solo не меняется. */}
      {mission && <div className="cipher-timer">{attemptLabel}</div>}

      <CipherGame
        drums={gameDrums}
        correctCode={correctCodeChars}
        timeLimitSeconds={content?.timeLimitSeconds ?? null}
        onSubmit={handleSubmit}
        isSubmitting={submitting}
        resetSignal={resetSignal}
        initialIndices={gameIndices}
        onTimeout={() => setTimedOut(true)}
        onReset={handleReset}
        error={error}
      />
    </section>
  )
}