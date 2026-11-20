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

  // Синхронизация в момент истечения дедлайна.
  // Бэкенд закрывает просроченную миссию лениво (_synchronize_player_missions
  // внутри bootstrap), поэтому клиент сам запрашивает bootstrap в момент
  // дедлайна — иначе таймер замирает на 00:00, а миссия остаётся in_progress
  // до перезапуска приложения. Берём ближайший дедлайн по всем миссиям.
  const resyncTimerRef = useRef<number | null>(null)

  useEffect(() => {
    if (authStatus !== 'authenticated') return

    if (resyncTimerRef.current !== null) {
      window.clearTimeout(resyncTimerRef.current)
      resyncTimerRef.current = null
    }

    // Истёкшие дедлайны (в прошлом) не планируем — их закроет эффект
    // visibilitychange или ближайшее действие игрока.
    const nowMs = Date.now()
    const upcoming = missions
      .map((mission) => mission.deadlineAt)
      .filter((value): value is string => Boolean(value))
      .map((value) => new Date(value).getTime())
      .filter((value) => Number.isFinite(value) && value > nowMs)
      .sort((a, b) => a - b)

    if (upcoming.length === 0) return

    // +1 c: даём серверу пройти собственную границу дедлайна.
    const delay = Math.min(upcoming[0] - nowMs + 1_000, 2_147_483_647)
    let isMounted = true

    resyncTimerRef.current = window.setTimeout(() => {
      getEngineBootstrap()
        .then((fresh) => {
          if (!isMounted) return
          applyBootstrap(fresh)
        })
        .catch(() => {
          // Ошибку не показываем: таймер уже на 00:00, игрок увидит
          // актуальный статус при следующем действии.
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
