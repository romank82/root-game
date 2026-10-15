import { useEffect, useState } from 'react'
import type {
  EngineMission,
  MissionSubmission,
} from '../../api/engineApi'
import type { ApiStatus, Screen } from '../../types/game'
import { Sidebar } from '../Sidebar'
import { CooldownCountdown } from '../CooldownCountdown'
import { missionText } from '../../utils/missionHelpers'

interface TerminalScreenProps {
  echo: number
  apiStatus: ApiStatus
  missions: EngineMission[]
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
  onScreenChange,
  onSubmitMission,
  onAcceptMission,
  onExpireMission,
}: TerminalScreenProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [acceptingId, setAcceptingId] = useState<string | null>(null)
  const [acceptError, setAcceptError] = useState<string | null>(null)
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
  // Показываем в Контуре все миссии, кроме team (у team отдельный флоу).
  // Sprint 8.13: раньше фильтр был === 'text_answer' и отсекал cipher/code_repair.
  const textMissions = missions.filter(
    (mission) => mission.missionType !== 'team',
  )

  // Активные (в основном списке): всё, кроме завершённых и одноразовых провалов.
  const activeMissions = textMissions.filter(
    (mission) =>
      mission.status !== 'completed' &&
      !(mission.status === 'expired' && mission.availableAgainAt === null),
  )

  // Архив: завершённые + одноразовые провалы.
  const archivedMissions = textMissions.filter(
    (mission) =>
      mission.status === 'completed' ||
      (mission.status === 'expired' && mission.availableAgainAt === null),
  )

  // Группировка активных миссий по слоям.
  const LAYER_ORDER = ['story', 'team', 'solo'] as const
  const LAYER_LABEL: Record<typeof LAYER_ORDER[number], string> = {
    story: 'СЮЖЕТНЫЕ',
    team: 'КОМАНДНЫЕ',
    solo: 'ИНДИВИДУАЛЬНЫЕ',
  }
  const LAYER_COLOR: Record<typeof LAYER_ORDER[number], string> = {
    story: '#ff5c5c',
    team: '#4da6ff',
    solo: '#ffcc00',
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

  async function submitAnswer(mission: EngineMission) {
    const answer = answers[mission.id] ?? ''
    const response = await onSubmitMission(mission.id, { answer })

    if (!response) {
      setSubmissionError('СЕРВЕР НЕДОСТУПЕН. ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ.')
      return
    }

    if (response.accepted) {
      setAnswers((current) => ({ ...current, [mission.id]: '' }))
      setSubmissionError(null)
      return
    }

    setSubmissionError(
      response.message ?? 'ОТВЕТ НЕ ПРИНЯТ. ПРОВЕРЬТЕ ДАННЫЕ И ПОВТОРИТЕ.',
    )
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

  function renderMissionCard(mission: EngineMission) {
    const isCompleted = mission.status === 'completed'
    const isExpired = mission.status === 'expired'
    const isLocked = mission.status === 'locked'
    const isInProgress = mission.status === 'in_progress'

    return (
      <article className="puzzle" key={mission.id}>
        <span className="file-label">
          {missionText(mission, 'label', mission.title)}
        </span>
        <small>СТАТУС: {missionStatusLabel(mission.status)}</small>
        <h3>
          {missionText(mission, 'question', mission.description)}
        </h3>

        {isCompleted ? (
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
            {mission.availableAgainAt ? (
              <p className="expired-hint">
                Доступна снова через:{' '}
                <CooldownCountdown
                  availableAgainAt={mission.availableAgainAt}
                />
              </p>
            ) : (
              <p className="expired-hint">Миссия одноразовая.</p>
            )}
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
            <button onClick={() => onScreenChange('map')}>
              ОТКРЫТЬ КАРТУ
            </button>
          </div>
        ) : (
          <>
            <div className="accept-row">
              <button
                onClick={() => void handleAccept(mission)}
                disabled={acceptingId === mission.id}
              >
                {acceptingId === mission.id
                  ? 'ПОЛУЧЕНИЕ GPS…'
                  : 'ВЗЯТЬ МИССИЮ'}
              </button>
            </div>
            <div className="answer-row">
              <input
                value={answers[mission.id] ?? ''}
                onChange={(event) => {
                  const value = event.target.value
                  setAnswers((current) => ({
                    ...current,
                    [mission.id]: value,
                  }))
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    void submitAnswer(mission)
                  }
                }}
                placeholder={missionText(
                  mission,
                  'inputPlaceholder',
                  'Введите ответ...',
                )}
              />
              <button onClick={() => void submitAnswer(mission)}>
                ПРОВЕРИТЬ
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

        {submissionError && (
          <p className="repair-error">{submissionError}</p>
        )}

        {acceptError && (
          <p className="repair-error">{acceptError}</p>
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
                  style={{ color: LAYER_COLOR[layer] }}
                  onClick={() => setOpenLayer(layer)}
                >
                  <span className="layer-folder-icon">{isOpen ? '📂' : '📁'}</span>
                  <span className="layer-folder-name">{LAYER_LABEL[layer]}</span>
                  <span className="layer-folder-count">({total})</span>
                </button>

                {isOpen && (
                  <div
                    className="layer-folder-body"
                    style={{ borderLeftColor: LAYER_COLOR[layer] }}
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
    </section>
  )
}
