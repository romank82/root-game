import { Fragment, useEffect } from 'react'
import { Circle, CircleMarker, MapContainer, TileLayer, useMap } from 'react-leaflet'
import type { EngineMission } from '../../api/engineApi'
import 'leaflet/dist/leaflet.css'

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

  useEffect(() => {
    map.setView(center, zoom)
  }, [center, zoom, map])

  return null
}

interface MapScreenProps {
  missions: EngineMission[]
  geoPosition: { lat: number; lng: number; accuracy: number } | null
  geoError: string | null
}

export function MapScreen({ missions, geoPosition, geoError }: MapScreenProps) {
  const missionsWithSpawn = missions.filter(
    (m) => m.spawn !== null && m.status === 'in_progress',
  )

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

  return (
    <section className="map-screen">
      <MapContainer
        center={[geoPosition.lat, geoPosition.lng]}
        zoom={FOCUS_ZOOM}
        style={{ width: '100%', height: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapController center={[geoPosition.lat, geoPosition.lng]} zoom={FOCUS_ZOOM} />

        {missionsWithSpawn.map((mission) => {
          const spawn = mission.spawn!
          const hasCenter =
            spawn.generatedFromLat !== null && spawn.generatedFromLng !== null
          return (
            <Fragment key={mission.id}>
              {/* Большой круг — область поиска. Центр — точка accept. */}
              {hasCenter && (
                <Circle
                  center={[spawn.generatedFromLat!, spawn.generatedFromLng!]}
                  radius={spawn.searchRadiusMeters}
                  pathOptions={{
                    color: '#00ff88',
                    fillColor: '#00ff88',
                    fillOpacity: 0.08,
                    weight: 2,
                  }}
                />
              )}

              {/* Маленький круг — точка spawn. Только в dev. */}
              {import.meta.env.DEV && (
                <Circle
                  center={[spawn.latitude, spawn.longitude]}
                  radius={spawn.zoneRadiusMeters ?? 20}
                  pathOptions={{
                    color: '#ffcc00',
                    fillColor: '#ffcc00',
                    fillOpacity: 0.4,
                    weight: 2,
                  }}
                />
              )}
            </Fragment>
          )
        })}

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
        <div className="map-overlay-info">
          {geoPosition.lat.toFixed(5)}, {geoPosition.lng.toFixed(5)}
          {' '}± {Math.round(geoPosition.accuracy)} м
        </div>
      </div>
    </section>
  )
}