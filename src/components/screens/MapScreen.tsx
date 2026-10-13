import { useCallback, useEffect, useState } from 'react'
import { CircleMarker, MapContainer, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'

// Заглушка пока GPS не получен — Москва.
const DEFAULT_CENTER: [number, number] = [55.7558, 37.6173]
const DEFAULT_ZOOM = 13
// Приближение, когда знаем позицию игрока.
const FOCUS_ZOOM = 16

type GpsCoords = {
  latitude: number
  longitude: number
  accuracy: number
}

/**
 * Вспомогательный компонент внутри MapContainer: умеет двигать карту,
 * т.к. props center/zoom у MapContainer — только initial.
 */
function MapController({
  center,
  zoom,
}: {
  center: [number, number]
  zoom: number
}) {
  const map = useMap()

  useEffect(() => {
    map.setView(center, zoom)
  }, [center, zoom, map])

  return null
}

export function MapScreen() {
  const [gps, setGps] = useState<GpsCoords | null>(null)
  const [gpsError, setGpsError] = useState<string | null>(null)
  const [loadingGps, setLoadingGps] = useState(false)

  const requestGps = useCallback(() => {
    if (!navigator.geolocation) {
      setGpsError('Геолокация не поддерживается этим устройством.')
      return
    }
    setLoadingGps(true)
    setGpsError(null)

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setGps({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        })
        setLoadingGps(false)
      },
      (error) => {
        const messages: Record<number, string> = {
          1: 'Доступ к геолокации запрещён. Разрешите в настройках.',
          2: 'Не удалось определить позицию. Проверьте GPS.',
          3: 'Превышено время ожидания GPS.',
        }
        setGpsError(messages[error.code] ?? 'Ошибка геолокации.')
        setLoadingGps(false)
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  }, [])

  useEffect(() => {
    requestGps()
  }, [requestGps])

  const center: [number, number] = gps
    ? [gps.latitude, gps.longitude]
    : DEFAULT_CENTER
  const zoom = gps ? FOCUS_ZOOM : DEFAULT_ZOOM

  return (
    <section className="map-screen">
      <MapContainer
        center={center}
        zoom={zoom}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapController center={center} zoom={zoom} />

        {gps && (
          <>
            {/* Точка игрока — синий кружок. */}
            <CircleMarker
              center={[gps.latitude, gps.longitude]}
              radius={8}
              pathOptions={{
                color: '#ffffff',
                fillColor: '#1976d2',
                fillOpacity: 1,
                weight: 3,
              }}
            />
            {/* Радиус точности — тонкий ореол. */}
            <CircleMarker
              center={[gps.latitude, gps.longitude]}
              radius={8}
              pathOptions={{
                color: '#1976d2',
                fillColor: '#1976d2',
                fillOpacity: 0.15,
                weight: 1,
              }}
            />
          </>
        )}
      </MapContainer>

      <div className="map-overlay">
        {loadingGps && <div className="map-overlay-info">Определяем вашу позицию…</div>}
        {gpsError && <div className="map-overlay-error">{gpsError}</div>}
        {gps && !loadingGps && (
          <div className="map-overlay-info">
            {gps.latitude.toFixed(5)}, {gps.longitude.toFixed(5)}
            {' '}± {Math.round(gps.accuracy)} м
          </div>
        )}
        <button
          className="map-overlay-button"
          onClick={requestGps}
          disabled={loadingGps}
        >
          {loadingGps ? 'Обновление…' : 'Обновить мою позицию'}
        </button>
      </div>
    </section>
  )
}