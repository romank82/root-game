import { useEffect, useRef, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  createTeamSession,
  getEngineBootstrap,
  getTeamSessions,
  markTeamSessionReady,
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
        </div>
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}