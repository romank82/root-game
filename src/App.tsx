import { useEffect, useState } from 'react'
import './App.css'

type Screen = 'briefing' | 'terminal' | 'archive' | 'inventory'

function App() {
  const [screen, setScreen] = useState<Screen>(() => {
    const saved = localStorage.getItem('chimera-screen')

    return saved === 'terminal' ||
      saved === 'archive' ||
      saved === 'inventory'
      ? saved
      : 'briefing'
  })

  const [accepted, setAccepted] = useState(() => {
    return localStorage.getItem('chimera-accepted') === 'true'
  })

  const [echo, setEcho] = useState(() => {
    return Number(localStorage.getItem('chimera-echo') ?? 0)
  })

  const [answer, setAnswer] = useState('')

  const [solved, setSolved] = useState(() => {
    return localStorage.getItem('chimera-first-puzzle-solved') === 'true'
  })

  const [secondAnswer, setSecondAnswer] = useState('')

  const [secondSolved, setSecondSolved] = useState(() => {
    return localStorage.getItem('chimera-second-puzzle-solved') === 'true'
  })

  useEffect(() => {
    localStorage.setItem('chimera-screen', screen)
  }, [screen])

  useEffect(() => {
    localStorage.setItem('chimera-accepted', String(accepted))
  }, [accepted])

  useEffect(() => {
    localStorage.setItem('chimera-echo', String(echo))
  }, [echo])

  useEffect(() => {
    localStorage.setItem('chimera-first-puzzle-solved', String(solved))
  }, [solved])

  useEffect(() => {
    localStorage.setItem('chimera-second-puzzle-solved', String(secondSolved))
  }, [secondSolved])

  function activateProtocol() {
    setAccepted(true)
    setScreen('terminal')
  }

  function checkAnswer() {
    if (answer.trim().toLowerCase() === 'сигнал') {
      setSolved(true)
      setEcho((currentEcho) => Math.max(currentEcho, 3))
    }
  }

  function checkSecondAnswer() {
    if (secondAnswer.trim().toLowerCase() === 'архив') {
      setSecondSolved(true)
      setEcho((currentEcho) => Math.max(currentEcho, 7))
    }
  }

  function stopSession() {
    const confirmed = window.confirm(
      'Остановить игровую сессию? Прогресс этой локальной версии будет удалён.',
    )

    if (!confirmed) {
      return
    }

    localStorage.removeItem('chimera-screen')
    localStorage.removeItem('chimera-accepted')
    localStorage.removeItem('chimera-echo')
    localStorage.removeItem('chimera-first-puzzle-solved')
    localStorage.removeItem('chimera-second-puzzle-solved')

    setAccepted(false)
    setEcho(0)
    setSolved(false)
    setSecondSolved(false)
    setAnswer('')
    setSecondAnswer('')
    setScreen('briefing')
  }

  return (
    <main className="app-shell">
      <div className="noise" />

      <header className="topbar">
        <button
          className="brand"
          onClick={() => {
            if (accepted) {
              setScreen('terminal')
            }
          }}
        >
          <span className="brand-mark">◈</span>

          <span>
            <strong>CHIMERA</strong>
            <small>PROTOCOL // 01</small>
          </span>
        </button>

        {accepted && (
          <div className="status">
            <span className="status-dot" />
            КОНТУР АКТИВЕН
          </div>
        )}
      </header>

      {screen === 'briefing' && (
        <section className="briefing">
          <div className="packet-icon">▣</div>

          <p className="eyebrow">ВХОДЯЩИЙ АРХИВНЫЙ ПАКЕТ</p>

          <h1>
            Пакет
            <br />
            без отправителя
          </h1>

          <div className="packet-data">
            <div>
              <span>ОТПРАВИТЕЛЬ</span>
              <b>НЕ ОПРЕДЕЛЁН</b>
            </div>

            <div>
              <span>ЦЕЛОСТНОСТЬ</span>
              <b className="warning">61%</b>
            </div>

            <div>
              <span>СТАТУС</span>
              <b>ОЖИДАНИЕ НАБЛЮДАТЕЛЯ</b>
            </div>
          </div>

          <p className="intro">
            «Протокол Химера» — интерактивная художественная игра. Она не
            получает доступ к вашим файлам, настройкам или устройству. Вы
            можете остановить участие в любой момент.
          </p>

          <label className="consent">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(event) => setAccepted(event.target.checked)}
            />

            <span>
              Я понимаю, что это игровая симуляция, и хочу продолжить.
            </span>
          </label>

          <button
            className="primary-button"
            disabled={!accepted}
            onClick={activateProtocol}
          >
            АКТИВИРОВАТЬ ПРОТОКОЛ <span>→</span>
          </button>

          <p className="safe-note">
            ДОСТУП МОЖНО ОТКЛЮЧИТЬ В ЛЮБОЙ МОМЕНТ
          </p>
        </section>
      )}

      {screen === 'terminal' && (
        <section className="terminal-layout">
          <aside className="sidebar">
            <p>НАВИГАЦИЯ</p>

            <button className="active" onClick={() => setScreen('terminal')}>
              ◉ Контур
            </button>

            <button onClick={() => setScreen('archive')}>▤ Архив</button>

            <button onClick={() => setScreen('inventory')}>
              ◈ Инвентарь
            </button>

            <button>◌ Профиль</button>

            <div className="echo-card">
              <span>РЕСУРС</span>
              <strong>{echo} ЭХО</strong>
              <small>нестабильные данные</small>
            </div>
          </aside>

          <div className="terminal-content">
            <p className="eyebrow">
              СЕССИЯ #A-017 / НАБЛЮДАТЕЛЬ ПОДКЛЮЧЁН
            </p>

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
              <span className="file-label">ПЕРВАЯ ПРОВЕРКА</span>

              <h3>Что остаётся, когда исчезает шум?</h3>

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
                    placeholder="Введите ответ..."
                  />

                  <button onClick={checkAnswer}>ПРОВЕРИТЬ</button>
                </div>
              ) : (
                <div className="success">
                  <strong>✓ ФРАГМЕНТ РАСШИФРОВАН</strong>

                  <p>
                    Получено: 3 ЭХО. Найден сюжетный предмет: КЛЮЧ A-01.
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
                  <span className="file-label">ВТОРАЯ ПРОВЕРКА</span>

                  <h3>Где сохраняются следы исчезнувших записей?</h3>

                  {!secondSolved ? (
                    <div className="answer-row">
                      <input
                        value={secondAnswer}
                        onChange={(event) =>
                          setSecondAnswer(event.target.value)
                        }
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            checkSecondAnswer()
                          }
                        }}
                        placeholder="Введите ответ..."
                      />

                      <button onClick={checkSecondAnswer}>ПРОВЕРИТЬ</button>
                    </div>
                  ) : (
                    <div className="success">
                      <strong>✓ ФРАГМЕНТ A-02 РАСШИФРОВАН</strong>

                      <p>
                        Получено: 4 ЭХО. Найден сюжетный предмет: МЕТКА
                        ARCHIVE_NODE_04.
                      </p>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </section>
      )}

      {screen === 'archive' && (
        <section className="archive">
          <p className="eyebrow">АРХИВ / УРОВЕНЬ ДОСТУПА: 01</p>

          <h2>Полученные фрагменты</h2>

          <button
            className="archive-file"
            onClick={() => setScreen('terminal')}
          >
            <span>TXT</span>

            <div>
              <strong>ФРАГМЕНТ A-01</strong>
              <small>Получен во время инициализации контура</small>
            </div>

            <b>ОТКРЫТЬ →</b>
          </button>

          {secondSolved ? (
            <button
              className="archive-file"
              onClick={() => setScreen('terminal')}
            >
              <span>LOG</span>

              <div>
                <strong>ФРАГМЕНТ A-02</strong>
                <small>Восстановленный журнал архивного узла</small>
              </div>

              <b>ОТКРЫТЬ →</b>
            </button>
          ) : (
            <div className="locked-file">
              <span>?</span>

              <div>
                <strong>НЕИЗВЕСТНЫЙ ФРАГМЕНТ</strong>
                <small>Требуется расшифровка пакета A-01</small>
              </div>
            </div>
          )}
        </section>
      )}

      {screen === 'inventory' && (
        <section className="inventory">
          <p className="eyebrow">ИНВЕНТАРЬ / ЛИЧНЫЙ КОНТУР</p>

          <div className="inventory-heading">
            <div>
              <h2>Найденные объекты</h2>
              <p>
                Предметы не имеют реальной ценности и существуют только внутри
                истории «Протокола Химера».
              </p>
            </div>

            <div className="inventory-count">
              <span>ОБЪЕКТОВ</span>
              <strong>{secondSolved ? '02 / 03' : solved ? '01 / 03' : '00 / 03'}</strong>
            </div>
          </div>

          <div className="item-grid">
            {solved ? (
              <article className="item-card">
                <div className="item-symbol">⌘</div>

                <span className="file-label">ОБЪЕКТ #01</span>

                <h3>КЛЮЧ A-01</h3>

                <p>
                  Повреждённый ключ доступа, извлечённый из первого архивного
                  пакета. Его происхождение пока не установлено.
                </p>

                <small>СТАТУС: СТАБИЛЬНЫЙ</small>
              </article>
            ) : (
              <article className="item-card locked-item">
                <div className="item-symbol">?</div>

                <span className="file-label">ОБЪЕКТ #01</span>

                <h3>НЕ ОБНАРУЖЕН</h3>

                <p>Пройдите первую проверку, чтобы извлечь объект.</p>

                <small>СТАТУС: ЗАБЛОКИРОВАН</small>
              </article>
            )}

            {secondSolved ? (
              <article className="item-card">
                <div className="item-symbol">◉</div>

                <span className="file-label">ОБЪЕКТ #02</span>

                <h3>МЕТКА NODE_04</h3>

                <p>
                  Адрес архивного узла, оставленный неизвестным источником.
                  Может открыть доступ к следующему уровню расследования.
                </p>

                <small>СТАТУС: ТРЕБУЕТ АНАЛИЗА</small>
              </article>
            ) : (
              <article className="item-card locked-item">
                <div className="item-symbol">?</div>

                <span className="file-label">ОБЪЕКТ #02</span>

                <h3>НЕ ОБНАРУЖЕН</h3>

                <p>Расшифруйте журнал A-02, чтобы получить метку узла.</p>

                <small>СТАТУС: ЗАБЛОКИРОВАН</small>
              </article>
            )}

            <article className="item-card locked-item">
              <div className="item-symbol">?</div>

              <span className="file-label">ОБЪЕКТ #03</span>

              <h3>НЕИЗВЕСТНЫЙ НОСИТЕЛЬ</h3>

              <p>
                Контур фиксирует присутствие ещё одного объекта. Доступа к
                данным пока нет.
              </p>

              <small>СТАТУС: СИГНАЛ НЕ РАСПОЗНАН</small>
            </article>
          </div>

          <button
            className="back-button"
            onClick={() => setScreen('terminal')}
          >
            ← ВЕРНУТЬСЯ В КОНТУР
          </button>
        </section>
      )}

      {accepted && screen !== 'briefing' && (
        <button className="exit-button" onClick={stopSession}>
          ОСТАНОВИТЬ СЕССИЮ
        </button>
      )}
    </main>
  )
}

export default App