import { useEffect, useState } from 'react'

export type GeoPosition = {
  lat: number
  lng: number
  accuracy: number
}

export type GeoPermissionStatus = 'granted' | 'denied' | 'prompt' | 'unknown'

/**
 * Единый GPS-канал приложения. Один watchPosition на всё приложение,
 * создаётся один раз в App.tsx. Экземпляры не пересоздаются при переключении
 * экранов, поэтому система не запрашивает разрешение заново.
 */
export function useGeoPosition() {
  const [position, setPosition] = useState<GeoPosition | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [permission, setPermission] = useState<GeoPermissionStatus>('unknown')

  useEffect(() => {
    let cancelled = false

    async function init() {
      // 1) Проверим разрешение без запроса (если API доступен).
      if (navigator.permissions && navigator.permissions.query) {
        try {
          const status = await navigator.permissions.query({ name: 'geolocation' as PermissionName })
          if (cancelled) return
          setPermission(status.state as GeoPermissionStatus)
          if (status.state === 'denied') {
            setError('Доступ к геолокации запрещён. Разрешите его в настройках браузера или Telegram.')
            return
          }
        } catch {
          // Permissions API не поддерживает geolocation — игнорируем, идём дальше.
        }
      }

      // 2) Запускаем один watchPosition на всё приложение.
      if (!navigator.geolocation) {
        if (cancelled) return
        setError('Геолокация не поддерживается этим устройством.')
        return
      }

      const watchId = navigator.geolocation.watchPosition(
        (pos) => {
          if (cancelled) return
          setPosition({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
          })
          setError(null)
        },
        (err) => {
          if (cancelled) return
          if (err.code === err.PERMISSION_DENIED) {
            setError('Доступ к геолокации запрещён.')
          } else if (err.code === err.POSITION_UNAVAILABLE) {
            setError('Не удалось определить позицию. Проверьте GPS.')
          } else {
            setError('Ошибка геолокации.')
          }
        },
        {
          enableHighAccuracy: true,
          maximumAge: 30000,
          timeout: 20000,
        },
      )

      return () => {
        navigator.geolocation.clearWatch(watchId)
      }
    }

    let cleanup: (() => void) | undefined
    init().then((fn) => {
      cleanup = fn
    })

    return () => {
      cancelled = true
      if (cleanup) cleanup()
    }
  }, [])

  return { position, error, permission }
}