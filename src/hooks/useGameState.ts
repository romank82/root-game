import { useCallback, useState } from 'react'
import {
  submitEngineMission,
  type EngineBootstrap,
  type EngineInventoryItem,
  type EngineMission,
  type EngineSegment,
  type EngineStoryNode,
} from '../api/engineApi'
import type { ApiStatus, Screen } from '../types/game'

export function useGameState() {
  const [screen, setScreen] = useState<Screen>(() => {
    const saved = localStorage.getItem('chimera-screen')
    return saved === 'terminal' ||
      saved === 'archive' ||
      saved === 'inventory' ||
      saved === 'scanner' ||
      saved === 'map'
      ? saved
      : 'briefing'
  })

  const [accepted, setAccepted] = useState(() => {
    return localStorage.getItem('chimera-accepted') === 'true'
  })

  // ROOT is a backend-maintained cache over immutable ledger transactions.
  // The client displays only the latest authenticated bootstrap value.
  const [echo, setEcho] = useState(0)
  const [inventory, setInventory] = useState<EngineInventoryItem[]>([])
  const [storyNodes, setStoryNodes] = useState<EngineStoryNode[]>([])
  const [missions, setMissions] = useState<EngineMission[]>([])
  const [segments, setSegments] = useState<EngineSegment[]>([])
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  const applyEngineBootstrap = useCallback((bootstrap: EngineBootstrap) => {
    setEcho(bootstrap.wallet.availableBalance)
    setInventory(bootstrap.inventory)
    setStoryNodes(bootstrap.storyNodes)
    setMissions(bootstrap.missions)
    setSegments(bootstrap.segments)
    setApiStatus('online')
  }, [])

  const submitMission = useCallback(async (
    missionId: string,
    payload: { answer?: string; sequence?: string[] },
  ) => {
    try {
      const response = await submitEngineMission(missionId, payload)
      applyEngineBootstrap(response.bootstrap)
      return response
    } catch {
      setApiStatus('offline')
      return null
    }
  }, [applyEngineBootstrap])

  const resetProgress = useCallback(() => {
    setAccepted(false)
    setScreen('briefing')
    localStorage.removeItem('chimera-screen')
    localStorage.removeItem('chimera-accepted')
  }, [])

  return {
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
    setApiStatus,
    applyEngineBootstrap,
    submitMission,
    resetProgress,
  }
}
