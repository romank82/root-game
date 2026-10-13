import { useEffect } from 'react'
import './App.css'
import { useAuth } from './hooks/useAuth'
import { useGameState } from './hooks/useGameState'
import { Topbar } from './components/Topbar'
import { MobileNavigation } from './components/MobileNavigation'
import { BriefingScreen } from './components/screens/BriefingScreen'
import { TerminalScreen } from './components/screens/TerminalScreen'
import { ArchiveScreen } from './components/screens/ArchiveScreen'
import { InventoryScreen } from './components/screens/InventoryScreen'
import { ScannerScreen } from './components/screens/ScannerScreen'
import { ShopScreen } from './components/screens/ShopScreen'
import { MapScreen } from './components/screens/MapScreen'
import { DevAcceptMissionButton } from './components/DevAcceptMissionButton'

function App() {
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
    resetProgress,
  } = useGameState()

  const { authStatus, authError } = useAuth(applyEngineBootstrap)

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
    const confirmed = window.confirm(
      'Завершить игровую сессию? Прогресс сохранится, вы сможете вернуться.',
    )

    if (!confirmed) return

    resetProgress()
  }

  if (authStatus !== 'authenticated') {
    return (
      <main className="app-shell">
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
      <div className="noise" />

      <Topbar
        accepted={accepted}
        rootBalance={echo}
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
          onScreenChange={setScreen}
          onSubmitMission={submitMission}
          onAcceptMission={acceptMission}
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
        />
      )}

      {screen === 'map' && <MapScreen missions={missions} />}

      {screen === 'shop' && (
        <ShopScreen onScreenChange={setScreen} />
      )}

      {accepted && screen !== 'briefing' && (
        <MobileNavigation screen={screen} onScreenChange={setScreen} />
      )}

      {accepted && screen !== 'briefing' && (
        <button className="exit-button" onClick={stopSession}>
          ОСТАНОВИТЬ СЕССИЮ
        </button>
      )}

      {import.meta.env.DEV && <DevAcceptMissionButton />}
    </main>
  )
}

export default App
