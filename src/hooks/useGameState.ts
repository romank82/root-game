import { useCallback, useState } from 'react'
import {
  acceptEngineMission,
  getEngineBootstrap,
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

  const acceptMission = useCallback(
    async (missionId: string): Promise<{ accepted: boolean; error?: string }> => {
      // 1. Запрос GPS
      let coords: GeolocationPosition
      try {
        coords = await new Promise<GeolocationPosition>((resolve, reject) => {
          if (!navigator.geolocation) {
            reject(new Error('Геолокация не поддерживается устройством.'))
            return
          }
          navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 15000,
            maximumAge: 0,
          })
        })
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Не удалось получить GPS.'
        return { accepted: false, error: message }
      }

      // 2. Вызов accept
      try {
        await acceptEngineMission(missionId, {
          latitude: coords.coords.latitude,
          longitude: coords.coords.longitude,
          accuracy: coords.coords.accuracy,
        })
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Сервер не принял миссию.'
        return { accepted: false, error: message }
      }

      // 3. Refresh bootstrap, чтобы клиентское состояние missions/spawn обновилось
      try {
        const fresh = await getEngineBootstrap()
        applyEngineBootstrap(fresh)
      } catch (err) {
        // Миссия принята, но bootstrap не обновился — не считаем это ошибкой accept,
        // но возвращаем предупреждение. UI может показать «перезагрузите страницу».
        const message =
          err instanceof Error ? err.message : 'Не удалось обновить состояние.'
        return { accepted: true, error: message }
      }

      return { accepted: true }
    },
    [applyEngineBootstrap],
  )

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
    acceptMission,
    resetProgress,
  }
}
