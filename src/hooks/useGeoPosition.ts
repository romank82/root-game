import { useEffect, useState } from 'react'
import i18n from '../i18n'

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
      // 1) Опрос статуса (информативно, НЕ влияет на поток).
      // Никогда не делаем ранний return по 'denied' — система может вернуть
      // устаревший 'denied', а реальный диалог покажет только watchPosition.
      if (navigator.permissions && navigator.permissions.query) {
        try {
          const status = await navigator.permissions.query({
            name: 'geolocation' as PermissionName,
          })
          if (cancelled) return
          setPermission(status.state as GeoPermissionStatus)
        } catch {
          // Permissions API не поддерживает geolocation — игнорируем.
        }
      }

      // 2) ВСЕГДА запускаем watchPosition — это единственный вызов,
      // который триггерит системный диалог разрешений в WebView.
      if (!navigator.geolocation) {
        if (cancelled) return
        setError(i18n.t('common:gps.notSupported'))
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
          setPermission('granted')
          setError(null)
        },
        (err) => {
          if (cancelled) return
          if (err.code === err.PERMISSION_DENIED) {
            setPermission('denied')
            setError(i18n.t('common:gps.permissionDenied'))
          } else if (err.code === err.POSITION_UNAVAILABLE) {
            setError(i18n.t('common:gps.positionUnavailable'))
          } else {
            setError(i18n.t('common:gps.positionError'))
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