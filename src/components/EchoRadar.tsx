import { useEffect, useRef, useState } from 'react'

interface EchoRadarProps {
  playerLat: number
  playerLng: number
  playerAccuracy: number
  targetLat: number
  targetLng: number
  // Опционально: подпись под радаром.
  hint?: string
}

// Радиусы концентрических кругов (в метрах).
// Внешний круг = зона внимания, средний = размер зоны, внутренний = близко.
const RADIUS_RINGS_M = [30, 50, 70] as const
const MAX_DISTANCE_M = 70

// Радиус радара на экране (в пикселях).
const RADAR_SIZE_PX = 220
const RADAR_CENTER_PX = RADAR_SIZE_PX / 2
const RADAR_RADIUS_PX = RADAR_CENTER_PX - 10

function toRadians(deg: number): number {
  return (deg * Math.PI) / 180
}

function toDegrees(rad: number): number {
  return (rad * 180) / Math.PI
}

/**
 * Bearing от точки A к точке B (угол по компасу: 0° = север, 90° = восток).
 * Использует формулу great-circle.
 */
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

  const θ = Math.atan2(y, x)
  return (toDegrees(θ) + 360) % 360
}

/**
 * Haversine-расстояние между двумя точками (в метрах).
 */
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

export function EchoRadar({
  playerLat,
  playerLng,
  playerAccuracy,
  targetLat,
  targetLng,
  hint,
}: EchoRadarProps) {
  const [heading, setHeading] = useState<number | null>(null)
  const [compassError, setCompassError] = useState<string | null>(null)

  const lastUpdateRef = useRef<number>(0)
  const lastAbsoluteAtRef = useRef<number>(0)
  const lastRawHeadingRef = useRef<number | null>(null)
  const jumpCounterRef = useRef<number>(0)
  const smoothedHeadingRef = useRef<number | null>(null)

  useEffect(() => {
    function onOrientation(event: DeviceOrientationEvent) {
      const alpha = event.alpha
      if (alpha === null || alpha === undefined) return

      const now = Date.now()

      // Определяем источник события.
      // deviceorientationabsolute — всегда абсолютный.
      // deviceorientation имеет флаг absolute.
      const isAbsolute =
        event.type === 'deviceorientationabsolute' ||
        (event as DeviceOrientationEvent).absolute === true

      if (isAbsolute) {
        lastAbsoluteAtRef.current = now
      } else {
        // Если абсолютный компас работал в последние 2 сек — игнорируем относительный.
        if (now - lastAbsoluteAtRef.current < 2000) return
      }

      // Throttle.
      if (now - lastUpdateRef.current < 50) return
      lastUpdateRef.current = now

      let raw: number
      const webkit = (event as DeviceOrientationEvent & {
        webkitCompassHeading?: number
      }).webkitCompassHeading

      if (typeof webkit === 'number') {
        raw = webkit
      } else if (isAbsolute) {
        // Абсолютный alpha идёт ПРОТИВ часовой: 0=С, 90=З, 180=Ю, 270=В.
        const normalized = ((alpha % 360) + 360) % 360
        raw = (360 - normalized) % 360
      } else {
        // Относительный — не привязан к северу. Но раз absolute не работает,
        // используем как есть (хоть что-то).
        raw = ((alpha % 360) + 360) % 360
      }

      // Jump filter: если скачок > 90° за один тик — глитч, игнорируем.
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

      // EMA 0.3.
      const prev = smoothedHeadingRef.current
      let smoothed: number
      if (prev === null) {
        smoothed = raw
      } else {
        let diff = raw - prev
        if (diff > 180) diff -= 360
        if (diff < -180) diff += 360
        smoothed = (prev + 0.3 * diff + 360) % 360
      }
      smoothedHeadingRef.current = smoothed
      setHeading(smoothed)
    }

    if (typeof DeviceOrientationEvent === 'undefined') {
      setCompassError('Компас недоступен.')
      return
    }

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

  const distanceM = calculateDistanceM(playerLat, playerLng, targetLat, targetLng)
  const bearingDeg = calculateBearing(playerLat, playerLng, targetLat, targetLng)

  // Угол между направлением камеры (heading) и целевым направлением (bearing).
  // 0° — цель прямо по курсу. Положительный — цель справа.
  const deltaDeg = heading === null ? 0 : ((bearingDeg - heading + 540) % 360) - 180

  // Нормализованное расстояние до края радара.
  const distanceRatio = Math.min(distanceM / MAX_DISTANCE_M, 1)
  const dotRadiusPx = distanceRatio * RADAR_RADIUS_PX

  // Позиция точки на радаре. Верх радара = heading камеры.
  // deltaDeg = 0 → точка сверху; deltaDeg = 90 → точка справа.
  const dotAngleRad = toRadians(deltaDeg - 90)
  const dotX = RADAR_CENTER_PX + dotRadiusPx * Math.cos(dotAngleRad)
  const dotY = RADAR_CENTER_PX + dotRadiusPx * Math.sin(dotAngleRad)

  return (
    <section className="echo-radar">
      <p className="echo-radar-title">ЭХОЛОКАЦИЯ · КУРС ВВЕРХ</p>

      <svg
        className="echo-radar-svg"
        viewBox={`0 0 ${RADAR_SIZE_PX} ${RADAR_SIZE_PX}`}
        width="100%"
        height="100%"
      >
        {/* Концентрические круги 30/50/70 */}
        {RADIUS_RINGS_M.map((radiusM) => {
          const rPx = (radiusM / MAX_DISTANCE_M) * RADAR_RADIUS_PX
          return (
            <circle
              key={radiusM}
              cx={RADAR_CENTER_PX}
              cy={RADAR_CENTER_PX}
              r={rPx}
              fill="none"
              stroke="#00ff88"
              strokeOpacity={0.4}
              strokeWidth={1}
            />
          )
        })}

        {/* Перекрестие */}
        <line
          x1={RADAR_CENTER_PX}
          y1={10}
          x2={RADAR_CENTER_PX}
          y2={RADAR_SIZE_PX - 10}
          stroke="#00ff88"
          strokeOpacity={0.2}
          strokeWidth={1}
        />
        <line
          x1={10}
          y1={RADAR_CENTER_PX}
          x2={RADAR_SIZE_PX - 10}
          y2={RADAR_CENTER_PX}
          stroke="#00ff88"
          strokeOpacity={0.2}
          strokeWidth={1}
        />

        {/* Подписи кругов */}
        <text
          x={RADAR_CENTER_PX}
          y={RADAR_CENTER_PX - (RADIUS_RINGS_M[0] / MAX_DISTANCE_M) * RADAR_RADIUS_PX + 12}
          fill="#00ff88"
          fontSize="9"
          textAnchor="middle"
          opacity={0.6}
        >
          30м
        </text>
        <text
          x={RADAR_CENTER_PX}
          y={RADAR_CENTER_PX - (RADIUS_RINGS_M[1] / MAX_DISTANCE_M) * RADAR_RADIUS_PX + 12}
          fill="#00ff88"
          fontSize="9"
          textAnchor="middle"
          opacity={0.6}
        >
          50м
        </text>
        <text
          x={RADAR_CENTER_PX}
          y={RADAR_CENTER_PX - (RADIUS_RINGS_M[2] / MAX_DISTANCE_M) * RADAR_RADIUS_PX + 12}
          fill="#00ff88"
          fontSize="9"
          textAnchor="middle"
          opacity={0.6}
        >
          70м
        </text>

        {/* Точка игрока в центре */}
        <circle
          cx={RADAR_CENTER_PX}
          cy={RADAR_CENTER_PX}
          r={5}
          fill="#00ff88"
        />

        {/* Цель БЛИЗКО (≤70 м) — залитая точка как сейчас */}
        {distanceM <= MAX_DISTANCE_M && (
          <circle
            cx={dotX}
            cy={dotY}
            r={7}
            fill="#ffcc00"
            stroke="#000"
            strokeWidth={1}
            style={{ transition: 'cx 0.2s linear, cy 0.2s linear' }}
          />
        )}

        {/* Цель ДАЛЕКО (>70 м) — стрелка на границе радара */}
        {distanceM > MAX_DISTANCE_M && (
          <g
            transform={`translate(${dotX}, ${dotY}) rotate(${(dotAngleRad * 180) / Math.PI})`}
            style={{ transition: 'transform 0.2s linear' }}
          >
            {/* Треугольник указывает ВПРАВО в локальных координатах.
                rotate(dotAngleRad) поворачивает его в нужную сторону. */}
            <polygon
              points="-9,-8 -9,8 11,0"
              fill="#ffcc00"
              stroke="#000"
              strokeWidth={1}
            />
          </g>
        )}
      </svg>

      <div className="echo-radar-info">
        <p className="echo-radar-line">
          РАССТОЯНИЕ: {Math.round(distanceM)} м
        </p>
        {distanceM > MAX_DISTANCE_M && (
          <p className="echo-radar-line echo-radar-far">
            Цель далеко — идите по стрелке
          </p>
        )}
        <p className="echo-radar-line">
          ТОЧНОСТЬ: ±{Math.round(playerAccuracy)} м
        </p>
        {playerAccuracy > 100 && (
          <p className="echo-radar-line echo-radar-warning">
            GPS пока неточный, подождите 10-20 сек или выйдите на открытое место.
          </p>
        )}
        {heading !== null && (
          <p className="echo-radar-line echo-radar-debug">
            heading: {heading.toFixed(1)}° · bearing: {bearingDeg.toFixed(1)}° · delta: {deltaDeg.toFixed(1)}°
          </p>
        )}
        <p className="echo-radar-line">
          НАПРАВЛЕНИЕ:{' '}
          {heading === null
            ? 'компас...'
            : Math.abs(deltaDeg) < 15
              ? 'ПРЯМО'
              : deltaDeg > 0
                ? `↻ ${Math.round(deltaDeg)}°`
                : `↺ ${Math.round(Math.abs(deltaDeg))}°`}
        </p>
        {compassError && (
          <p className="echo-radar-line echo-radar-error">{compassError}</p>
        )}
        {hint && <p className="echo-radar-hint">{hint}</p>}
      </div>
    </section>
  )
}