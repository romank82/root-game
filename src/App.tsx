import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import './App.css'
import { useAuth } from './hooks/useAuth'
import { useGameState } from './hooks/useGameState'
import { useGeoPosition } from './hooks/useGeoPosition'
import { getEngineBootstrap, type EngineBootstrap } from './api/engineApi'
import { Topbar } from './components/Topbar'
import { MobileNavigation } from './components/MobileNavigation'
import { MoreSheet } from './components/MoreSheet'
import { BriefingScreen } from './components/screens/BriefingScreen'
import { TerminalScreen } from './components/screens/TerminalScreen'
import { InventoryScreen } from './components/screens/InventoryScreen'
import { ScannerScreen } from './components/screens/ScannerScreen'
import { ShopScreen } from './components/screens/ShopScreen'
import { ProfileScreen } from './components/screens/ProfileScreen'
import { TransferScreen } from './components/screens/TransferScreen'
import { MapScreen } from './components/screens/MapScreen'
// AR camera screen (8.11+).
import { CameraTestScreen } from './components/screens/CameraTestScreen'
import { CipherScreen } from './components/screens/CipherScreen'
import { MemoryScreen } from './components/screens/MemoryScreen'
import { RiskScreen } from './components/screens/RiskScreen'
import { TeamSessionScreen } from './components/screens/TeamSessionScreen'

function App() {
  const { t } = useTranslation(['common'])
  const {
    screen,
    setScreen,
    accepted,
    setAccepted,
    echo,
    inventory,
    missions,
    rootBalanceNano,
    apiStatus,
    
    applyEngineBootstrap,
    submitMission,
    acceptMission,
    expireMission,
    resetProgress,
  } = useGameState()

  // Единая точка применения bootstrap: useGameState обновляет всё состояние,
  // включая nano-баланс. Раньше nano жил отдельным state в App и обновлялся
  // только при входе — после победы в миссии шапка показывала старый баланс.
  const applyBootstrap = useCallback(
    (bootstrap: EngineBootstrap) => {
      applyEngineBootstrap(bootstrap)
    },
    [applyEngineBootstrap],
  )

  const { authStatus, authError } = useAuth(applyBootstrap)

  const { position: geoPosition, error: geoError } = useGeoPosition()

  const [moreOpen, setMoreOpen] = useState(false)

  useEffect(() => {
    localStorage.setItem('chimera-screen', screen)
  }, [screen])

  useEffect(() => {
    localStorage.setItem('chimera-accepted', String(accepted))
  }, [accepted])

  useEffect(() => {
    localStorage.setItem('chimera-echo', String(echo))
  }, [echo])

  // Синхронизация с сервером при возврате в приложение.
  // Сервер закрывает просроченные миссии лениво — только при следующем
  // запросе от клиента (_synchronize_player_missions в bootstrap). Без этого
  // эффекта игрок, у которого истёк дедлайн, видел застывший таймер и старый
  // статус миссии до полного перезапуска Mini App: фронт ничего не запрашивал.
  useEffect(() => {
    if (authStatus !== 'authenticated') return

    let isMounted = true

    const resync = () => {
      getEngineBootstrap()
        .then((fresh) => {
          if (!isMounted) return
          applyBootstrap(fresh)
        })
        .catch(() => {
          // Сеть недоступна — оставляем текущее состояние, повторим при
          // следующем возврате в приложение.
        })
    }

    // Мини-приложение снова на экране (вернулись из другого приложения или
    // разблокировали телефон). В Telegram WebView visibilitychange работает,
    // но на части Android-прошивок срабатывает только focus — слушаем оба.
    const onVisibility = () => {
      if (document.visibilityState === 'visible') resync()
    }

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('focus', onVisibility)

    return () => {
      isMounted = false
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('focus', onVisibility)
    }
  }, [authStatus, applyBootstrap])

  // Синхронизация в момент истечения любого клиентского дедлайна.
  //
  // Бэкенд закрывает просроченное ЛЕНИВО: _synchronize_player_missions
  // переводит миссию в expired только внутри чужого запроса. Сам он ничего не
  // делает по расписанию, поэтому клиент обязан разбудить его ровно в момент
  // нуля — иначе счётчик замирает на 00:00, а миссия остаётся in_progress
  // (кнопка «взять снова» не появляется) до перезапуска приложения.
  //
  // Клиентских дедлайнов ТРИ, и они разные:
  //   deadlineAt         — общий лимит выполнения миссии (истинный дедлайн);
  //   attemptDeadlineAt  — лимит текущей попытки в мини-игре;
  //   cancel/cooldown    — окно отказа и availableAgainAt (считаются кнопками).
  // Первая версия следила только за deadlineAt, поэтому таймер, который игрок
  // реально видит (попытка/cooldown), продолжал стоять на нуле.
  const resyncTimerRef = useRef<number | null>(null)
  // Подпись «залипшего» набора дедлайнов. Сбрасывает счётчик повторов, когда
  // состояние реально изменилось (сервер обновил статус) — иначе интервал
  // оставался бы максимальным.
  const staleSignatureRef = useRef('')
  const staleRetryRef = useRef(0)

  useEffect(() => {
    if (authStatus !== 'authenticated') return

    if (resyncTimerRef.current !== null) {
      window.clearTimeout(resyncTimerRef.current)
      resyncTimerRef.current = null
    }

    const nowMs = Date.now()
    const wakeups: number[] = []
    // «Просрочено, но статус ещё не обновлён»: сервер узнает об истечении
    // только от нас, поэтому такие миссии требуют немедленной синхронизации.
    let staleCount = 0

    for (const mission of missions) {
      // Только СЕРВЕРНЫЕ дедлайны: окно отказа (startedAt + 3 мин) считается
      // на клиенте и не меняет состояние на сервере — будить его ради него
      // незачем.
      for (const raw of [
        mission.deadlineAt,
        mission.attemptDeadlineAt,
        mission.availableAgainAt,
      ]) {
        if (raw === null) continue
        const at = new Date(raw).getTime()
        if (!Number.isFinite(at)) continue
        if (at > nowMs) {
          wakeups.push(at)
          continue
        }
        // В прошлом: миссия ещё выглядит незакрытой → сервер отстал.
        if (
          mission.status === 'in_progress' ||
          mission.availableAgainAt !== null
        ) {
          staleCount += 1
        }
      }
    }

    // Оставляем только будущие: прошедшие закроет немедленный resync ниже.
    const upcoming = wakeups.sort((a, b) => a - b)

    // Прошедшие дедлайны при «живой» миссии — синхронизируемся сразу. Набор
    // подписываем, чтобы не опрашивать сервер вечно, если он отдаёт тот же
    // просроченный статус: на одну и ту же подпись — не больше трёх попыток.
    const staleSignature = missions
      .filter(
        (mission) =>
          mission.status === 'in_progress' ||
          mission.availableAgainAt !== null,
      )
      .map((mission) => `${mission.id}:${mission.status}`)
      .sort()
      .join('|')

    if (staleSignature !== staleSignatureRef.current) {
      staleSignatureRef.current = staleSignature
      staleRetryRef.current = 0
    }

    const canResyncNow = staleCount > 0

    if (upcoming.length === 0 && !canResyncNow) return

    // Задержка пробуждения.
    //
    // Будущий дедлайн — точно в его момент (+1 c на границу времени сервера).
    //
    // «Залипший» (дедлайн прошёл, а статус ещё живой) — с РАСТУЩИМ интервалом,
    // а не с нулём. Первая версия ставила delay=0, и все STALE_RESYNC_MAX
    // попытки уходили в одну миллисекунду: если сервер в этот момент ещё
    // считал перерыв неистёкшим (расхождение часов телефона и сервера), клиент
    // сжигал весь лимит мгновенно и замолкал навсегда — счётчик оставался на
    // нуле до перезапуска приложения. Теперь повторы разнесены по времени и
    // после лимита продолжается редкий опрос, пока вкладка видима.
    // Первый повтор быстрый (2 c): игрок уже видит нули и ждёт результат.
    // Дальше интервал растёт, чтобы не долбить сервер, если он ещё держит
    // статус (например, расхождение часов).
    const retryDelays = [2_000, 5_000, 15_000, 60_000]
    const delay = canResyncNow
      ? retryDelays[Math.min(staleRetryRef.current, retryDelays.length - 1)]
      : Math.min(upcoming[0] - nowMs + 1_000, 2_147_483_647)
    let isMounted = true

    resyncTimerRef.current = window.setTimeout(() => {
      if (canResyncNow) staleRetryRef.current += 1
      getEngineBootstrap()
        .then((fresh) => {
          if (!isMounted) return
          // Новый bootstrap пересоздаёт missions, эффект перезапускается и
          // планирует следующую точку пробуждения — цепочка продолжается, пока
          // у миссий остаются будущие дедлайны.
          applyBootstrap(fresh)
        })
        .catch(() => {
          // Ошибку не показываем: таймер уже на нуле, актуальный статус
          // придёт при следующем действии или возврате в приложение.
        })
    }, delay)

    return () => {
      isMounted = false
      if (resyncTimerRef.current !== null) {
        window.clearTimeout(resyncTimerRef.current)
        resyncTimerRef.current = null
      }
    }
  }, [authStatus, applyBootstrap, missions])

  function activateProtocol() {
    setAccepted(true)
    setScreen('terminal')
  }

  function stopSession() {
    const confirmed = window.confirm(t('common:confirmEndSession'))

    if (!confirmed) return

    resetProgress()
  }

  if (authStatus !== 'authenticated') {
    return (
      <main className="app-shell">
        <div className="ambient" aria-hidden="true">
          <i className="blob a" />
          <i className="blob b" />
          <i className="blob c" />
        </div>
        <div className="noise" />
        <BriefingScreen
          authStatus={authStatus}
          authError={authError}
          accepted={accepted}
          setAccepted={setAccepted}
          onActivate={activateProtocol}
        />
      </main>
    )
  }

  return (
    <main className="app-shell">
      <div className="ambient" aria-hidden="true">
        <i className="blob a" />
        <i className="blob b" />
        <i className="blob c" />
      </div>
      <div className="noise" />

      <Topbar
        accepted={accepted}
        rootBalance={echo}
        rootBalanceNano={rootBalanceNano}
        onBrandClick={() => setScreen('terminal')}
      />

      {screen === 'briefing' && (
        <BriefingScreen
          authStatus={authStatus}
          authError={authError}
          accepted={accepted}
          setAccepted={setAccepted}
          onActivate={activateProtocol}
        />
      )}

      {screen === 'terminal' && (
        <TerminalScreen
          echo={echo}
          apiStatus={apiStatus}
          missions={missions}
          rootBalance={echo}
          rootBalanceNano={rootBalanceNano}
          inventory={inventory}
          onScreenChange={setScreen}
          onSubmitMission={submitMission}
          onAcceptMission={acceptMission}
          onExpireMission={expireMission}
          onSyncState={() => {
            // Счётчик перерыва/дедлайна дошёл до нуля: сервер снимает перерыв
            // только по запросу клиента, поэтому просим свежий bootstrap.
            getEngineBootstrap()
              .then((fresh) => applyBootstrap(fresh))
              .catch(() => {
                // Сеть недоступна — следующий визит к серверу подтянет статус.
              })
          }}
        />
      )}

      {screen === 'inventory' && (
        <InventoryScreen inventory={inventory} onScreenChange={setScreen} />
      )}

      {screen === 'scanner' && (
        <ScannerScreen
          missions={missions}
          onScreenChange={setScreen}
          onSubmitMission={submitMission}
          geoPosition={geoPosition}
          geoError={geoError}
          onExpireMission={expireMission}
        />
      )}

      {screen === 'map' && (
        <MapScreen
          missions={missions}
          geoPosition={geoPosition}
          geoError={geoError}
        />
      )}

      {/* AR camera screen (8.11+): камера + куб, доступен в build (не dev-only). */}
      {screen === 'camera-test' && (
        <CameraTestScreen
          missions={missions}
          geoPosition={geoPosition}
          onScreenChange={setScreen}
          onExpireMission={expireMission}
        />
      )}

      {screen === 'cipher' && (
        <CipherScreen
          missions={missions}
          onScreenChange={setScreen}
          onSubmitMission={submitMission}
          onExpireMission={expireMission}
        />
      )}

      {/* Sprint Memory-2b: мини-игра «память» (пары карточек). */}
      {screen === 'risk' && (
        <RiskScreen onScreenChange={setScreen} />
      )}

      {screen === 'memory' && (
        <MemoryScreen
          missions={missions}
          onScreenChange={setScreen}
          onSubmitMission={submitMission}
          onExpireMission={expireMission}
        />
      )}

      {screen === 'shop' && (
        <ShopScreen
          inventory={inventory}
          onScreenChange={setScreen}
          onPurchaseComplete={async () => {
            // Refetch bootstrap: inventory + rootBalance после покупки.
            try {
              const fresh = await getEngineBootstrap()
              applyBootstrap(fresh)
            } catch {
              // Покупка прошла, но bootstrap не обновился — не критично.
            }
          }}
        />
      )}

      {screen === 'profile' && (
        <ProfileScreen onScreenChange={setScreen} />
      )}

      {screen === 'team-session' && (
        <TeamSessionScreen onScreenChange={setScreen} missions={missions} />
      )}

      {screen === 'transfer' && (
        <TransferScreen
          rootBalance={echo}
          rootBalanceNano={rootBalanceNano}
          onScreenChange={setScreen}
          onBalanceChange={async () => {
            // Refetch bootstrap: rootBalance после перевода.
            try {
              const fresh = await getEngineBootstrap()
              applyBootstrap(fresh)
            } catch {
              // Перевод прошёл, но bootstrap не обновился — не критично.
            }
          }}
        />
      )}

      {accepted && screen !== 'briefing' && (
        <MobileNavigation
          screen={screen}
          onScreenChange={setScreen}
          onOpenMore={() => setMoreOpen(true)}
        />
      )}

      <MoreSheet
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        onScreenChange={setScreen}
      />

      {accepted && screen !== 'briefing' && (
        <button className="exit-button" onClick={stopSession}>
          {t('common:stopSession')}
        </button>
      )}
    </main>
  )
}

export default App
