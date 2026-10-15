// TEMP: dev-only AR camera — удалить в Sprint 8.6.j.
// Единый AR-режим: камера + куб с QR, позиционированный по компасу и GPS.

import { useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import type { EngineMission } from '../../api/engineApi'
import { getMissionQrPayload } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { useCameraStream } from '../../hooks/useCameraStream'
import { useActiveMission } from '../../hooks/useActiveMission'
import { MissionTimer } from '../MissionTimer'

interface CameraTestScreenProps {
  missions: EngineMission[]
  geoPosition: { lat: number; lng: number; accuracy: number } | null
  onExpireMission: (
    missionId: string,
  ) => Promise<{ ok: boolean; error?: string }>
  onScreenChange: (screen: Screen) => void
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
  onExpireMission,
  onScreenChange,
}: CameraTestScreenProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const { stream, status, error } = useCameraStream()

  const [heading, setHeading] = useState<number | null>(null)
  const [qrPayload, setQrPayload] = useState<{
    payload: string
    hmac: string
  } | null>(null)

  // Единый выбор активной миссии: ближайшая in_progress со spawn.
  const mission = useActiveMission(missions, geoPosition)

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
  const lastAbsoluteAtRef = useRef<number>(0)
  const lastRawHeadingRef = useRef<number | null>(null)
  const jumpCounterRef = useRef<number>(0)
  const smoothedDistanceRef = useRef<number | null>(null)
  const smoothedDeltaRef = useRef<number | null>(null)
  const lastGoodPositionRef = useRef<{ lat: number; lng: number } | null>(null)
  const anchoredBearingRef = useRef<number | null>(null)

  useEffect(() => {
    function onOrientation(event: DeviceOrientationEvent) {
      const alpha = event.alpha
      if (alpha === null || alpha === undefined) return

      const now = Date.now()

      const isAbsolute =
        event.type === 'deviceorientationabsolute' ||
        (event as DeviceOrientationEvent).absolute === true

      if (isAbsolute) {
        lastAbsoluteAtRef.current = now
      } else {
        if (now - lastAbsoluteAtRef.current < 2000) return
      }

      if (now - lastUpdateRef.current < 50) return
      lastUpdateRef.current = now

      let raw: number
      const webkit = (
        event as DeviceOrientationEvent & {
          webkitCompassHeading?: number
        }
      ).webkitCompassHeading

      if (typeof webkit === 'number') {
        raw = webkit
      } else if (isAbsolute) {
        const normalized = ((alpha % 360) + 360) % 360
        raw = (360 - normalized) % 360
      } else {
        raw = ((alpha % 360) + 360) % 360
      }

      const prevRaw = lastRawHeadingRef.current
      if (prevRaw !== null) {
        let jump = raw - prevRaw
        if (jump > 180) jump -= 360
        if (jump < -180) jump += 360
        if (Math.abs(jump) > 90) {
          jumpCounterRef.current += 1
          return
        }
      }
      lastRawHeadingRef.current = raw

      const prev = smoothedRef.current
      let smoothed: number
      if (prev === null) {
        smoothed = raw
      } else {
        let diff = raw - prev
        if (diff > 180) diff -= 360
        if (diff < -180) diff += 360
        smoothed = (prev + 0.5 * diff + 360) % 360
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

  // Сброс anchor и сглаживания при смене миссии — иначе куб «застрянет» с прошлого.
  useEffect(() => {
    anchoredBearingRef.current = null
    smoothedDistanceRef.current = null
    smoothedDeltaRef.current = null
    lastGoodPositionRef.current = null
  }, [mission?.id])

  // Вычислить delta и distance — с EMA-сглаживанием и accuracy gate.
  let deltaDeg: number | null = null
  let distanceM: number | null = null

  if (geoPosition && spawn) {
    // Accuracy gate: пока GPS шумит (±>30 м), не обновляем позицию.
    // Используем последнюю «хорошую» точку.
    const accuracyOk = geoPosition.accuracy <= 30
    let playerLat = geoPosition.lat
    let playerLng = geoPosition.lng

    if (accuracyOk) {
      lastGoodPositionRef.current = { lat: geoPosition.lat, lng: geoPosition.lng }
    } else if (lastGoodPositionRef.current) {
      playerLat = lastGoodPositionRef.current.lat
      playerLng = lastGoodPositionRef.current.lng
    }

    const bearing = calculateBearing(
      playerLat,
      playerLng,
      spawn.latitude,
      spawn.longitude,
    )
    const rawDistance = calculateDistanceM(
      playerLat,
      playerLng,
      spawn.latitude,
      spawn.longitude,
    )

    // EMA distance: 70% старая + 30% новая. Сглаживает GPS-шум.
    const prevDist = smoothedDistanceRef.current
    const smoothedDist =
      prevDist === null ? rawDistance : prevDist * 0.7 + rawDistance * 0.3
    smoothedDistanceRef.current = smoothedDist
    distanceM = smoothedDist

    // ANCHOR: при первом входе в зону (или очень близко) фиксируем направление
    // на цель. Дальше bearing не пересчитывается — куб не дрожит от GPS.
    // Порог: максимум из zone_radius или 40 м (чтобы у маленьких зон был запас).
    const zoneRadius = spawn.zoneRadiusMeters ?? 50
    const anchorRange = Math.max(zoneRadius, 40)

    if (smoothedDist <= anchorRange && anchoredBearingRef.current === null) {
      anchoredBearingRef.current = bearing
    }

    // Если anchor взят — используем его. Иначе — свежий bearing от GPS.
    const effectiveBearing = anchoredBearingRef.current ?? bearing

    if (heading !== null) {
      const rawDelta = ((effectiveBearing - heading + 540) % 360) - 180
      // EMA delta: 60% старая + 40% новая (быстрее следует за компасом).
      const prevDelta = smoothedDeltaRef.current
      const smoothedDelta =
        prevDelta === null
          ? rawDelta
          : prevDelta * 0.6 + rawDelta * 0.4
      smoothedDeltaRef.current = smoothedDelta
      deltaDeg = smoothedDelta
    }
  }

  // Позиция куба на экране в % по горизонтали.
  // delta = 0 → центр, delta = ±60° → край экрана.
  // Клэмпим в [-20, 120], чтобы куб мог немного уехать за край.
  const rawPosition =
    deltaDeg === null ? 50 : 50 + (deltaDeg / 120) * 100
  const leftPercent = Math.max(-20, Math.min(120, rawPosition))

  // Плавная интерполяция: 70 м → 0.3; 35 м → 1.15; 5 м → 1.95; 0 м → 2.0 (clamp).
  const scale =
    distanceM === null
      ? 1
      : Math.max(
          0.3,
          Math.min(2, (VISIBLE_RANGE_M - distanceM) / 40 + 0.3),
        )

  const isNear = distanceM !== null && distanceM <= VISIBLE_RANGE_M
  const isCentered = deltaDeg !== null && Math.abs(deltaDeg) < 15

  // Тап по кубу открывает мини-игру cipher (только для миссий типа cipher).
  const handleCubeTap = () => {
    if (!isNear || !isCentered) return
    if (!mission || mission.missionType !== 'cipher') return
    onScreenChange('cipher')
  }

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

        {mission?.deadlineAt && (
          <div className="camera-timer-wrapper">
            <MissionTimer
              deadlineAt={mission.deadlineAt}
              onClick={() => void onExpireMission(mission.id)}
            />
          </div>
        )}

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
            className={`ar-cube-world${isCentered ? ' is-centered' : ''}${
              isNear && isCentered && mission?.missionType === 'cipher'
                ? ' is-tappable'
                : ''
            }`}
            onClick={handleCubeTap}
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
