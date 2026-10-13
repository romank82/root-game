// TEMP: dev-only AR camera — удалить в Sprint 8.6.j.
// Единый AR-режим: камера + куб с QR, позиционированный по компасу и GPS.

import { useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import type { EngineMission } from '../../api/engineApi'
import { getMissionQrPayload } from '../../api/engineApi'
import { useCameraStream } from '../../hooks/useCameraStream'

interface CameraTestScreenProps {
  missions: EngineMission[]
  geoPosition: { lat: number; lng: number; accuracy: number } | null
}

// Радиус, до которого куб виден и активен (в метрах).
const VISIBLE_RANGE_M = 70

function toRadians(deg: number): number {
  return (deg * Math.PI) / 180
}

function toDegrees(rad: number): number {
  return (rad * 180) / Math.PI
}

function calculateBearing(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const φ1 = toRadians(lat1)
  const φ2 = toRadians(lat2)
  const Δλ = toRadians(lon2 - lon1)
  const y = Math.sin(Δλ) * Math.cos(φ2)
  const x =
    Math.cos(φ1) * Math.sin(φ2) -
    Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ)
  return (toDegrees(Math.atan2(y, x)) + 360) % 360
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

export function CameraTestScreen({
  missions,
  geoPosition,
}: CameraTestScreenProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const { stream, status, error } = useCameraStream()

  const [heading, setHeading] = useState<number | null>(null)
  const [qrPayload, setQrPayload] = useState<{
    payload: string
    hmac: string
  } | null>(null)

  // Выбираем ближайшую in_progress миссию со spawn.
  // TODO (Sprint 8.6.k): заменить на явный выбор активной миссии игроком.
  const mission = (() => {
    if (!geoPosition) {
      // Без GPS — берём первую in_progress со spawn (порядок не важен для UI).
      return missions.find(
        (m) => m.status === 'in_progress' && m.spawn !== null,
      ) ?? null
    }
    let closest: EngineMission | null = null
    let closestDist = Infinity
    for (const m of missions) {
      if (m.status !== 'in_progress' || m.spawn === null) continue
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
  })()

  const spawn = mission?.spawn ?? null

  // Привязка MediaStream к <video>.
  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream
      videoRef.current.play().catch(() => {})
    }
  }, [stream])

  // Компас с throttle 10 Hz + EMA 0.3.
  const lastUpdateRef = useRef<number>(0)
  const smoothedRef = useRef<number | null>(null)

  useEffect(() => {
    function onOrientation(event: DeviceOrientationEvent) {
      const alpha = event.alpha
      if (alpha === null || alpha === undefined) return

      const now = Date.now()
      if (now - lastUpdateRef.current < 100) return
      lastUpdateRef.current = now

      let raw: number
      const webkit = (
        event as DeviceOrientationEvent & {
          webkitCompassHeading?: number
        }
      ).webkitCompassHeading
      if (typeof webkit === 'number') {
        raw = webkit
      } else {
        const normalized = ((alpha % 360) + 360) % 360
        raw = (360 - normalized) % 360
      }

      const prev = smoothedRef.current
      let smoothed: number
      if (prev === null) {
        smoothed = raw
      } else {
        let diff = raw - prev
        if (diff > 180) diff -= 360
        if (diff < -180) diff += 360
        smoothed = (prev + 0.3 * diff + 360) % 360
      }
      smoothedRef.current = smoothed
      setHeading(smoothed)
    }

    if (typeof DeviceOrientationEvent === 'undefined') return
    window.addEventListener(
      'deviceorientationabsolute',
      onOrientation as EventListener,
      true,
    )
    window.addEventListener(
      'deviceorientation',
      onOrientation as EventListener,
      true,
    )
    return () => {
      window.removeEventListener(
        'deviceorientationabsolute',
        onOrientation as EventListener,
        true,
      )
      window.removeEventListener(
        'deviceorientation',
        onOrientation as EventListener,
        true,
      )
    }
  }, [])

  // Загрузка QR-payload один раз при готовности камеры.
  useEffect(() => {
    if (status !== 'ready') return
    if (!mission) return
    let cancelled = false
    async function load() {
      try {
        const data = await getMissionQrPayload(mission!.id)
        if (cancelled) return
        setQrPayload({ payload: data.payload, hmac: data.hmac })
      } catch {
        // Тихо: QR не готов — куб просто не покажется.
      }
    }
    setQrPayload(null)
    void load()
    return () => {
      cancelled = true
    }
  }, [status, mission?.id])

  // Вычислить delta и distance.
  let deltaDeg: number | null = null
  let distanceM: number | null = null
  if (geoPosition && spawn) {
    const bearing = calculateBearing(
      geoPosition.lat,
      geoPosition.lng,
      spawn.latitude,
      spawn.longitude,
    )
    distanceM = calculateDistanceM(
      geoPosition.lat,
      geoPosition.lng,
      spawn.latitude,
      spawn.longitude,
    )
    if (heading !== null) {
      deltaDeg = ((bearing - heading + 540) % 360) - 180
    }
  }

  // Позиция куба на экране в % по горизонтали.
  // delta = 0 → 50% (центр), delta = +30° → 100% (правый край), delta = -30° → 0% (левый край).
  // Клэмпим в [-30, 130], чтобы куб уезжал немного за край при большом отклонении.
  const rawPosition =
    deltaDeg === null ? 50 : 50 + (deltaDeg / 60) * 100
  const leftPercent = Math.max(-30, Math.min(130, rawPosition))

  // Масштаб: далеко → 0.6, близко → 2.0.
  const scale =
    distanceM === null
      ? 1
      : Math.max(0.6, Math.min(2, 1 + (VISIBLE_RANGE_M - distanceM) / 50))

  const isNear = distanceM !== null && distanceM <= VISIBLE_RANGE_M
  const isCentered = deltaDeg !== null && Math.abs(deltaDeg) < 15

  return (
    <section className="camera-test-screen">
      <div className="camera-video-area">
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          className="camera-test-video"
        />

        {status === 'starting' && (
          <div className="camera-test-overlay">Запуск камеры…</div>
        )}

        {status === 'error' && (
          <div className="camera-test-overlay camera-test-overlay-error">
            {error ?? 'Ошибка камеры'}
          </div>
        )}

        {status === 'ready' && isNear && qrPayload && (
          <div
            className={`ar-cube-world${isCentered ? ' is-centered' : ''}`}
            style={{
              left: `${leftPercent}%`,
              transform: `translate(-50%, -50%) scale(${scale})`,
            }}
          >
            <div className="ar-cube-3d">
              <div className="ar-cube-3d-face ar-cube-3d-front">
                <QRCodeSVG
                  value={`${qrPayload.payload}.${qrPayload.hmac}`}
                  size={120}
                  bgColor="#000000"
                  fgColor="#00ff88"
                  level="M"
                  style={{ width: '100%', height: '100%' }}
                />
              </div>
              <div className="ar-cube-3d-face ar-cube-3d-back">
                <QRCodeSVG
                  value={`${qrPayload.payload}.${qrPayload.hmac}`}
                  size={120}
                  bgColor="#000000"
                  fgColor="#00ff88"
                  level="M"
                  style={{ width: '100%', height: '100%' }}
                />
              </div>
              <div className="ar-cube-3d-face ar-cube-3d-right" />
              <div className="ar-cube-3d-face ar-cube-3d-left" />
              <div className="ar-cube-3d-face ar-cube-3d-top" />
              <div className="ar-cube-3d-face ar-cube-3d-bottom" />
            </div>
          </div>
        )}

        {status === 'ready' && !geoPosition && (
          <div className="ar-hint">Определяем вашу позицию…</div>
        )}

        {status === 'ready' && distanceM !== null && distanceM > VISIBLE_RANGE_M && (
          <div className="ar-hint">
            Цель в {Math.round(distanceM)} м. Идите по радару.
          </div>
        )}

        {status === 'ready' &&
          isNear &&
          deltaDeg !== null &&
          Math.abs(deltaDeg) > 30 && (
            <div className="ar-hint">
              Поверните телефон {deltaDeg > 0 ? 'вправо' : 'влево'} на{' '}
              {Math.round(Math.abs(deltaDeg))}°
            </div>
          )}
      </div>
    </section>
  )
}
