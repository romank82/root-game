import { useCallback, useEffect, useState } from 'react'
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
import { ArchiveScreen } from './components/screens/ArchiveScreen'
import { InventoryScreen } from './components/screens/InventoryScreen'
import { ScannerScreen } from './components/screens/ScannerScreen'
import { ShopScreen } from './components/screens/ShopScreen'
import { ProfileScreen } from './components/screens/ProfileScreen'
import { TransferScreen } from './components/screens/TransferScreen'
import { MapScreen } from './components/screens/MapScreen'
// TEMP: dev-only camera test screen — удалить в Sprint 8.6.g.
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
    storyNodes,
    missions,
    segments,
    apiStatus,
    
    applyEngineBootstrap,
    submitMission,
    acceptMission,
    expireMission,
    resetProgress,
  } = useGameState()

  // Sprint 11.8 NanoROOT (этап 2C): дробный баланс для шапки в nano.
  // useGameState хранит только целый ROOT (echo) — nano берём здесь при
  // каждом применении bootstrap и передаём в Topbar.
  const [rootBalanceNano, setRootBalanceNano] = useState<number | null>(null)

  const applyBootstrap = useCallback(
    (bootstrap: EngineBootstrap) => {
      applyEngineBootstrap(bootstrap)
      setRootBalanceNano(
        bootstrap.player.rootBalanceNano
          ?? bootstrap.wallet.availableBalanceNano
          ?? null,
      )
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
          inventory={inventory}
          onScreenChange={setScreen}
          onSubmitMission={submitMission}
          onAcceptMission={acceptMission}
          onExpireMission={expireMission}
        />
      )}

      {screen === 'archive' && (
        <ArchiveScreen
          storyNodes={storyNodes}
          onScreenChange={setScreen}
        />
      )}

      {screen === 'inventory' && (
        <InventoryScreen inventory={inventory} onScreenChange={setScreen} />
      )}

      {screen === 'scanner' && (
        <ScannerScreen
          missions={missions}
          segments={segments}
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

      {/* TEMP: dev-only camera test screen — удалить в Sprint 8.6.g. */}
      {import.meta.env.DEV && screen === 'camera-test' && (
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
