import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  createTeamSession,
  getEngineBootstrap,
  getTeamSessions,
  markTeamSessionReady,
  type EngineMission,
  type EngineTeamSession,
} from '../../api/engineApi'

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
            <p>
              Игра началась! Здесь появится мини-игра (3 попытки, провал
              одного — провал всех).
            </p>
          )}
        </div>
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}