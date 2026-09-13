import { useEffect, useState } from 'react'
import './App.css'

type Screen = 'briefing' | 'terminal' | 'archive'

function App() {
  const [screen, setScreen] = useState<Screen>(() => {
    const saved = localStorage.getItem('chimera-screen')
    return saved === 'terminal' || saved === 'archive' ? saved : 'briefing'
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

  function activateProtocol() {
    setAccepted(true)
    setScreen('terminal')
  }

  function checkAnswer() {
    if (answer.trim().toLowerCase() === 'сигнал') {
      setSolved(true)
      setEcho(3)
    }
  }

  return (
    <main className="app-shell">
      <div className="noise" />

      <header className="topbar">
        <button className="brand" onClick={() => setScreen('terminal')}>
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
          <h1>Пакет<br />без отправителя</h1>

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
            «Протокол Химера» — интерактивная художественная игра.
            Она не получает доступ к вашим файлам, настройкам или устройству.
            Вы можете остановить участие в любой момент.
          </p>

          <label className="consent">
            <input
              type="checkbox"
              checked={accepted}
              onChange={(event) => setAccepted(event.target.checked)}
            />
            <span>Я понимаю, что это игровая симуляция, и хочу продолжить.</span>
          </label>

          <button
            className="primary-button"
            disabled={!accepted}
            onClick={activateProtocol}
          >
            АКТИВИРОВАТЬ ПРОТОКОЛ <span>→</span>
          </button>

          <p className="safe-note">ДОСТУП МОЖНО ОТКЛЮЧИТЬ В ЛЮБОЙ МОМЕНТ</p>
        </section>
      )}

      {screen === 'terminal' && (
        <section className="terminal-layout">
          <aside className="sidebar">
            <p>НАВИГАЦИЯ</p>
            <button className="active" onClick={() => setScreen('terminal')}>
              ◉ Контур
            </button>
            <button onClick={() => setScreen('archive')}>
              ▤ Архив
            </button>
            <button>◈ Инвентарь</button>
            <button>◌ Профиль</button>

            <div className="echo-card">
              <span>РЕСУРС</span>
              <strong>{echo} ЭХО</strong>
              <small>нестабильные данные</small>
            </div>
          </aside>

          <div className="terminal-content">
            <p className="eyebrow">СЕССИЯ #A-017 / НАБЛЮДАТЕЛЬ ПОДКЛЮЧЁН</p>
            <h2>Контур инициализирован</h2>

            <div className="log-window">
              <p><span>[00:00:01]</span> Подключение к архиву...</p>
              <p><span>[00:00:03]</span> Проверка целостности пакета.</p>
              <p className="alert"><span>[00:00:05]</span> Обнаружено повреждение данных.</p>
              <p><span>[00:00:08]</span> Найдено сообщение, адресованное наблюдателю.</p>
            </div>

            <article className="message-card">
              <span className="file-label">ФРАГМЕНТ A-01.TXT</span>
              <p>
                Если ты читаешь это — значит, пакет нашёл тебя раньше, чем
                Оператор успел закрыть контур.
              </p>
              <p>
                Не доверяй первому сообщению. Не доверяй второму.
                Найди то, что повторяется, когда исчезает шум.
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
                    onKeyDown={(event) => event.key === 'Enter' && checkAnswer()}
                    placeholder="Введите ответ..."
                  />
                  <button onClick={checkAnswer}>ПРОВЕРИТЬ</button>
                </div>
              ) : (
                <div className="success">
                  <strong>✓ ФРАГМЕНТ РАСШИФРОВАН</strong>
                  <p>Получено: 3 ЭХО. Доступ к следующему архиву будет открыт позднее.</p>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {screen === 'archive' && (
        <section className="archive">
          <p className="eyebrow">АРХИВ / УРОВЕНЬ ДОСТУПА: 01</p>
          <h2>Полученные фрагменты</h2>

          <button className="archive-file" onClick={() => setScreen('terminal')}>
            <span>TXT</span>
            <div>
              <strong>ФРАГМЕНТ A-01</strong>
              <small>Получен во время инициализации контура</small>
            </div>
            <b>ОТКРЫТЬ →</b>
          </button>

          <div className="locked-file">
            <span>?</span>
            <div>
              <strong>НЕИЗВЕСТНЫЙ ФРАГМЕНТ</strong>
              <small>Требуется расшифровка пакета A-01</small>
            </div>
          </div>
        </section>
      )}

      {accepted && screen !== 'briefing' && (
        <button
          className="exit-button"
          onClick={() => {
  const confirmed = window.confirm(
    'Остановить игровую сессию? Прогресс этой локальной версии будет удалён.'
  )

  if (confirmed) {
    localStorage.removeItem('chimera-screen')
    localStorage.removeItem('chimera-accepted')
    localStorage.removeItem('chimera-echo')
    localStorage.removeItem('chimera-first-puzzle-solved')

    setAccepted(false)
    setEcho(0)
    setSolved(false)
    setAnswer('')
    setScreen('briefing')
  }
}}
        >
          ОСТАНОВИТЬ СЕССИЮ
        </button>
      )}
    </main>
  )
}

export default App