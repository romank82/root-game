import { useEffect, useRef, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  createTeamSession,
  devBotActivate,
  devBotJoin,
  devBotLocation,
  devBotPlayWave,
  devBotReady,
  devLocationMe,
  getEngineBootstrap,
  getTeamSessions,
  markTeamSessionReady,
  submitTeamLocation,
  submitTeamWave,
  type EngineMission,
  type EngineTeamSession,
} from '../../api/engineApi'
import { CipherGame } from '../CipherGame'

interface TeamSessionScreenProps {
  onScreenChange: (screen: Screen) => void
  // Командные миссии для формы создания (из App/bootstrap). Если не
  // переданы — экран сам сходит за bootstrap.
  missions?: EngineMission[]
  // Игрок пришёл с карты по клику на маркер миссии — предвыбор в форме.
  presetMissionId?: string | null
}

const TEAM_MISSION_LAYER = 'team'

// Sprint 8.x-4-dev-bot-ui: кнопки управления dev-ботом видны только в dev
// (vite dev server). В production build import.meta.env.DEV === false —
// ветка не рендерится и выкидывается минификатором. Удалим вместе с dev-bot.
const DEV_BOT_UI_ENABLED = import.meta.env.DEV

const SESSION_STATUS_LABELS: Record<string, string> = {
  collecting: 'Сбор команды',
  ready_to_start: 'Все готовы — ожидание авто-старта',
  active: 'Игра идёт',
  succeeded: 'Успех',
  failed: 'Провал',
  expired: 'Истекла',
  cancelled_before_start: 'Отменена до старта',
}

function listTeamMissions(all: EngineMission[]): EngineMission[] {
  return all.filter((mission) => mission.missionLayer === TEAM_MISSION_LAYER)
}

export function TeamSessionScreen({
  onScreenChange,
  missions,
  presetMissionId,
}: TeamSessionScreenProps) {
  // Активная сессия игрока (collecting/ready_to_start/active) или null.
  const [session, setSession] = useState<EngineTeamSession | null>(null)
  const [teamMissionsList, setTeamMissionsList] = useState<EngineMission[]>([])
  const [selectedMissionId, setSelectedMissionId] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [readyBusy, setReadyBusy] = useState(false)
  // Sprint 8.x-4b-2a: состояние командной мини-игры (волна cipher).
  const [waveSubmitting, setWaveSubmitting] = useState(false)
  const [waveError, setWaveError] = useState<string | null>(null)
  const [waveSuccess, setWaveSuccess] = useState<string | null>(null)
  // Sprint 8.x-4-dev-bot-ui: состояние кнопок dev-бота (только dev).
  const [devBotBusy, setDevBotBusy] = useState(false)
  const [devBotNotice, setDevBotNotice] = useState<string | null>(null)
  // Sprint 8.x-4-location-ui: отметка гео-присутствия (proof для активации).
  const [locationBusy, setLocationBusy] = useState(false)
  const [locationNotice, setLocationNotice] = useState<string | null>(null)
  const [locationOk, setLocationOk] = useState(false)
  // Инкремент при смене волны/«ЗАНОВО» → CipherGame пересобирает барабаны/таймер.
  const [resetSignal, setResetSignal] = useState(0)
  // Ключ текущей волны для сравнения при polling (не сбрасывать игру
  // каждые 3 сек — только при реальной смене волны/кода).
  const prevWaveKeyRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [sessionsResult, bootstrap] = await Promise.all([
          getTeamSessions(),
          missions ? Promise.resolve(missions) : getEngineBootstrap(),
        ])

        if (cancelled) return

        const teamOnes = listTeamMissions(
          Array.isArray(bootstrap) ? bootstrap : bootstrap.missions,
        )
        setTeamMissionsList(teamOnes)

        // Бэкенд отдаёт только активные сессии игрока (одна на игрока).
        const active: EngineTeamSession | null =
          (sessionsResult.sessions[0] ?? null) as EngineTeamSession | null
        setSession(active)

        const preset = presetMissionId
        setSelectedMissionId(
          active
            ? active.mission_id
            : preset && teamOnes.some((m) => m.id === preset)
              ? preset
              : (teamOnes[0]?.id ?? ''),
        )
      } catch (err) {
        if (!cancelled) setError((err as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [missions, presetMissionId])

  // Sprint 8.x-4b-1: polling игрового состояния, пока сессия в статусе
  // 'active' (идёт мини-игра). Обновляет весь session-объект — новые поля
  // 8.x-3 (currentWave/maxWaves/waveStatus/wavePlayedCount/myWavePlayed/
  // cipherSession) уже лежат в типе EngineTeamSession. Вне 'active' и без
  // сессии опрос не нужен. UI мини-игры — шаг 8.x-4b-2.
  const sessionId = session?.id ?? null
  const sessionActive = session?.status === 'active'

  useEffect(() => {
    if (!sessionId || !sessionActive) return

    let cancelled = false
    let warnedOnce = false

    async function poll() {
      try {
        const result = await getTeamSessions()
        if (cancelled) return
        // Подхватываем и финализацию (succeeded/failed): сессия уходит из
        // ответа либо меняет status → setSession завершит этот эффект.
        setSession((result.sessions[0] ?? null) as EngineTeamSession | null)
      } catch {
        // Не спамить консоль каждые 3 сек: один warning, дальше пропускаем
        // опрос, последнее известное состояние остаётся в стейте.
        if (!cancelled && !warnedOnce) {
          warnedOnce = true
          console.warn('Не удалось обновить состояние командной сессии')
        }
      }
    }

    void poll()
    const interval = window.setInterval(() => void poll(), 3000)

    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [sessionId, sessionActive])

  // Sprint 8.x-4b-2a: пересборка CipherGame при смене волны/сессии (новые
  // барабаны и таймер) + сброс сообщений результата. Ключ — session.id +
  // currentWave + correctCode: polling пересоздаёт объект session каждые 3 сек,
  // но ключ стабилен, пока не сменилась волна (или код после провала) — сброс
  // НЕ на каждом опросе.
  const waveKey =
    session && session.status === 'active'
      ? `${session.id}:${session.currentWave}:${session.cipherSession?.correctCode?.join('') ?? 'none'}`
      : null

  useEffect(() => {
    if (waveKey === null) {
      prevWaveKeyRef.current = null
      return
    }
    if (prevWaveKeyRef.current === null) {
      prevWaveKeyRef.current = waveKey
      return
    }
    if (prevWaveKeyRef.current !== waveKey) {
      prevWaveKeyRef.current = waveKey
      setResetSignal((value) => value + 1)
      setWaveError(null)
      setWaveSuccess(null)
    }
  }, [waveKey])

  async function handleCreate() {
    setError(null)
    setNotice(null)

    if (!selectedMissionId) {
      setError('Выберите командную миссию.')
      return
    }

    setCreating(true)
    try {
      const created = await createTeamSession(selectedMissionId)
      setSession(created)
      setNotice('Сессия создана. Друзья могут присоединиться по коду сессии.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setCreating(false)
    }
  }

  async function handleReady() {
    if (!session || session.status !== 'collecting') return

    setError(null)
    setNotice(null)
    setReadyBusy(true)
    try {
      const updated = await markTeamSessionReady(session.id)
      setSession(updated)
      setNotice('Вы готовы. Когда все отметятся и будут в зоне — старт автоматически.')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setReadyBusy(false)
    }
  }
  // Sprint 8.x-4b-2a: отправка cipher-ответа волны (submitTeamWave).
  async function handleSubmitWave(sequence: string[]) {
    if (!session) return
    setWaveSubmitting(true)
    setWaveError(null)
    setWaveSuccess(null)

    let accepted = false
    try {
      const result = await submitTeamWave(session.id, sequence)
      accepted = result.accepted
      if (!result.accepted) {
        setWaveError(result.message ?? 'Неверная комбинация.')
      } else if (result.sessionStatus === 'succeeded') {
        const rootText =
          result.awarded && result.awarded.root > 0
            ? ` +${result.awarded.root} ROOT`
            : ''
        setWaveSuccess(`Миссия пройдена!${rootText}`)
      } else {
        // Верно, но сыграли не все: волна остаётся 'playing' (ждём
        // остальных — плашка/блокировка в шаге 8.x-4b-2b).
        setWaveSuccess('Верно!')
      }
    } catch (err) {
      setWaveError((err as Error).message)
    } finally {
      setWaveSubmitting(false)
    }

    // После верного ответа — полный объект сессии (свежий myWavePlayed,
    // при финализации cipherSession=null/new). Частичный result из
    // submitTeamWave cipherSession не содержит. При провале волны свежий
    // объект принесёт polling (~3 сек) — чтобы игрок успел увидеть ошибку
    // до пересборки игры, здесь не обновляем.
    if (accepted) {
      try {
        const fresh = await getTeamSessions()
        setSession((current) => fresh.sessions[0] ?? current)
      } catch {
        // тихо: следующее polling обновит состояние.
      }
    }
  }

  // «ЗАНОВО» в командной волне: перезапуск таймера и позиций барабанов.
  function handleResetWave() {
    setWaveError(null)
    setResetSignal((value) => value + 1)
  }

  // Sprint 8.x-4-location-ui: GPS-координаты (паттерн useGameState.ts).
  function getCurrentPosition(): Promise<GeolocationPosition> {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error('Геолокация не поддерживается устройством.'))
        return
      }
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0,
      })
    })
  }

  // Отметить гео-присутствие в командной сессии: свежий verified proof нужен
  // для активации (все готовы + все в зоне). Бэкенд принимает proof только
  // в статусах 'collecting' / 'ready_to_start'.
  async function handleSubmitLocation() {
    if (!session) return
    if (session.status !== 'collecting' && session.status !== 'ready_to_start') {
      return
    }
    setLocationBusy(true)
    setLocationNotice(null)
    try {
      let coords: GeolocationPosition
      try {
        coords = await getCurrentPosition()
      } catch (geoErr) {
        const code =
          geoErr instanceof GeolocationPositionError ? geoErr.code : null
        const geoMessage =
          code === 1
            ? 'Отказано в доступе к геолокации. Разрешите доступ и повторите.'
            : code === 2
              ? 'Не удалось определить местоположение. Повторите попытку.'
              : code === 3
                ? 'Таймаут геолокации. Повторите попытку.'
                : (geoErr as Error).message
        throw new Error(geoMessage)
      }

      const result = await submitTeamLocation(
        session.id,
        coords.coords.latitude,
        coords.coords.longitude,
        coords.coords.accuracy,
      )
      if (result.verified) {
        setLocationOk(true)
        setLocationNotice('Присутствие подтверждено.')
      } else {
        setLocationOk(false)
        setLocationNotice('Вы вне зоны миссии. Подойдите ближе и попробуйте снова.')
      }

      // Свежее состояние сессии (возможен авто-старт/смена статуса).
      try {
        const fresh = await getTeamSessions()
        setSession((current) => fresh.sessions[0] ?? current)
      } catch {
        // тихо: polling обновит состояние.
      }
    } catch (err) {
      setLocationOk(false)
      setLocationNotice(`Ошибка: ${(err as Error).message}`)
    } finally {
      setLocationBusy(false)
    }
  }

  // Sprint 8.x-4-dev-bot-ui: выполнить действие dev-бота (только dev).
  // После каждого вызова подтягиваем свежее состояние сессии, чтобы волны/
  // статус сразу отразились на экране.
  async function runDevBot(
    action:
      | 'join'
      | 'ready'
      | 'location'
      | 'locationMe'
      | 'activate'
      | 'playWave',
  ) {
    if (!session) return
    setDevBotBusy(true)
    setDevBotNotice(null)
    try {
      const callers: Record<
        typeof action,
        () => Promise<Record<string, unknown>>
      > = {
        join: () => devBotJoin(session.id),
        ready: () => devBotReady(session.id),
        location: () => devBotLocation(session.id),
        locationMe: () => devLocationMe(session.id),
        activate: () => devBotActivate(session.id),
        playWave: () => devBotPlayWave(session.id),
      }
      const result = await callers[action]()
      setDevBotNotice(`БОТ: ${JSON.stringify(result)}`)
      try {
        const fresh = await getTeamSessions()
        setSession((current) => fresh.sessions[0] ?? current)
      } catch {
        // тихо: polling обновит состояние.
      }
    } catch (err) {
      setDevBotNotice(`БОТ: ошибка — ${(err as Error).message}`)
    } finally {
      setDevBotBusy(false)
    }
  }

  return (
    <section className="inventory">
      <p className="eyebrow">КОМАНДНАЯ МИССИЯ / СЕССИЯ</p>
      <h2>Командные сессии</h2>

      {loading && <p>Загрузка…</p>}

      {error && <p className="repair-error">{error}</p>}
      {notice && <p className="mission-success-card">{notice}</p>}

      {!loading && session === null && (
        <div className="gas-block">
          <h3>Создать сессию</h3>

          <label>
            Миссия
            <select
              value={selectedMissionId}
              disabled={creating}
              onChange={(e) => setSelectedMissionId(e.target.value)}
            >
              <option value="">Выберите командную миссию</option>
              {teamMissionsList.map((mission) => (
                <option key={mission.id} value={mission.id}>
                  {mission.title}
                </option>
              ))}
            </select>
          </label>

          {teamMissionsList.length === 0 && (
            <p className="admin-muted">Командных миссий пока нет.</p>
          )}

          <button
            type="button"
            className="primary-button"
            disabled={creating || teamMissionsList.length === 0}
            onClick={handleCreate}
          >
            {creating ? 'Создаём…' : 'Создать сессию'}
          </button>
        </div>
      )}

      {!loading && session !== null && (
        <div className="gas-block">
          <h3>{session.missionTitle ?? session.mission_id}</h3>

          <p>
            Статус:{' '}
            <b>{SESSION_STATUS_LABELS[session.status] ?? session.status}</b>
          </p>
          <p>
            Участников: <b>{session.memberCount}</b>
          </p>

          {session.status === 'collecting' && (
            <>
              {session.myStatus === 'joined' && (
                <button
                  type="button"
                  className="primary-button"
                  disabled={readyBusy}
                  onClick={handleReady}
                >
                  {readyBusy ? 'Отправка…' : 'Ready — я готов(а)'}
                </button>
              )}
              {session.myStatus === 'ready' && (
                <p>
                  Вы отметились ({String(!!session.myReadyAt)}). Ждём остальных
                  участников.
                </p>
              )}
            </>
          )}

          {session.status === 'ready_to_start' && (
            <p>
              Все готовы. Как только у всех участников будет свежая отметка
              присутствия в зоне миссии — игра начнётся автоматически.
            </p>
          )}

          {/* Sprint 8.x-4-location-ui: отметка гео-присутствия (proof нужен
              для активации; бэкенд принимает в collecting/ready_to_start). */}
          {(session.status === 'collecting' ||
            session.status === 'ready_to_start') && (
            <div>
              <button
                type="button"
                className="primary-button"
                disabled={locationBusy}
                onClick={() => void handleSubmitLocation()}
              >
                {locationBusy ? 'Отправка…' : 'ОТМЕТИТЬ ПРИСУТСТВИЕ'}
              </button>
              {locationNotice && (
                <p
                  className={
                    locationOk ? 'mission-success-card' : 'repair-error'
                  }
                >
                  {locationNotice}
                </p>
              )}
            </div>
          )}

          {session.status === 'active' && (
            <>
              {/* Счётчик — как в solo (cipher-timer), переиспользуем класс. */}
              <div className="cipher-timer">
                ПОПЫТКА {session.currentWave} / {session.maxWaves}
              </div>

              {session.cipherSession ? (
                <CipherGame
                  drums={session.cipherSession.drums}
                  correctCode={session.cipherSession.correctCode}
                  timeLimitSeconds={session.cipherSession.timeLimitSeconds}
                  onSubmit={handleSubmitWave}
                  isSubmitting={waveSubmitting}
                  resetSignal={resetSignal}
                  onReset={handleResetWave}
                  // CipherGame сам рендерит ошибку (repair-error) — не дублируем.
                  error={waveError}
                  title="КОМАНДНАЯ МИНИ-ИГРА"
                />
              ) : (
                <p>Игровая сессия завершена.</p>
              )}

              {waveSuccess && (
                <p className="mission-success-card">{waveSuccess}</p>
              )}
            </>
          )}

          {/* Sprint 8.x-4-dev-bot-ui: временные кнопки dev-бота. Показываются
              при любой активной сессии (collecting/ready_to_start/active) —
              join/ready/location/activate нужны ДО старта игры. session на этом
              уровне гарантированно не null (блок под {!loading && session !==
              null}). Удаляются вместе с dev-bot. */}
          {DEV_BOT_UI_ENABLED && (
            <div className="dev-bot-panel">
              <p className="admin-muted">
                DEV: управление ботом (временно, удалим после проверки)
              </p>
              <div className="repair-actions dev-bot-actions">
                <button
                  type="button"
                  className="repair-clear-button"
                  disabled={devBotBusy}
                  onClick={() => void runDevBot('join')}
                >
                  БОТ: вступить
                </button>
                <button
                  type="button"
                  className="repair-clear-button"
                  disabled={devBotBusy}
                  onClick={() => void runDevBot('ready')}
                >
                  БОТ: готов
                </button>
                <button
                  type="button"
                  className="repair-clear-button"
                  disabled={devBotBusy}
                  onClick={() => void runDevBot('location')}
                >
                  БОТ: на месте
                </button>
                <button
                  type="button"
                  className="repair-clear-button"
                  disabled={devBotBusy}
                  onClick={() => void runDevBot('locationMe')}
                >
                  БОТ: я на месте
                </button>
                <button
                  type="button"
                  className="repair-clear-button"
                  disabled={devBotBusy}
                  onClick={() => void runDevBot('activate')}
                >
                  БОТ: старт
                </button>
                <button
                  type="button"
                  className="repair-clear-button"
                  disabled={devBotBusy}
                  onClick={() => void runDevBot('playWave')}
                >
                  БОТ: пройти волну
                </button>
              </div>
              {devBotNotice && (
                <p className="dev-bot-notice">{devBotNotice}</p>
              )}
            </div>
          )}
        </div>
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}