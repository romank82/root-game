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
}: TerminalScreenProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [submissionError, setSubmissionError] = useState<string | null>(null)

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
                ) : (
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
                )}
              </article>
            )
          })
        )}
      </div>
    </section>
  )
}
