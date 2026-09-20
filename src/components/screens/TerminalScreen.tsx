import { useState } from 'react'
import type { EngineMission } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { Sidebar } from '../Sidebar'
import { missionText } from '../../utils/missionHelpers'
import type { ApiStatus } from '../../types/game'

interface TerminalScreenProps {
  echo: number
  apiStatus: ApiStatus
  missions: EngineMission[]
  onScreenChange: (screen: Screen) => void
  onSubmitMission: (missionId: string, payload: { answer?: string }) => Promise<{ accepted?: boolean } | null>
}

export function TerminalScreen({
  echo,
  apiStatus,
  missions,
  onScreenChange,
  onSubmitMission,
}: TerminalScreenProps) {
  const [answer, setAnswer] = useState('')
  const [secondAnswer, setSecondAnswer] = useState('')

  const solved = missions.some(
    (mission) =>
      mission.id === 'mission-puzzle-a-01' && mission.status === 'completed',
  )

  const secondSolved = missions.some(
    (mission) =>
      mission.id === 'mission-puzzle-a-02' && mission.status === 'completed',
  )

  const missionA01 = missions.find(
    (mission) => mission.id === 'mission-puzzle-a-01',
  )
  const missionA02 = missions.find(
    (mission) => mission.id === 'mission-puzzle-a-02',
  )

  async function checkAnswer() {
    const response = await onSubmitMission('mission-puzzle-a-01', { answer })
    if (response?.accepted) {
      setAnswer('')
    }
  }

  async function checkSecondAnswer() {
    const response = await onSubmitMission('mission-puzzle-a-02', {
      answer: secondAnswer,
    })
    if (response?.accepted) {
      setSecondAnswer('')
    }
  }

  return (
    <section className="terminal-layout">
      <Sidebar
        echo={echo}
        apiStatus={apiStatus}
        onScreenChange={onScreenChange}
      />

      <div className="terminal-content">
        <p className="eyebrow">СЕССИЯ #A-017 / НАБЛЮДАТЕЛЬ ПОДКЛЮЧЁН</p>

        <h2>Контур инициализирован</h2>

        <div className="log-window">
          <p>
            <span>[00:00:01]</span> Подключение к архиву...
          </p>
          <p>
            <span>[00:00:03]</span> Проверка целостности пакета.
          </p>
          <p className="alert">
            <span>[00:00:05]</span> Обнаружено повреждение данных.
          </p>
          <p>
            <span>[00:00:08]</span> Найдено сообщение, адресованное
            наблюдателю.
          </p>
        </div>

        <article className="message-card">
          <span className="file-label">ФРАГМЕНТ A-01.TXT</span>

          <p>
            Если ты читаешь это — значит, пакет нашёл тебя раньше, чем
            Оператор успел закрыть контур.
          </p>

          <p>
            Не доверяй первому сообщению. Не доверяй второму. Найди то,
            что повторяется, когда исчезает шум.
          </p>

          <p className="signature">— неизвестный источник</p>
        </article>

        <div className="puzzle">
          <span className="file-label">
            {missionText(missionA01, 'label', 'ПЕРВАЯ ПРОВЕРКА')}
          </span>

          <h3>
            {missionText(
              missionA01,
              'question',
              'Что остаётся, когда исчезает шум?',
            )}
          </h3>

          {!solved ? (
            <div className="answer-row">
              <input
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    checkAnswer()
                  }
                }}
                placeholder={missionText(
                  missionA01,
                  'inputPlaceholder',
                  'Введите ответ...',
                )}
              />

              <button onClick={checkAnswer}>ПРОВЕРИТЬ</button>
            </div>
          ) : (
            <div className="success">
              <strong>
                {missionText(
                  missionA01,
                  'successTitle',
                  '✓ ФРАГМЕНТ РАСШИФРОВАН',
                )}
              </strong>
              <p>
                {missionText(
                  missionA01,
                  'successText',
                  'Получено: 3 ROOT. Найден сюжетный предмет: КЛЮЧ A-01.',
                )}
              </p>
            </div>
          )}
        </div>

        {solved && (
          <>
            <article className="message-card">
              <span className="file-label">ФРАГМЕНТ A-02.LOG</span>

              <p>
                Восстановлен скрытый сектор пакета. Файл не должен был
                сохраниться после первичной очистки.
              </p>

              <div className="log-window compact-log">
                <p>
                  <span>[ОБЪЕКТ]</span> ARCHIVE_NODE_04
                </p>
                <p>
                  <span>[СТАТУС]</span> недоступен
                </p>
                <p>
                  <span>[ПРИЧИНА]</span> наблюдатель ещё не распознал
                  источник
                </p>
                <p className="alert">
                  <span>[ПРЕДУПРЕЖДЕНИЕ]</span> Оператор удалил часть
                  записей.
                </p>
              </div>

              <p className="signature">
                «Не ищи дверь. Ищи место, где сохраняются следы тех, кого
                уже нет».
              </p>
            </article>

            <div className="puzzle">
              <span className="file-label">
                {missionText(missionA02, 'label', 'ВТОРАЯ ПРОВЕРКА')}
              </span>

              <h3>
                {missionText(
                  missionA02,
                  'question',
                  'Где сохраняются следы исчезнувших записей?',
                )}
              </h3>

              {!secondSolved ? (
                <div className="answer-row">
                  <input
                    value={secondAnswer}
                    onChange={(event) => setSecondAnswer(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        checkSecondAnswer()
                      }
                    }}
                    placeholder={missionText(
                      missionA02,
                      'inputPlaceholder',
                      'Введите ответ...',
                    )}
                  />

                  <button onClick={checkSecondAnswer}>ПРОВЕРИТЬ</button>
                </div>
              ) : (
                <div className="success">
                  <strong>
                    {missionText(
                      missionA02,
                      'successTitle',
                      '✓ ФРАГМЕНТ A-02 РАСШИФРОВАН',
                    )}
                  </strong>
                  <p>
                    {missionText(
                      missionA02,
                      'successText',
                      'Получено: 4 ROOT. Найден доступ к архивному узлу.',
                    )}
                  </p>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  )
}
