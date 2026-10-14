import { useEffect, useRef } from 'react'
import { Circle, CircleMarker, MapContainer, TileLayer, useMap } from 'react-leaflet'
import type { Map as LeafletMap } from 'leaflet'
import type { EngineMission } from '../../api/engineApi'
import 'leaflet/dist/leaflet.css'
import { useActiveMission } from '../../hooks/useActiveMission'

const LAYER_COLORS: Record<string, string> = {
  solo: '#ffcc00',
  team: '#4da6ff',
  story: '#ff5c5c',
}

// Приближение, когда знаем позицию игрока.
const FOCUS_ZOOM = 16

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
  const isInitialized = useRef(false)

  useEffect(() => {
    if (isInitialized.current) return
    map.setView(center, zoom)
    isInitialized.current = true
  }, [center, zoom, map])

  return null
}

interface MapScreenProps {
  missions: EngineMission[]
  geoPosition: { lat: number; lng: number; accuracy: number } | null
  geoError: string | null
}

export function MapScreen({ missions, geoPosition, geoError }: MapScreenProps) {
  // Показываем только активную (ближайшую) миссию. Остальные — в других экранах.
  const activeMission = useActiveMission(missions, geoPosition)
  const mapRef = useRef<LeafletMap | null>(null)

  if (!geoPosition) {
    return (
      <section className="map-screen map-screen-loading">
        <div className="map-loading-box">
          {geoError ? (
            <>
              <p className="map-loading-title">ОШИБКА ГЕОЛОКАЦИИ</p>
              <p className="map-loading-text">{geoError}</p>
            </>
          ) : (
            <>
              <p className="map-loading-title">ОПРЕДЕЛЯЕМ ВАШУ ПОЗИЦИЮ…</p>
              <p className="map-loading-text">
                Разрешите геолокацию, чтобы увидеть карту и зоны миссий.
              </p>
            </>
          )}
        </div>
      </section>
    )
  }

  function centerOnPlayer() {
    if (mapRef.current && geoPosition) {
      mapRef.current.setView([geoPosition.lat, geoPosition.lng], FOCUS_ZOOM)
    }
  }

  return (
    <section className="map-screen">
      <MapContainer
        ref={mapRef}
        center={[geoPosition.lat, geoPosition.lng]}
        zoom={FOCUS_ZOOM}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapController center={[geoPosition.lat, geoPosition.lng]} zoom={FOCUS_ZOOM} />

        {activeMission?.spawn && (
          <Circle
            center={[activeMission.spawn.latitude, activeMission.spawn.longitude]}
            radius={activeMission.spawn.zoneRadiusMeters ?? 50}
            pathOptions={{
              color: LAYER_COLORS[activeMission.missionLayer] ?? '#ffcc00',
              fillColor: LAYER_COLORS[activeMission.missionLayer] ?? '#ffcc00',
              fillOpacity: 0.5,
              weight: 3,
            }}
          />
        )}

        {/* Точка игрока — синий кружок. */}
        <CircleMarker
          center={[geoPosition.lat, geoPosition.lng]}
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
          center={[geoPosition.lat, geoPosition.lng]}
          radius={8}
          pathOptions={{
            color: '#1976d2',
            fillColor: '#1976d2',
            fillOpacity: 0.15,
            weight: 1,
          }}
        />
      </MapContainer>

      <div className="map-overlay">
        {geoError && <div className="map-overlay-error">{geoError}</div>}
        <button
          className="map-overlay-button map-overlay-button-compact"
          onClick={centerOnPlayer}
        >
          ⌖ На игрока
        </button>
        <div className="map-overlay-info">
          {geoPosition.lat.toFixed(5)}, {geoPosition.lng.toFixed(5)}
          {' '}± {Math.round(geoPosition.accuracy)} м
        </div>
      </div>
    </section>
  )
}