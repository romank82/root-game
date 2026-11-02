import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { useEffect, useRef, useState } from 'react'
import type {
  EngineActiveTeamSession,
  EngineInventoryItem,
  EngineMission,
  MissionSubmission,
} from '../../api/engineApi'
import {
  getActiveTeamSessions,
  joinTeamSession,
  leaveTeamSession,
} from '../../api/engineApi'
import type { ApiStatus, Screen } from '../../types/game'
import { Sidebar } from '../Sidebar'
import { CooldownCountdown } from '../CooldownCountdown'
import { MissionTimer } from '../MissionTimer'
import { MissionModal } from '../MissionModal'
import { missionText } from '../../utils/missionHelpers'
import {
  MISSION_LAYER_COLORS,
  MISSION_LAYER_ORDER as LAYER_ORDER,
} from '../../constants/missionLayerColors'

// Окно отказа с возвратом платы (3 минуты после взятия миссии).
// Зеркало CANCEL_DEADLINE_SECONDS = 180 на бэкенде (mission_engine.py):
// cancel_deadline_at = started_at + 180с. Бэкенд пока не отдаёт
// cancelDeadlineAt в bootstrap — считаем на клиенте из startedAt.
const CANCEL_REFUSE_WINDOW_MS = 3 * 60 * 1000

// Парсинг timestamp как UTC-мгновения (поля bootstrap вида startedAt /
// sessionCreatedAt). Бэкенд шлёт ISO с суффиксом "+00:00"/Z (ensure_utc),
// но если строка придёт без таймзоны, JS Date.parse интерпретировал бы её
// как ЛОКАЛЬНОЕ время, и дедлайн сместился бы в прошлое (таймер «истёк»).
// Наивные строки трактуем как UTC (приписываем 'Z'), невалидные → null.
function parseUtcTimestamp(value: string | null | undefined): number | null {
  if (!value) return null
  const hasTimezoneSuffix = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  const normalized = hasTimezoneSuffix ? value : `${value}Z`
  const ms = Date.parse(normalized)
  return Number.isFinite(ms) ? ms : null
}

interface TerminalScreenProps {
  echo: number
  apiStatus: ApiStatus
  missions: EngineMission[]
  rootBalance: number
  inventory: EngineInventoryItem[]
  onScreenChange: (screen: Screen) => void
  onSubmitMission: (
    missionId: string,
    payload: { answer?: string },
  ) => Promise<MissionSubmission | null>
  onAcceptMission: (
    missionId: string,
  ) => Promise<{ accepted: boolean; error?: string }>
  onExpireMission: (
    missionId: string,
  ) => Promise<{ ok: boolean; error?: string }>
}

function missionStatusLabel(
  t: TFunction,
  status: EngineMission['status'],
): string {
  return t(`terminal.missionStatus.${status}`, 'ДОСТУПНО')
}

export function TerminalScreen({
  echo,
  apiStatus,
  missions,
  rootBalance,
  inventory,
  onScreenChange,
  onAcceptMission,
  onExpireMission,
}: TerminalScreenProps) {
  const { t } = useTranslation(['terminal', 'common'])
  const [acceptingId, setAcceptingId] = useState<string | null>(null)
  const [acceptError, setAcceptError] = useState<string | null>(null)
  // Командные сессии, из которых игрок вышел (для «исчезновения» карточки
  // без полного bootstrap-refresh; следующий свежий bootstrap придёт из App).
  const [leftTeamSessionIds, setLeftTeamSessionIds] = useState<string[]>([])
  // Уведомление о результате отказа от командной сессии.
  const [teamLeaveNote, setTeamLeaveNote] = useState<string | null>(null)
  const [selectedMission, setSelectedMission] =
    useState<EngineMission | null>(null)
  const [showArchive, setShowArchive] = useState(false)
  const [openLayer, setOpenLayer] = useState<'story' | 'team' | 'solo'>('story')
  // Sprint 8.x-4-join-gps: подвкладка «Активные» в папке «Командные» —
  // чужие лобби в сборе (свободные места, та же страна, ≤50 км до команды).
  const [teamTab, setTeamTab] = useState<'mine' | 'active'>('mine')
  const [activeSessions, setActiveSessions] = useState<
    EngineActiveTeamSession[]
  >([])
  const [activeLoading, setActiveLoading] = useState(false)
  const [activeError, setActiveError] = useState<string | null>(null)
  const [joiningSessionId, setJoiningSessionId] = useState<string | null>(null)
  // GPS кэшируем на время экрана: подвкладку можно открывать повторно,
  // разрешение не запрашиваем заново (один getCurrentPosition на сессию).
  const geoCacheRef = useRef<{
    latitude: number
    longitude: number
    accuracy: number | null
  } | null>(null)

  useEffect(() => {
    // Автовыбор: первая непустая папка (story → team → solo).
    // Если у всех пусто — остаётся story.
    const order: Array<'story' | 'team' | 'solo'> = ['story', 'team', 'solo']
    const firstNonEmpty = order.find(
      (layer) => missionsByLayer[layer].length > 0,
    )
    if (firstNonEmpty !== undefined) {
      setOpenLayer(firstNonEmpty)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missions])

  // Ordering and player-visible status come from authenticated bootstrap.
  // Sprint 8.13: раньше фильтр был === 'text_answer' и отсекал cipher/code_repair.
  // Командные миссии (missionType === 'team') НЕ вырезаем: папка «КОМАНДНЫЕ»
  // группирует их по missionLayer === 'team' (как solo/story).
  const textMissions = missions

  // Sprint 8.14 (fix): миссия с cooldown (availableAgainAt) — всегда
  // в активном списке, независимо от статуса (completed или expired).
  const activeMissions = textMissions.filter(
    (mission) =>
      mission.availableAgainAt !== null ||
      (mission.status !== 'completed' &&
        !(mission.status === 'expired' && mission.availableAgainAt === null)),
  )

  const archivedMissions = textMissions.filter(
    (mission) =>
      mission.availableAgainAt === null &&
      (mission.status === 'completed' ||
        (mission.status === 'expired' && mission.availableAgainAt === null)),
  )

  // Группировка активных миссий по слоям.
  const LAYER_LABEL: Record<typeof LAYER_ORDER[number], string> = {
    story: t('terminal.sections.story'),
    team: t('terminal.sections.team'),
    solo: t('terminal.sections.individual'),
  }
  const missionsByLayer = {
    story: activeMissions.filter((m) => m.missionLayer === 'story'),
    team: activeMissions.filter((m) => m.missionLayer === 'team'),
    solo: activeMissions.filter((m) => m.missionLayer === 'solo'),
  }

  // Счётчик доступных/всего для заголовка секции.
  const layerCounts = {
    story: {
      available: missionsByLayer.story.filter((m) => m.status === 'available' || m.status === 'in_progress').length,
      total: missionsByLayer.story.length,
    },
    team: {
      available: missionsByLayer.team.filter((m) => m.status === 'available' || m.status === 'in_progress').length,
      total: missionsByLayer.team.length,
    },
    solo: {
      available: missionsByLayer.solo.filter((m) => m.status === 'available' || m.status === 'in_progress').length,
      total: missionsByLayer.solo.length,
    },
  }

  async function handleAccept(mission: EngineMission) {
    setAcceptError(null)
    setAcceptingId(mission.id)
    const result = await onAcceptMission(mission.id)
    setAcceptingId(null)
    if (!result.accepted) {
      setAcceptError(result.error ?? t('terminal.errors.takeMissionFailed'))
      return
    }
    // После accept переходим на карту — там будут круги.
    onScreenChange('map')
  }

  // Отказ от командной сессии: leave_team_session возвращает плату в окне
  // 3 минут с момента создания (refunded), затем карточка сессии исчезает.
  async function handleLeaveTeamMission(mission: EngineMission) {
    try {
      // Sprint 8.x-4-refuse-fix: эндпоинт leave_team_session ждёт id сессии
      // (team-session-...), а не mission.id. sessionId приходит в bootstrap
      // (mission.sessionId); fallback на mission.id — для старых ответов
      // (бэкенд раньше не отдавал sessionId, _leave_team_session умеет искать
      // активную сессию игрока по id миссии).
      const result = await leaveTeamSession(mission.sessionId ?? mission.id)
      if (result.left) {
        setTeamLeaveNote(
          result.refunded
            ? 'Плата возвращена'
            : 'Вы вышли из командной сессии',
        )
        // Оптимистично скрываем блок сессии (bootstrap обновится в App).
        setLeftTeamSessionIds((ids) => [...ids, mission.id])
      }
    } catch (err) {
      setTeamLeaveNote(
        err instanceof Error
          ? err.message
          : t('terminal.errors.leaveSessionFailed'),
      )
    }
  }

  // ---- Sprint 8.x-4-join-gps: GPS + подвкладка «Активные» ----------------

  // GPS-координаты (паттерн useGameState.acceptMission / TeamSessionScreen).
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

  // Координаты + человекочитаемая ошибка GPS; кэш на время экрана
  // (повторное открытие подвкладки не запрашивает разрешение заново).
  async function getCoords(): Promise<{
    latitude: number
    longitude: number
    accuracy: number | null
  }> {
    if (geoCacheRef.current !== null) {
      return geoCacheRef.current
    }

    let position: GeolocationPosition
    try {
      position = await getCurrentPosition()
    } catch (geoErr) {
      const code =
        geoErr instanceof GeolocationPositionError ? geoErr.code : null
      const message =
        code === 1
          ? 'Отказано в доступе к геолокации. Разрешите доступ и повторите.'
          : code === 2
            ? 'Не удалось определить местоположение. Повторите попытку.'
            : code === 3
              ? 'Таймаут геолокации. Повторите попытку.'
              : (geoErr as Error).message
      throw new Error(message)
    }

    const { latitude, longitude, accuracy } = position.coords
    const coords = {
      latitude,
      longitude,
      accuracy: Number.isFinite(accuracy) && accuracy > 0 ? accuracy : null,
    }
    geoCacheRef.current = coords
    return coords
  }

  async function loadActiveSessions() {
    setActiveLoading(true)
    setActiveError(null)
    try {
      const coords = await getCoords()
      const result = await getActiveTeamSessions(
        coords.latitude,
        coords.longitude,
      )
      setActiveSessions(result.sessions)
    } catch (err) {
      setActiveError((err as Error).message)
    } finally {
      setActiveLoading(false)
    }
  }

  // Вступление из карточки: GPS + join. Бэкенд проверяет страну и «рядом»
  // (≤50 км) ДО списания entry fee; при отказе — 409 с текстом.
  async function handleJoinActive(target: EngineActiveTeamSession) {
    setActiveError(null)
    setJoiningSessionId(target.id)
    try {
      const coords = await getCoords()
      await joinTeamSession(
        target.id,
        coords.latitude,
        coords.longitude,
        coords.accuracy,
      )
      setActiveSessions((items) =>
        items.filter((item) => item.id !== target.id),
      )
      onScreenChange('team-session')
    } catch (err) {
      setActiveError((err as Error).message)
    } finally {
      setJoiningSessionId(null)
    }
  }

  // Sprint 8.x-4-active-refresh: «Активные» без кэша (activeLoaded убран) —
  // подвкладка перезагружается при каждом открытии: список лобби и GPS
  // всегда свежие. GPS берётся из geoCacheRef (разрешение не спрашиваем заново).
  useEffect(() => {
    // «АКТИВНЫЕ» (чужие лобби) не зависят от наличия своих миссий: при пустом
    // activeMissions папки не рендерятся, поэтому подвкладка вынесена отдельным
    // блоком (см. ветку «НЕТ ДОСТУПНЫХ») и грузится по тому же клику.
    const activeTabOpen =
      teamTab === 'active' &&
      (openLayer === 'team' || activeMissions.length === 0)
    if (!activeTabOpen) return
    void loadActiveSessions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openLayer, teamTab])

  // Подвкладки папки «Командные»: свои сессии и чужие лобби рядом.
  // Вынесены в helper, чтобы использовать и в папке, и в блоке при пустом
  // активном списке миссий (папки там не рендерятся).
  function renderTeamTabs() {
    return (
      <div style={{ display: 'flex', gap: 8, margin: '0 0 12px' }}>
        <button
          type="button"
          onClick={() => setTeamTab('mine')}
          style={{
            background: teamTab === 'mine' ? '#00ff88' : 'transparent',
            color: teamTab === 'mine' ? '#000' : 'inherit',
            border: '1px solid #00ff88',
            padding: '6px 12px',
            borderRadius: 6,
            fontWeight: 'bold',
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          {t('terminal.sections.mySessions')}
        </button>
        <button
          type="button"
          onClick={() => {
            // Нажатие на уже активную подвкладку — перезагрузка
            // (эффект не сработает: teamTab не меняется).
            if (teamTab === 'active') {
              void loadActiveSessions()
              return
            }
            setTeamTab('active')
          }}
          style={{
            background: teamTab === 'active' ? '#00ff88' : 'transparent',
            color: teamTab === 'active' ? '#000' : 'inherit',
            border: '1px solid #00ff88',
            padding: '6px 12px',
            borderRadius: 6,
            fontWeight: 'bold',
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          {t('terminal.sections.activeSessions')}
        </button>
      </div>
    )
  }

  function renderActiveSessions() {
    return (
      <>
        {activeError && <p className="repair-error">{activeError}</p>}
        {activeLoading && <p className="admin-muted">{t('terminal.empty.searchingSessions')}</p>}
        {!activeLoading && activeSessions.length === 0 && (
          <p className="layer-empty">{t('terminal.empty.noActiveSessions')}</p>
        )}
        {activeSessions.map((item) => (
          <article className="puzzle" key={item.id}>
            <span className="file-label">
              {item.missionTitle ?? 'Командная миссия'}
            </span>
            <small>СТАТУС: СБОР</small>
            <h3>{item.description ?? 'Без описания'}</h3>
            <p className="team-member-count">
              {item.memberCount}/{item.maxMembers ?? '?'} — свободно:{' '}
              {item.freeSlots ?? '?'}
            </p>
            <p className="in-progress-hint">
              До команды:{' '}
              {item.distanceKm !== null ? `${item.distanceKm} км` : '—'}
            </p>
            <button
              type="button"
              className="primary-button"
              disabled={joiningSessionId !== null}
              onClick={() => void handleJoinActive(item)}
            >
              {joiningSessionId === item.id
                ? t('terminal.buttons.joining')
                : t('terminal.buttons.join')}
            </button>
          </article>
        ))}
      </>
    )
  }

  function renderMissionCard(mission: EngineMission) {
    const isCompleted = mission.status === 'completed'
    const isExpired = mission.status === 'expired'
    const isLocked = mission.status === 'locked'
    const isInProgress = mission.status === 'in_progress'

    // Sprint 8.x: цена входа (atomic ROOT) и требуемые ключи из runtime policy.
    const missingRoot =
      typeof mission.entryRoot === 'number' &&
      mission.entryRoot > 0 &&
      rootBalance < mission.entryRoot
    const requiredItems = mission.requiredItems ?? []
    const hasAllKeys = requiredItems.every((requirement) => {
      const owned =
        inventory.find((item) => item.id === requirement.itemId)?.quantity ?? 0
      return owned >= requirement.quantity
    })

    // Sprint 8.x: публичные награды миссии (mission.rewards). Валютная награда
    // снижается с каждой попыткой → помечаем «До». Пустые/неизвестные типы
    // пропускаем.
    const rewardLabels = (mission.rewards ?? [])
      .map((reward) => {
        if (reward.type === 'currency' && typeof reward.amount === 'number') {
          return `До ${reward.amount} ROOT`
        }
        if (reward.type === 'item' && reward.itemId) {
          // Человекочитаемый код из CMS (TEST_KEY_003); если его нет —
          // системный itemId.
          return `Предмет: ${reward.itemCode ?? reward.itemId}`
        }
        if (reward.type === 'story_node' && reward.storyNodeId) {
          return `Сюжетный узел: ${reward.storyNodeId}`
        }
        return null
      })
      .filter((label): label is string => label !== null)

    // Окно отказа с возвратом платы: cancel_deadline_at = started_at + 3 мин.
    // (бэкенд пока не отдаёт его в bootstrap — вычисляем на клиенте).
    const cancelDeadlineAt = mission.startedAt
      ? new Date(
          new Date(mission.startedAt).getTime() + CANCEL_REFUSE_WINDOW_MS,
        ).toISOString()
      : null

    // Окно отказа с возвратом для командной сессии считаем от accept/create —
    // sessionCreatedAt, как в solo от startedAt (accept = оплата).
    // Парсим строго как UTC: без суффикса таймзоны JS принял бы строку за
    // локальное время, и дедлайн «истёк» сразу после Ready.
    const sessionCreatedUtcMs = parseUtcTimestamp(mission.sessionCreatedAt)
    const teamCancelDeadlineAt =
      sessionCreatedUtcMs !== null
        ? new Date(sessionCreatedUtcMs + CANCEL_REFUSE_WINDOW_MS).toISOString()
        : null
    // Sprint 8.x-4-ux-fix: окно отказа с ВОЗВРАТОМ открыто, пока дедлайн не
    // прошёл. После — _leave_team_session всё ещё разрешает выход, но БЕЗ
    // возврата платы, поэтому таймер скрываем (кнопка остаётся).
    const teamCancelWindowOpen =
      teamCancelDeadlineAt !== null &&
      new Date(teamCancelDeadlineAt).getTime() > Date.now()

    return (
      <article className="puzzle" key={mission.id}>
        <span className="file-label">
          {missionText(mission, 'label', mission.title)}
        </span>
        <small>СТАТУС: {missionStatusLabel(t, mission.status)}</small>
        <h3>
          {missionText(mission, 'question', mission.description)}
        </h3>

        {mission.availableAgainAt !== null ? (
          <div className="expired-file">
            <p>{t('terminal.status.onBreak')}</p>
            <p className="expired-hint">
              {t('terminal.status.availableAgainIn')}{' '}
              <CooldownCountdown availableAgainAt={mission.availableAgainAt} />
            </p>
          </div>
        ) : isCompleted ? (
          <div className="success">
            <strong>
              {missionText(
                mission,
                'successTitle',
                t('terminal.status.packageConfirmed'),
              )}
            </strong>
            <p>
              {missionText(
                mission,
                'successText',
                t('terminal.status.progressConfirmed'),
              )}
            </p>
          </div>
        ) : isExpired ? (
          <div className="expired-file">
            <p>{t('terminal.status.timeUp')}</p>
            <p className="expired-hint">{t('terminal.status.missionOneTime')}</p>
            <button
              className="expired-remove"
              onClick={() => void onExpireMission(mission.id)}
            >
              {t('terminal.buttons.remove')}
            </button>
          </div>
        ) : isLocked ? (
          <div className="locked-file">
            <span>?</span>
            <div>
              <strong>{t('terminal.status.packageUnavailable')}</strong>
              <small>{t('terminal.status.serverWillOpen')}</small>
            </div>
          </div>
        ) : isInProgress ? (
          <div className="accept-row">
            <p className="in-progress-hint">
              {t('terminal.status.missionActive')}
            </p>
            {mission.missionType === 'team' && (
              <p className="team-member-count">
                {mission.sessionMemberCount ?? 0}/{mission.maxMembers ?? 0}
                {' — '}
                {((mission.sessionMemberCount ?? 0) < (mission.maxMembers ?? 0))
                  ? t('terminal.status.waitingPlayers')
                  : t('terminal.status.teamAssembled')}
              </p>
            )}
            <button onClick={() => onScreenChange('map')}>
              {t('terminal.buttons.openMap')}
            </button>

            {cancelDeadlineAt && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  flexWrap: 'wrap',
                }}
              >
                <MissionTimer
                  mode="cancel"
                  deadlineAt={cancelDeadlineAt}
                  label="до конца отказа с возвратом"
                />
                <button
                  type="button"
                  style={{
                    background: '#00ff88',
                    color: '#000',
                    border: 'none',
                    padding: '8px 14px',
                    borderRadius: 6,
                    fontWeight: 'bold',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                  onClick={() => void onExpireMission(mission.id)}
                >
                  {t('terminal.buttons.refuse')}
                </button>
              </div>
            )}
          </div>
        ) : mission.missionType === 'team' &&
          mission.sessionStatus &&
          !leftTeamSessionIds.includes(mission.id) ? (
          <div className="accept-row">
            <p className="team-member-count">
              {mission.sessionMemberCount ?? 0}/{mission.maxMembers ?? 0}
              {' — '}
              {((mission.sessionMemberCount ?? 0) < (mission.maxMembers ?? 0))
                ? t('terminal.status.waitingPlayers')
                : t('terminal.status.teamAssembled')}
            </p>

            {/* Sprint 8.x-4-nav: вход в экран командной сессии (мини-игра).
                TeamSessionScreen сам подтягивает сессию игрока. */}
            <button
              type="button"
              onClick={() => onScreenChange('team-session')}
            >
              {t('terminal.buttons.openSession')}
            </button>

            {mission.sessionStatus === 'active' ? (
              <p className="in-progress-hint">{t('terminal.status.gameInProgress')}</p>
            ) : mission.sessionStatus === 'collecting' ||
              mission.sessionStatus === 'ready_to_start' ? (
              <>
                {/* Таймер — только пока открыто окно отказа С возвратом
                    платы (3 мин); после дедлайна возврата нет, таймер скрыт. */}
                {teamCancelWindowOpen && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      flexWrap: 'wrap',
                    }}
                  >
                    <MissionTimer
                      mode="cancel"
                      deadlineAt={teamCancelDeadlineAt}
                      label="до конца отказа с возвратом"
                    />
                  </div>
                )}
                {/* Sprint 8.x-4-ux-fix: отказ разрешён бэкендом и в
                    collecting, и в ready_to_start (409 только в active);
                    после дедлайна — без возврата платы, но выход остаётся. */}
                <button
                  type="button"
                  style={{
                    background: '#00ff88',
                    color: '#000',
                    border: 'none',
                    padding: '8px 14px',
                    borderRadius: 6,
                    fontWeight: 'bold',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                  onClick={() => void handleLeaveTeamMission(mission)}
                >
                  {t('terminal.buttons.refuse')}
                </button>
              </>
            ) : null}
          </div>
        ) : (
          <>
            {typeof mission.entryRoot === 'number' && mission.entryRoot > 0 && (
              <>
                <p>Вход: {mission.entryRoot} ROOT</p>
                {missingRoot && (
                  <p className="repair-error">
                    {t('terminal.errors.notEnoughRoot', {
                      amount: mission.entryRoot - rootBalance,
                    })}
                  </p>
                )}
              </>
            )}

            {requiredItems.length > 0 && (
              <p className={hasAllKeys ? undefined : 'repair-error'}>
                Требуемые ключи:{' '}
                {requiredItems
                  .map(
                    (requirement) =>
                      `${requirement.itemCode ?? requirement.itemId} (${requirement.quantity})`,
                  )
                  .join(', ')}
              </p>
            )}

            {rewardLabels.length > 0 && (
              <p>Возможные награды: {rewardLabels.join(', ')}</p>
            )}

            <div className="accept-row">
              <button onClick={() => setSelectedMission(mission)}>
                {t('terminal.buttons.view')}
              </button>
            </div>
          </>
        )}
      </article>
    )
  }

  return (
    <section className="terminal-layout">
      <Sidebar
        echo={echo}
        apiStatus={apiStatus}
        onScreenChange={onScreenChange}
      />

      <div className="terminal-content">
        <p className="eyebrow">{t('terminal.header.contourConnected')}</p>
        <h2>{t('terminal.header.availablePackages')}</h2>

        <div className="log-window">
          <p>{t('terminal.header.systemContentReceived')}</p>
          <p>{t('terminal.header.systemResultsReceived')}</p>
        </div>

        {acceptError && (
          <p className="repair-error">{acceptError}</p>
        )}

        {teamLeaveNote && (
          <p
            style={{
              margin: '0 0 12px',
              color: '#65e9ae',
              fontSize: 13,
            }}
          >
            {teamLeaveNote}
          </p>
        )}

        {activeMissions.length === 0 ? (
          <>
            <section className="location-status">
              <span className="location-status-icon">⌖</span>
              <div>
                <strong>{t('terminal.empty.noTextPackages')}</strong>
                <p>{t('terminal.empty.publishedPackageHint')}</p>
              </div>
            </section>

            {/* «АКТИВНЫЕ» (чужие лобби) не зависят от наличия своих миссий:
                при пустом activeMissions папки не рендерятся, поэтому
                подвкладка вынесена отдельным блоком. */}
            <section className="layer-folder">
              <p className="eyebrow">{LAYER_LABEL.team}</p>
              <div
                className="layer-folder-body"
                style={{ borderLeftColor: MISSION_LAYER_COLORS.team }}
              >
                {renderTeamTabs()}
                {teamTab === 'active' ? (
                  renderActiveSessions()
                ) : (
                  <p className="layer-empty">{t('terminal.empty.nothingYet')}</p>
                )}
              </div>
            </section>
          </>
        ) : (
          LAYER_ORDER.map((layer) => {
            const isOpen = openLayer === layer
            const total = layerCounts[layer].total
            const isEmpty = total === 0

            return (
              <section key={layer} className="layer-folder">
                <button
                  type="button"
                  className={`layer-folder-toggle${isOpen ? ' is-open' : ''}${isEmpty ? ' is-empty' : ''}`}
                  style={{ color: MISSION_LAYER_COLORS[layer] }}
                  onClick={() => setOpenLayer(layer)}
                >
                  <span className="layer-folder-icon">{isOpen ? '📂' : '📁'}</span>
                  <span className="layer-folder-name">{LAYER_LABEL[layer]}</span>
                  <span className="layer-folder-count">({total})</span>
                </button>

                {isOpen && (
                  <div
                    className="layer-folder-body"
                    style={{ borderLeftColor: MISSION_LAYER_COLORS[layer] }}
                  >
                    {/* Sprint 8.x-4-join-gps: подвкладки папки «Командные» —
                        свои сессии (как было) и чужие лобби рядом. */}
                    {layer === 'team' && renderTeamTabs()}

                    {layer === 'team' && teamTab === 'active' ? (
                      renderActiveSessions()
                    ) : isEmpty ? (
                      <p className="layer-empty">{t('terminal.empty.nothingYet')}</p>
                    ) : (
                      missionsByLayer[layer].map((mission) =>
                        renderMissionCard(mission),
                      )
                    )}
                  </div>
                )}
              </section>
            )
          })
        )}

        {/* АРХИВ */}
        {archivedMissions.length > 0 && (
          <section className="archive-section">
            <button
              className="archive-toggle"
              onClick={() => setShowArchive((v) => !v)}
            >
              {showArchive ? '▼' : '▶'} {t('terminal.sections.jobHistory')} ({archivedMissions.length})
            </button>

            {showArchive && (
              <div className="archive-list">
                {archivedMissions.map((mission) => (
                  <article className="archive-card" key={mission.id}>
                    <span className="file-label">
                      {missionText(mission, 'label', mission.title)}
                    </span>
                    <small>
                      СТАТУС:{' '}
                      {mission.status === 'completed'
                        ? t('terminal.missionStatus.completed')
                        : t('terminal.missionStatus.expired')}
                    </small>
                    <h3>{mission.title}</h3>
                    {mission.completedAt && (
                      <p className="archive-hint">
                        Завершено:{' '}
                        {new Date(mission.completedAt).toLocaleString()}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      {selectedMission && (
        <MissionModal
          mission={selectedMission}
          onClose={() => setSelectedMission(null)}
          onAccept={() => void handleAccept(selectedMission)}
          isAccepting={acceptingId === selectedMission.id}
          error={acceptError}
        />
      )}
    </section>
  )
}
