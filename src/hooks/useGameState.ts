import { useState, useCallback } from 'react'
import { submitEngineMission, resetEngineDemoProgress, type EngineBootstrap, type EngineInventoryItem, type EngineMission, type EngineStoryNode } from '../api/engineApi'
import type { ApiStatus, Screen } from '../types/game'

export function useGameState() {
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
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  const applyEngineBootstrap = useCallback((bootstrap: EngineBootstrap) => {
    setEcho(bootstrap.wallet.availableBalance)
    setInventory(bootstrap.inventory)
    setStoryNodes(bootstrap.storyNodes)
    setMissions(bootstrap.missions)
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

  const resetProgress = useCallback(async () => {
    try {
      const bootstrap = await resetEngineDemoProgress()
      applyEngineBootstrap(bootstrap)
      setAccepted(false)
      setScreen('briefing')
      localStorage.removeItem('chimera-screen')
      localStorage.removeItem('chimera-accepted')
      localStorage.removeItem('chimera-echo')
    } catch {
      setApiStatus('offline')
    }
  }, [applyEngineBootstrap])

  return {
    screen,
    setScreen,
    accepted,
    setAccepted,
    echo,
    inventory,
    storyNodes,
    missions,
    apiStatus,
    setApiStatus,
    applyEngineBootstrap,
    submitMission,
    resetProgress,
  }
}
