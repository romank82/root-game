import { useEffect, useState } from 'react'
import type {
  EngineInventoryItem,
  EngineMission,
  MissionSubmission,
} from '../../api/engineApi'
import { leaveTeamSession } from '../../api/engineApi'
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

function missionStatusLabel(status: EngineMission['status']): string {
  if (status === 'completed') {
    return 'РАСШИФРОВАНО'
  }
  if (status === 'locked') {
    return 'НЕДОСТУПНО'
  }
  if (status === 'in_progress') {
    return 'В ПРОЦЕССЕ'
  }
  if (status === 'expired') {
    return 'ПРОВАЛЕНО'
  }
  if (status === 'cancelled') {
    return 'ОТМЕНЕНО'
  }
  return 'ДОСТУПНО'
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
    story: 'СЮЖЕТНЫЕ',
    team: 'КОМАНДНЫЕ',
    solo: 'ИНДИВИДУАЛЬНЫЕ',
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
      setAcceptError(result.error ?? 'Не удалось взять миссию.')
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
        err instanceof Error ? err.message : 'Не удалось выйти из сессии.',
      )
    }
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

    // Окно отказа с возвратом для командной сессии считаем от МОМЕНТА ОПЛАТЫ —
    // своего ready_at (бэкенд отдаёт mission.myReadyAt), как в solo от
    // startedAt (accept = оплата). Раньше считали от sessionCreatedAt, и время
    // лобби (ожидание других участников) съедало 3 минуты: к моменту Ready окно
    // уже было закрыто → refunded=False.
    // Парсим строго как UTC: без суффикса таймзоны JS принял бы строку за
    // локальное время, и дедлайн «истёк» сразу после Ready.
    // Поле новое: типизируем локально, чтобы не расширять EngineMission в этом
    // шаге (кандидат на добавление в тип engineApi.ts отдельным коммитом).
    const myReadyAtRaw = (
      mission as EngineMission & { myReadyAt?: string | null }
    ).myReadyAt
    const myReadyUtcMs = parseUtcTimestamp(myReadyAtRaw)
    // ready_at нет (ещё не Ready) → взнос не списан, возврата не будет:
    // таймер не показываем, кнопка «ОТКАЗАТЬСЯ» остаётся.
    const teamCancelDeadlineAt =
      myReadyUtcMs !== null
        ? new Date(myReadyUtcMs + CANCEL_REFUSE_WINDOW_MS).toISOString()
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
        <small>СТАТУС: {missionStatusLabel(mission.status)}</small>
        <h3>
          {missionText(mission, 'question', mission.description)}
        </h3>

        {mission.availableAgainAt !== null ? (
          <div className="expired-file">
            <p>НА ПЕРЕРЫВЕ</p>
            <p className="expired-hint">
              Доступна снова через:{' '}
              <CooldownCountdown availableAgainAt={mission.availableAgainAt} />
            </p>
          </div>
        ) : isCompleted ? (
          <div className="success">
            <strong>
              {missionText(
                mission,
                'successTitle',
                '✓ ПАКЕТ ПОДТВЕРЖДЁН',
              )}
            </strong>
            <p>
              {missionText(
                mission,
                'successText',
                'Прогресс подтверждён сервером.',
              )}
            </p>
          </div>
        ) : isExpired ? (
          <div className="expired-file">
            <p>ВРЕМЯ ВЫШЛО</p>
            <p className="expired-hint">Миссия одноразовая.</p>
            <button
              className="expired-remove"
              onClick={() => void onExpireMission(mission.id)}
            >
              УБРАТЬ
            </button>
          </div>
        ) : isLocked ? (
          <div className="locked-file">
            <span>?</span>
            <div>
              <strong>ПАКЕТ НЕДОСТУПЕН</strong>
              <small>
                Сервер откроет задание после выполнения необходимых
                условий.
              </small>
            </div>
          </div>
        ) : isInProgress ? (
          <div className="accept-row">
            <p className="in-progress-hint">
              Миссия активна. Зона поиска уже на карте.
            </p>
            {mission.missionType === 'team' && (
              <p className="team-member-count">
                {mission.sessionMemberCount ?? 0}/{mission.maxMembers ?? 0}
                {' — '}
                {((mission.sessionMemberCount ?? 0) < (mission.maxMembers ?? 0))
                  ? 'Ждём игроков...'
                  : 'Команда собрана!'}
              </p>
            )}
            <button onClick={() => onScreenChange('map')}>
              ОТКРЫТЬ КАРТУ
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
                  ОТКАЗАТЬСЯ
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
                ? 'Ждём игроков...'
                : 'Команда собрана!'}
            </p>

            {/* Sprint 8.x-4-nav: вход в экран командной сессии (мини-игра).
                TeamSessionScreen сам подтягивает сессию игрока. */}
            <button
              type="button"
              onClick={() => onScreenChange('team-session')}
            >
              ОТКРЫТЬ СЕССИЮ
            </button>

            {mission.sessionStatus === 'active' ? (
              <p className="in-progress-hint">Игра идёт</p>
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
                  ОТКАЗАТЬСЯ
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
                    Не хватает {mission.entryRoot - rootBalance} ROOT
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
                ПРОСМОТР
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
        <p className="eyebrow">КОНТУР / ПОДКЛЮЧЕНИЕ УСТАНОВЛЕНО</p>
        <h2>Доступные архивные пакеты</h2>

        <div className="log-window">
          <p>
            <span>[СИСТЕМА]</span> Контент получен из защищённого игрового
            bootstrap.
          </p>
          <p>
            <span>[СИСТЕМА]</span> Результаты проверок и награды подтверждает
            сервер.
          </p>
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
          <section className="location-status">
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>НЕТ ДОСТУПНЫХ ТЕКСТОВЫХ ПАКЕТОВ</strong>
              <p>
                Опубликованный сюжетный пакет ещё не получен из игрового
                bootstrap, либо все доступные пакеты уже в истории заданий.
              </p>
            </div>
          </section>
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
                    {isEmpty ? (
                      <p className="layer-empty">Пока пусто</p>
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
              {showArchive ? '▼' : '▶'} ИСТОРИЯ ЗАДАНИЙ ({archivedMissions.length})
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
                      {mission.status === 'completed' ? 'РАСШИФРОВАНО' : 'ПРОВАЛЕНО'}
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
