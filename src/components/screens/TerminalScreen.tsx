import { useState } from 'react'
import type {
  EngineMission,
  MissionSubmission,
} from '../../api/engineApi'
import type { ApiStatus, Screen } from '../../types/game'
import { Sidebar } from '../Sidebar'
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
  return 'ДОСТУПНО'
}

export function TerminalScreen({
  echo,
  apiStatus,
  missions,
  onScreenChange,
  onSubmitMission,
  onAcceptMission,
}: TerminalScreenProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [acceptingId, setAcceptingId] = useState<string | null>(null)
  const [acceptError, setAcceptError] = useState<string | null>(null)

  // Ordering and player-visible status come from authenticated bootstrap.
  // This screen only renders public text-answer presentation data.
  const textMissions = missions.filter(
    (mission) => mission.missionType === 'text_answer',
  )

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

        {textMissions.length === 0 ? (
          <section className="location-status">
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>НЕТ ДОСТУПНЫХ ТЕКСТОВЫХ ПАКЕТОВ</strong>
              <p>
                Опубликованные задания этого типа ещё не получены из игрового
                bootstrap.
              </p>
            </div>
          </section>
        ) : (
          textMissions.map((mission) => {
            const isCompleted = mission.status === 'completed'
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
          })
        )}
      </div>
    </section>
  )
}
