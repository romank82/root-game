import type { EngineMission } from '../api/engineApi'

export type MissionLayer = 'solo' | 'team' | 'story'

type GeoPosition = { lat: number; lng: number; accuracy: number } | null

function toRadians(deg: number): number {
  return (deg * Math.PI) / 180
}

function calculateDistanceM(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const R = 6371000
  const φ1 = toRadians(lat1)
  const φ2 = toRadians(lat2)
  const Δφ = toRadians(lat2 - lat1)
  const Δλ = toRadians(lon2 - lon1)
  const a =
    Math.sin(Δφ / 2) ** 2 +
    Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/**
 * Единый выбор активной миссии.
 * Приоритет: ближайшая in_progress со spawn.
 * Используется в радаре (ScannerScreen) и в AR-камере (CameraTestScreen),
 * чтобы оба экрана показывали одну и ту же цель.
 *
 * TODO (Sprint 8.6.k): заменить на явный выбор игроком через UI.
 */
export function useActiveMission(
  missions: EngineMission[],
  geoPosition: GeoPosition,
  layer?: MissionLayer,
): EngineMission | null {
  const matchesLayer = (m: EngineMission): boolean =>
    layer === undefined || m.missionLayer === layer

  if (!geoPosition) {
    // Без GPS — первая in_progress со spawn (порядок не важен для UI).
    return (
      missions.find(
        (m) => m.status === 'in_progress' && m.spawn !== null && matchesLayer(m),
      ) ?? null
    )
  }

  let closest: EngineMission | null = null
  let closestDist = Infinity
  for (const m of missions) {
    if (m.status !== 'in_progress' || m.spawn === null) continue
    if (!matchesLayer(m)) continue
    const d = calculateDistanceM(
      geoPosition.lat,
      geoPosition.lng,
      m.spawn.latitude,
      m.spawn.longitude,
    )
    if (d < closestDist) {
      closestDist = d
      closest = m
    }
  }
  return closest
}