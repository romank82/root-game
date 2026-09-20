import { useEffect, useState } from 'react'
import './App.css'
import { activeSegment } from './data/activeSegment'
import {
  authenticateTelegram,
  getEngineBootstrap,
  resetEngineDemoProgress,
  submitEngineMission,
  type EngineBootstrap,
  type EngineInventoryItem,
  type EngineMission,
  type EngineStoryNode,
} from './api/engineApi'

type Screen = 'briefing' | 'terminal' | 'archive' | 'inventory' | 'scanner'

function missionText(
  mission: EngineMission | undefined,
  field: string,
  fallback: string,
): string {
  const value = mission?.content[field]

  return typeof value === 'string' ? value : fallback
}

function missionBlocks(
  mission: EngineMission | undefined,
  fallback: string[],
): string[] {
  const blocks = mission?.content.blocks

  return Array.isArray(blocks) &&
    blocks.every((block) => typeof block === 'string')
    ? blocks
    : fallback
}

function App() {
  const [screen, setScreen] = useState<Screen>(() => {
    const saved = localStorage.getItem('chimera-screen')

    return saved === 'terminal' ||
      saved === 'archive' ||
      saved === 'inventory' ||
      saved === 'scanner'
      ? saved
      : 'briefing'
  })

  const [accepted, setAccepted] = useState(() => {
    return localStorage.getItem('chimera-accepted') === 'true'
  })

  const [echo, setEcho] = useState(() => {
    return Number(localStorage.getItem('chimera-echo') ?? 0)
  })
  const [inventory, setInventory] = useState<EngineInventoryItem[]>([])
  const [storyNodes, setStoryNodes] = useState<EngineStoryNode[]>([])
  const [missions, setMissions] = useState<EngineMission[]>([])
  const [apiStatus, setApiStatus] = useState<
    'checking' | 'online' | 'offline'
  >('checking')
  const [authStatus, setAuthStatus] = useState<
    'checking' | 'authenticated' | 'unavailable' | 'error'
  >('checking')
  const [authError, setAuthError] = useState('')

  const [answer, setAnswer] = useState('')

  const [solved, setSolved] = useState(false)

  const [secondAnswer, setSecondAnswer] = useState('')

  const [secondSolved, setSecondSolved] = useState(false)

  const [distanceToSegment, setDistanceToSegment] = useState<number | null>(
    null,
  )
  const [isCheckingLocation, setIsCheckingLocation] = useState(false)
  const [locationError, setLocationError] = useState('')
  const [arSessionStarted, setArSessionStarted] = useState(false)
  const [isSegmentFaceLocked, setIsSegmentFaceLocked] = useState(false)
  const [virtualQrRevealed, setVirtualQrRevealed] = useState(false)
  const [isCodeRepairOpen, setIsCodeRepairOpen] = useState(false)
  const [repairSequence, setRepairSequence] = useState<string[]>([])
    const [isSegmentMissionComplete, setIsSegmentMissionComplete] =
    useState(false)
  const [repairError, setRepairError] = useState('')
  function applyEngineBootstrap(bootstrap: EngineBootstrap) {
    setEcho(bootstrap.wallet.availableBalance)
    setInventory(bootstrap.inventory)
    setStoryNodes(bootstrap.storyNodes)
    setMissions(bootstrap.missions)

    setSolved(
      bootstrap.missions.some(
        (mission) =>
          mission.id === 'mission-puzzle-a-01' &&
          mission.status === 'completed',
      ),
    )
    setSecondSolved(
      bootstrap.missions.some(
        (mission) =>
          mission.id === 'mission-puzzle-a-02' &&
          mission.status === 'completed',
      ),
    )
    setIsSegmentMissionComplete(
      bootstrap.missions.some(
        (mission) =>
          mission.id === 'mission-archive-017' &&
          mission.status === 'completed',
      ),
    )

    setApiStatus('online')
  }

  useEffect(() => {
    let isMounted = true
    const webApp = window.Telegram?.WebApp
    const initData = webApp?.initData?.trim()

    webApp?.ready()
    webApp?.expand()

    if (!initData) {
      setAuthStatus('unavailable')
      setAuthError(
        'Откройте CHIMERA Protocol через Telegram-бота, чтобы начать игровую сессию.',
      )
      return () => {
        isMounted = false
      }
    }

    authenticateTelegram(initData)
      .then(() => getEngineBootstrap())
      .then((bootstrap) => {
        if (!isMounted) {
          return
        }

        applyEngineBootstrap(bootstrap)
        setAuthStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (!isMounted) {
          return
        }

        setApiStatus('offline')
        setAuthStatus('error')
        setAuthError(
          error instanceof Error
            ? error.message
            : 'Не удалось подтвердить Telegram-сессию.',
        )
      })

    return () => {
      isMounted = false
    }
  }, [])

  async function submitMission(
    missionId: string,
    payload: { answer?: string; sequence?: string[] },
  ) {
    try {
      const response = await submitEngineMission(missionId, payload)
      applyEngineBootstrap(response.bootstrap)
      return response
    } catch {
      setApiStatus('offline')
      return null
    }
  }

  useEffect(() => {
    localStorage.setItem('chimera-screen', screen)
  }, [screen])

  useEffect(() => {
    localStorage.setItem('chimera-accepted', String(accepted))
  }, [accepted])

  useEffect(() => {
    localStorage.setItem('chimera-echo', String(echo))
  }, [echo])


  function activateProtocol() {
    setAccepted(true)
    setScreen('terminal')
  }

  async function checkAnswer() {
    const response = await submitMission('mission-puzzle-a-01', {
      answer,
    })

    if (response?.accepted) {
      setAnswer('')
    }
  }

  async function checkSecondAnswer() {
    const response = await submitMission('mission-puzzle-a-02', {
      answer: secondAnswer,
    })

    if (response?.accepted) {
      setSecondAnswer('')
    }
  }

  function calculateDistanceInMeters(
    firstLatitude: number,
    firstLongitude: number,
    secondLatitude: number,
    secondLongitude: number,
  ) {
    const earthRadiusMeters = 6371000
    const latitudeDifference =
      ((secondLatitude - firstLatitude) * Math.PI) / 180
    const longitudeDifference =
      ((secondLongitude - firstLongitude) * Math.PI) / 180

    const firstLatitudeRadians = (firstLatitude * Math.PI) / 180
    const secondLatitudeRadians = (secondLatitude * Math.PI) / 180

    const value =
      Math.sin(latitudeDifference / 2) *
        Math.sin(latitudeDifference / 2) +
      Math.cos(firstLatitudeRadians) *
        Math.cos(secondLatitudeRadians) *
        Math.sin(longitudeDifference / 2) *
        Math.sin(longitudeDifference / 2)

    const arc = 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value))

    return Math.round(earthRadiusMeters * arc)
  }

  function openRouteInNavigator() {
    const { latitude, longitude } = activeSegment.safeScanPoint
    const isAppleDevice = /iPad|iPhone|iPod/.test(navigator.userAgent)

    const navigationUrl = isAppleDevice
      ? `maps://?daddr=${latitude},${longitude}&dirflg=w`
      : `geo:${latitude},${longitude}?q=${latitude},${longitude}`

    window.location.href = navigationUrl
  }

  function checkPlayerLocation() {
    if (!navigator.geolocation) {
      setLocationError('Геолокация не поддерживается этим устройством.')
      return
    }

    setLocationError('')
    setIsCheckingLocation(true)

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const distance = calculateDistanceInMeters(
          position.coords.latitude,
          position.coords.longitude,
          activeSegment.safeScanPoint.latitude,
          activeSegment.safeScanPoint.longitude,
        )

        setDistanceToSegment(distance)
        setIsCheckingLocation(false)
      },
      (error) => {
        setIsCheckingLocation(false)

        if (error.code === error.PERMISSION_DENIED) {
          setLocationError(
            'Доступ к геолокации запрещён. Разрешите его в настройках браузера или Telegram.',
          )
          return
        }

        if (error.code === error.POSITION_UNAVAILABLE) {
          setLocationError(
            'Не удалось определить позицию. Проверьте GPS, интернет и настройки геолокации.',
          )
          return
        }

        setLocationError(
          'Не удалось получить геопозицию. Попробуйте ещё раз через несколько секунд.',
        )
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0,
      },
    )
  }

    function startArSearch() {
    setArSessionStarted(true)
    setIsSegmentFaceLocked(false)
    setVirtualQrRevealed(false)
    setIsCodeRepairOpen(false)
    setRepairSequence([])
    setRepairError('')
  }

  function lockSegmentFace() {
    setIsSegmentFaceLocked(true)
  }

  function revealVirtualQr() {
    setVirtualQrRevealed(true)
  }

  function openCodeRepair() {
    setIsCodeRepairOpen(true)
    setRepairSequence([])
    setRepairError('')
  }

  function addRepairBlock(block: string) {
    if (isSegmentMissionComplete) {
      return
    }

    setRepairError('')
    setRepairSequence((currentSequence) => {
      if (currentSequence.length >= 3) {
        return currentSequence
      }

      return [...currentSequence, block]
    })
  }

  function clearRepairSequence() {
    setRepairSequence([])
    setRepairError('')
  }

  async function submitCodeRepair() {
    const response = await submitMission('mission-archive-017', {
      sequence: repairSequence,
    })

    if (!response) {
      setRepairError('СЕРВЕР НЕДОСТУПЕН. ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ.')
      return
    }

    if (!response.accepted) {
      setRepairError(
        response.message ??
          'СТРУКТУРА ПАКЕТА НАРУШЕНА. ОЧИСТИТЕ СТРОКУ И ВОССТАНОВИТЕ ЕЁ ЗАНОВО.',
      )
      return
    }

    setRepairError('')
  }

  const canStartArSearch =
    distanceToSegment !== null &&
    distanceToSegment <= activeSegment.safeScanRadiusMeters

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

    resetEngineDemoProgress()
      .then((bootstrap) => {
        applyEngineBootstrap(bootstrap)
      })
      .catch(() => {
        setApiStatus('offline')
      })

    setAccepted(false)
    setEcho(0)
    setSolved(false)
    setSecondSolved(false)
    setAnswer('')
    setSecondAnswer('')
    setDistanceToSegment(null)
    setLocationError('')
    setArSessionStarted(false)
    setIsSegmentFaceLocked(false)
    setVirtualQrRevealed(false)
    setIsCodeRepairOpen(false)
    setRepairSequence([])
    setIsSegmentMissionComplete(false)
    setRepairError('')
    setScreen('briefing')
  }
    const keyA01 = inventory.find((item) => item.id === 'item-key-a01')

  const archiveA17 = inventory.find(
    (item) => item.id === 'item-archive-a17',
  )
  const storyNodeA17 = storyNodes.find(
    (storyNode) => storyNode.id === 'story-node-a17',
  )


  const activeMission =
    missions.find(
      (mission) =>
        mission.id === 'mission-archive-017' &&
        mission.status !== 'completed',
    ) ??
    missions.find((mission) => mission.id === 'mission-archive-017') ??
    null


  const missionA01 = missions.find(
    (mission) => mission.id === 'mission-puzzle-a-01',
  )
  const missionA02 = missions.find(
    (mission) => mission.id === 'mission-puzzle-a-02',
  )
  const missionA17 = missions.find(
    (mission) => mission.id === 'mission-archive-017',
  )

  const repairBlocks = missionBlocks(missionA17, [
    'packet.',
    'signature',
    'return ',
  ])

  if (authStatus !== 'authenticated') {
    return (
      <main className="app-shell">
        <div className="noise" />
        <section className="briefing">
          <div className="packet-icon">◈</div>
          <p className="eyebrow">CHIMERA PROTOCOL / ACCESS GATE</p>
          <h1>
            {authStatus === 'checking'
              ? 'Проверяем\nсессию'
              : 'Требуется\nTelegram'}
          </h1>
          <p className="intro">
            {authStatus === 'checking'
              ? 'Проверяем подтверждённую игровую сессию…'
              : authError}
          </p>
          {authStatus !== 'checking' && (
            <p className="safe-note">
              ОТКРОЙТЕ ИГРУ КНОПКОЙ В ЧАТЕ С @HIMERAPROTOCOLBOT
            </p>
          )}
        </section>
      </main>
    )
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

            <button onClick={() => setScreen('scanner')}>◌ Сканер</button>

                        <div className="echo-card">
              <span>РЕСУРС</span>
              <strong>{echo} ROOT</strong>
              <small>
                {apiStatus === 'checking' && 'синхронизация...'}
                {apiStatus === 'online' && 'синхронизация: online'}
                {apiStatus === 'offline' && 'локальный тестовый режим'}
              </small>
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
                        onChange={(event) =>
                          setSecondAnswer(event.target.value)
                        }
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

          {storyNodeA17 && (
            <article className="message-card archive-story-node">
              <span className="file-label">СЕРВЕРНЫЙ СЮЖЕТНЫЙ ФРАГМЕНТ</span>
              <h3>{storyNodeA17.title}</h3>
              <p>{storyNodeA17.body}</p>
              <small>СТАТУС: РАЗБЛОКИРОВАН BACKEND-СЕРВЕРОМ</small>
            </article>
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
              <strong>{String(inventory.length).padStart(2, '0')} / 03</strong>
            </div>
          </div>

          <div className="item-grid">
            {keyA01 ? (
              <article className="item-card">
                <div className="item-symbol">{keyA01.symbol}</div>
                <span className="file-label">ОБЪЕКТ #01</span>
                <h3>{keyA01.title}</h3>
                <p>{keyA01.description}</p>
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

            {archiveA17 ? (
              <article className="item-card">
                <div className="item-symbol">{archiveA17.symbol}</div>
                <span className="file-label">ОБЪЕКТ #02</span>
                <h3>{archiveA17.title}</h3>
                <p>{archiveA17.description}</p>
                <small>СТАТУС: ТРЕБУЕТ АНАЛИЗА</small>
              </article>
            ) : (
              <article className="item-card locked-item">
                <div className="item-symbol">?</div>
                <span className="file-label">ОБЪЕКТ #02</span>
                <h3>НЕ ОБНАРУЖЕН</h3>
                <p>
                  Восстановите Сегмент ARCHIVE-017, чтобы извлечь объект.
                </p>
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

      {screen === 'scanner' && (
        <section className="segment-screen">
          <p className="eyebrow">
            {activeMission
              ? `АКТИВНАЯ МИССИЯ / ${activeMission.id.toUpperCase()}`
              : 'АРХИВНЫЙ СЕГМЕНТ / ВОССТАНОВЛЕН'}
          </p>

          <div className="segment-heading">
            <div>
              <span className="segment-type">{activeSegment.type}</span>
              <h2>{activeMission?.title ?? activeSegment.title}</h2>
              <p>{activeMission?.description ?? activeSegment.description}</p>
            </div>

            <div className="segment-code">
              <span>ИДЕНТИФИКАТОР</span>
              <strong>{activeSegment.code}</strong>
            </div>
          </div>

          <section className="segment-card">
            <div className="segment-visual">
              <div className="segment-cube">
                <span className="cube-face cube-front">▦</span>
                <span className="cube-face cube-side">01</span>
                <span className="cube-face cube-top">⌗</span>
              </div>

              <span className="signal-ring signal-ring-one" />
              <span className="signal-ring signal-ring-two" />
            </div>

            <div className="segment-details">
              <span className="file-label">ПАРАМЕТРЫ МИССИИ</span>

              <dl className="segment-stats">
                <div>
                  <dt>РАДИУС ПОИСКА</dt>
                  <dd>{activeSegment.searchRadiusMeters} м</dd>
                </div>

                <div>
                  <dt>SAFE SCAN POINT</dt>
                  <dd>{activeSegment.safeScanRadiusMeters} м</dd>
                </div>

                <div>
                  <dt>НАГРАДА ЗА УСПЕХ</dt>
                  <dd>+{activeSegment.reward.root} ROOT</dd>
                </div>

                <div>
                  <dt>ТИП СЦЕНЫ</dt>
                  <dd>{activeSegment.arScene.scenePreset}</dd>
                </div>
              </dl>

              {activeSegment.reward.itemName && (
                <p className="segment-item-reward">
                  ПРЕДМЕТ: {activeSegment.reward.itemName}
                </p>
              )}
            </div>
          </section>

          <section className="location-panel">
            <div>
              <span className="file-label">
                НАВИГАЦИЯ И ПРОВЕРКА ПОЗИЦИИ
              </span>

              <h3>Найдите безопасную точку сканирования</h3>

              <p>
                Откройте маршрут в навигаторе телефона. После прибытия
                вернитесь в игру и подтвердите своё местоположение.
              </p>
            </div>

            <div className="location-actions">
              <button className="route-button" onClick={openRouteInNavigator}>
                ОТКРЫТЬ МАРШРУТ →
              </button>

              <button
                className="location-button"
                onClick={checkPlayerLocation}
                disabled={isCheckingLocation}
              >
                {isCheckingLocation
                  ? 'ОПРЕДЕЛЯЕМ ПОЗИЦИЮ...'
                  : 'ПРОВЕРИТЬ ПОЗИЦИЮ'}
              </button>
            </div>
          </section>

          <section
            className={`location-status ${
              canStartArSearch ? 'location-status-success' : ''
            }`}
          >
            {locationError ? (
              <>
                <span className="location-status-icon">!</span>
                <div>
                  <strong>ОШИБКА ГЕОЛОКАЦИИ</strong>
                  <p>{locationError}</p>
                </div>
              </>
            ) : distanceToSegment === null ? (
              <>
                <span className="location-status-icon">⌖</span>
                <div>
                  <strong>ПОЗИЦИЯ НЕ ПРОВЕРЕНА</strong>
                  <p>
                    Для запуска AR-поиска подтвердите, что вы находитесь у
                    безопасной точки сканирования.
                  </p>
                </div>
              </>
            ) : canStartArSearch ? (
              <>
                <span className="location-status-icon">✓</span>
                <div>
                  <strong>SAFE SCAN POINT ДОСТУПЕН</strong>
                  <p>
                    Расстояние до безопасной точки: {distanceToSegment} м.
                    Можно запускать AR-поиск.
                  </p>
                </div>
              </>
            ) : (
              <>
                <span className="location-status-icon">⌖</span>
                <div>
                  <strong>ТОЧКА СКАНИРОВАНИЯ СЛИШКОМ ДАЛЕКО</strong>
                  <p>
                    Расстояние: {distanceToSegment} м. Для запуска AR-поиска
                    нужно подойти ближе чем на{' '}
                    {activeSegment.safeScanRadiusMeters} м.
                  </p>
                </div>
              </>
            )}
          </section>

                    {!arSessionStarted ? (
            <button
              className="ar-start-button"
              onClick={startArSearch}
              disabled={!canStartArSearch}
            >
              {canStartArSearch
                ? 'ЗАПУСТИТЬ AR-ПОИСК'
                : 'AR-ПОИСК ЗАБЛОКИРОВАН'}
            </button>
          ) : isSegmentMissionComplete ? (
            <section className="mission-success-card">
              <span className="file-label">ПАКЕТ ВОССТАНОВЛЕН</span>

              <div className="mission-success-symbol">✓</div>

              <h3>СЕГМЕНТ СТАБИЛИЗИРОВАН</h3>

              <p>
                Кодовая структура восстановлена. Архив извлечён из
                нестабильного контура.
              </p>

              <div className="mission-reward-grid">
                <div>
                  <span>ПОЛУЧЕНО</span>
                  <strong>+{activeSegment.reward.root} ROOT</strong>
                </div>

                <div>
                  <span>ИЗВЛЕЧЁН ОБЪЕКТ</span>
                  <strong>{activeSegment.reward.itemName}</strong>
                </div>
              </div>

              <small>
                В production награда, предмет и прогресс будут подтверждаться
                только backend-сервером.
              </small>
            </section>
          ) : isCodeRepairOpen ? (
            <section className="code-repair-panel">
              <span className="file-label">
                {missionText(missionA17, 'label', 'МИНИ-ИГРА / CODE REPAIR')}
              </span>

              <h3>Восстановите повреждённую строку</h3>

              <p>
                {missionText(
                  missionA17,
                  'instruction',
                  'Архивный пакет потерял порядок трёх блоков. Соберите корректную команду извлечения подписи.',
                )}
              </p>

              <div className="code-window">
                <span className="code-line-number">
                  {missionText(missionA17, 'lineNumber', '017')}
                </span>

                <code>
                  {repairSequence.length > 0 ? (
                    repairSequence.map((block, index) => (
                      <span key={`${block}-${index}`}>{block}</span>
                    ))
                  ) : (
                    <span className="code-placeholder">
                      {missionText(
                        missionA17,
                        'placeholder',
                        '// выберите блоки ниже',
                      )}
                    </span>
                  )}
                </code>
              </div>

              <div className="repair-blocks">
                {repairBlocks.map((block) => (
                  <button key={block} onClick={() => addRepairBlock(block)}>
                    {block}
                  </button>
                ))}
              </div>

              {repairError && <p className="repair-error">{repairError}</p>}

              <div className="repair-actions">
                <button
                  className="repair-clear-button"
                  onClick={clearRepairSequence}
                >
                  ОЧИСТИТЬ
                </button>

                <button
                  className="repair-submit-button"
                  onClick={submitCodeRepair}
                  disabled={repairSequence.length !== 3}
                >
                  ПРОВЕРИТЬ КОД →
                </button>
              </div>
            </section>
          ) : (
            <section className="ar-placeholder">
              <span className="file-label">AR-СЕССИЯ ИНИЦИАЛИЗИРОВАНА</span>

              <div
                className={`ar-placeholder-frame ${
                  isSegmentFaceLocked ? 'face-locked' : ''
                }`}
              >
                <div className="ar-cube">
                  {virtualQrRevealed ? (
                    <span className="virtual-qr">▦</span>
                  ) : (
                    '▦'
                  )}
                </div>

                <div className="ar-reticle">+</div>
                <span className="ar-scan-line" />

                {isSegmentFaceLocked && (
                  <span className="face-lock-status">ГРАНЬ ЗАФИКСИРОВАНА</span>
                )}
              </div>

              {!isSegmentFaceLocked ? (
                <>
                  <h3>Наведите прицел на грань Сегмента</h3>

                  <p>
                    Зафиксируйте одну из граней виртуального куба, чтобы начать
                    извлечение архивного маркера.
                  </p>

                  <button
                    className="ar-action-button"
                    onClick={lockSegmentFace}
                  >
                    ЗАФИКСИРОВАТЬ ГРАНЬ
                  </button>
                </>
              ) : !virtualQrRevealed ? (
                <>
                  <h3>Грань синхронизирована</h3>

                  <p>
                    На поверхности объекта обнаружена повреждённая QR-структура.
                    Запустите её визуальное извлечение.
                  </p>

                  <button
                    className="ar-action-button"
                    onClick={revealVirtualQr}
                  >
                    ПРОЯВИТЬ QR-МАРКЕР
                  </button>
                </>
              ) : (
                <>
                  <h3>Виртуальный QR-маркер извлечён</h3>

                  <p>
                    Серверная сессия сканирования в будущем будет создана на
                    этом шаге. Сейчас откроется тестовая головоломка.
                  </p>

                  <button className="ar-action-button" onClick={openCodeRepair}>
                    ИЗВЛЕЧЬ ДАННЫЕ →
                  </button>
                </>
              )}
            </section>
                    )}

          <button
            className="back-button"
            onClick={() => setScreen('terminal')}
          >
            ← ВЕРНУТЬСЯ В КОНТУР
          </button>
        </section>
      )}

      {accepted && screen !== 'briefing' && (
        <nav className="mobile-navigation" aria-label="Игровая навигация">
          <button
            className={screen === 'terminal' ? 'active' : ''}
            onClick={() => setScreen('terminal')}
          >
            <span>◉</span>
            Контур
          </button>

          <button
            className={screen === 'archive' ? 'active' : ''}
            onClick={() => setScreen('archive')}
          >
            <span>▤</span>
            Архив
          </button>

          <button
            className={screen === 'scanner' ? 'active' : ''}
            onClick={() => setScreen('scanner')}
          >
            <span>⌗</span>
            Сканер
          </button>

          <button
            className={screen === 'inventory' ? 'active' : ''}
            onClick={() => setScreen('inventory')}
          >
            <span>◈</span>
            Вещи
          </button>
        </nav>
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
