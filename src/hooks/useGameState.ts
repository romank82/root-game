import { useCallback, useEffect, useState } from 'react'
import {
  acceptEngineMission,
  expireEngineMission,
  getEngineBootstrap,
  submitEngineMission,
  type EngineBootstrap,
  type EngineInventoryItem,
  type EngineMission,
  type EngineSegment,
  type EngineStoryNode,
} from '../api/engineApi'
import i18n from '../i18n'
import type { ApiStatus, Screen } from '../types/game'

export function useGameState() {
  const [screen, setScreen] = useState<Screen>(() => {
    // Если игрок не активировал протокол — всегда показываем брифинг.
    // Иначе можно застрять в состоянии accepted=false + screen=<не briefing>:
    // таб-бар скрыт (условие accepted && ...), брифинг тоже не рендерится
    // (условие screen === 'briefing'), игрок застревает без навигации.
    const accepted = localStorage.getItem('chimera-accepted') === 'true'
    if (!accepted) {
      return 'briefing'
    }

    const saved = localStorage.getItem('chimera-screen')
    // 'camera-test' НЕ разрешаем как стартовый экран: автозапуск камеры
    // без жеста пользователя зависает в Android WebView.
    // Открытие камеры — только по явному действию игрока.
    if (saved === 'terminal' ||
        saved === 'archive' ||
        saved === 'inventory' ||
        saved === 'scanner' ||
        saved === 'map') {
      return saved
    }
    return 'terminal'
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

  // Sprint Trans-4b: контент миссий (title/description/content.ui) переводится
  // на бэкенде в bootstrap по ?lang= (Trans-4a). При смене языка интерфейса
  // перезапрашиваем bootstrap, чтобы миссии приехали на новом языке.
  // Первичная загрузка остаётся за useAuth — здесь только смена языка,
  // поэтому нет риска двойного запроса на старте.
  useEffect(() => {
    let isMounted = true

    const handleLanguageChanged = () => {
      getEngineBootstrap()
        .then((bootstrap) => {
          if (!isMounted) return
          applyEngineBootstrap(bootstrap)
        })
        .catch(() => {
          // Не роняем UI: при ошибке остаётся прежний (уже загруженный)
          // контент, следующий успешный bootstrap подтянет актуальный язык.
          if (!isMounted) return
        })
    }

    i18n.on('languageChanged', handleLanguageChanged)

    return () => {
      isMounted = false
      i18n.off('languageChanged', handleLanguageChanged)
    }
  }, [applyEngineBootstrap])

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

  const expireMission = useCallback(
    async (missionId: string): Promise<{ ok: boolean; error?: string }> => {
      try {
        await expireEngineMission(missionId)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Ошибка запроса.'
        return { ok: false, error: message }
      }

      try {
        const fresh = await getEngineBootstrap()
        applyEngineBootstrap(fresh)
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Не удалось обновить состояние.'
        return { ok: true, error: message }
      }

      return { ok: true }
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
    expireMission,
    resetProgress,
  }
}
