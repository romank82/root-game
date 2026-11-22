import { useEffect, useRef } from 'react'

/**
 * Hologram3D — голографическая сцена CHIMERA на canvas 2D.
 * Чистый React + Canvas, без внешних зависимостей.
 *
 * Что рисует:
 *  - внешний двойной шестиугольник с засечками по вершинам;
 *  - центральное 3D-ядро (октаэдр) с вращением и пульсацией;
 *  - электроразряды из засечек в углы ядра (каждой засечке — свой угол);
 *  - фоновую радиально-круговую сетку.
 *
 * Управление не нужно: время идёт само. Анимация останавливается,
 * когда компонент не виден (вкладка в фоне / элемент вне экрана).
 */

type Vec3 = [number, number, number]
type Rgb = { r: number; g: number; b: number }
type Segment = [Vec3, Vec3]

// ─────────────────────────────────────────────
//  STYLE PARAMETERS (правь здесь под свой дизайн)
// ─────────────────────────────────────────────
const BG: Rgb = { r: 4, g: 10, b: 8 }
const NEON: Rgb = { r: 110, g: 255, b: 170 }
const NEON_HOT: Rgb = { r: 180, g: 255, b: 210 }
const CORE_COLOR: Rgb = { r: 200, g: 255, b: 220 }
const FOCAL = 3.0
const R = 1.0

const OUTER_TILT = 0.45
const TILT_SPEED = 0.7
const PULSE_FREQ = 3.5
const PULSE_AMP = 0.3

const CORE_R = 0.27
const NOTCH_LEN = 0.1

// ─────────────────────────────────────────────
//  3D MATH
// ─────────────────────────────────────────────
function rot(p: Vec3, rx: number, rz: number): Vec3 {
  const [x, y, z] = p
  const cy = Math.cos(rx), sy = Math.sin(rx)
  const y1 = cy * y - sy * z
  const z1 = sy * y + cy * z
  const cz = Math.cos(rz), sz = Math.sin(rz)
  return [cz * x - sz * y1, sz * x + cz * y1, z1]
}

function rotY(p: Vec3, ry: number): Vec3 {
  const [x, y, z] = p
  const c = Math.cos(ry), s = Math.sin(ry)
  return [c * x + s * z, y, -s * x + c * z]
}

function P(r: number, deg: number): Vec3 {
  const a = (deg * Math.PI) / 180
  return [r * Math.cos(a), r * Math.sin(a), 0]
}

function hash(n: number): number {
  const x = Math.sin(n * 127.1) * 43758.5453
  return x - Math.floor(x)
}

// ─────────────────────────────────────────────
//  GEOMETRY
// ─────────────────────────────────────────────
function buildGeometry(): Segment[] {
  const outer: Segment[] = []
  for (const rad of [R, R * 0.86]) {
    const pts: Vec3[] = []
    for (let i = 0; i < 6; i++) pts.push(P(rad, 90 + 60 * i))
    for (let i = 0; i < 6; i++) outer.push([pts[i], pts[(i + 1) % 6]])
  }
  // засечки: от каждой вершины внутрь
  for (let i = 0; i < 6; i++) {
    const v = P(R, 90 + 60 * i)
    const len = Math.hypot(v[0], v[1]) || 1
    outer.push([v, [v[0] - (v[0] / len) * NOTCH_LEN, v[1] - (v[1] / len) * NOTCH_LEN, 0]])
  }
  return outer
}

// рёбра октаэдра: каждая вершина соединяется со всеми, кроме противоположной
const CORE_AXES: Vec3[] = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]
const CORE_EDGES: Array<[number, number]> = []
for (let i = 0; i < CORE_AXES.length; i++) {
  for (let j = i + 1; j < CORE_AXES.length; j++) {
    if (i >> 1 === j >> 1) continue // противоположные вершины
    CORE_EDGES.push([i, j])
  }
}

// ─────────────────────────────────────────────
//  GLOW SPRITE (один раз на модуль)
// ─────────────────────────────────────────────
function makeGlowSprite(size: number, color: Rgb, sharp = 3.0, plateau = 0.0): HTMLCanvasElement {
  const c = document.createElement('canvas')
  c.width = size
  c.height = size
  const g2 = c.getContext('2d')!
  const imageData = g2.createImageData(size, size)
  const data = imageData.data
  const half = (size - 1) / 2
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - half) / half
      const dy = (y - half) / half
      const d = Math.sqrt(dx * dx + dy * dy)
      let g = Math.exp(-((d * sharp) ** 2))
      if (plateau > 0) {
        const p = Math.max(0, Math.min(1, 1 - d / plateau))
        g = Math.max(g, p ** 1.5)
      }
      const idx = (y * size + x) * 4
      data[idx] = Math.round(color.r * g)
      data[idx + 1] = Math.round(color.g * g)
      data[idx + 2] = Math.round(color.b * g)
      data[idx + 3] = Math.round(g * 255)
    }
  }
  g2.putImageData(imageData, 0, 0)
  return c
}

let sprites: {
  halo: HTMLCanvasElement
  hot: HTMLCanvasElement
  core: HTMLCanvasElement
} | null = null

function getSprites() {
  if (!sprites) {
    sprites = {
      halo: makeGlowSprite(128, NEON, 2.4, 0),
      hot: makeGlowSprite(96, NEON_HOT, 3.6, 0.22),
      core: makeGlowSprite(64, CORE_COLOR, 5.0, 0.35),
    }
  }
  return sprites
}

const GEOMETRY = buildGeometry()

// ─────────────────────────────────────────────
//  PROPS
// ─────────────────────────────────────────────
export type Hologram3DProps = {
  /** класс-обёртка; по умолчанию растягивается на родителя */
  className?: string
  /** рисовать фон сцены (градиент). Выключи, если нужен прозрачный canvas */
  background?: boolean
  /** рисовать фоновую радиально-круговую сетку */
  grid?: boolean
  /** множитель скорости анимации (1 = как в демо) */
  speed?: number
  /** пауза без размонтирования */
  paused?: boolean
}

export default function Hologram3D({
  className,
  background = true,
  grid = true,
  speed = 1,
  paused = false,
}: Hologram3DProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  // параметры через ref: их изменение не должно перезапускать анимацию
  const opts = useRef({ background, grid, speed, paused })
  useEffect(() => {
    opts.current = { background, grid, speed, paused }
  }, [background, grid, speed, paused])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { halo, hot, core } = getSprites()

    let W = 0
    let H = 0
    let dpr = 1
    let raf = 0
    let running = true
    let time = 0
    let last = 0
    let visible = true

    // ── helpers ───────────────────────────────
    const project = (p: Vec3): Vec3 => {
      const f = FOCAL / (FOCAL - p[2])
      return [p[0] * f, p[1] * f, p[2]]
    }

    const depthAlpha = (z: number) => 0.22 + 0.78 * Math.max(0, Math.min(1, (z + 1) / 2))

    const stroke3 = (a: Vec3, b: Vec3, width: number, alpha: number) => {
      const A = project(a)
      const B = project(b)
      ctx.globalAlpha = alpha
      ctx.lineWidth = width
      ctx.beginPath()
      ctx.moveTo(A[0], A[1])
      ctx.lineTo(B[0], B[1])
      ctx.stroke()
    }

    const glow = (sprite: HTMLCanvasElement, x: number, y: number, size: number, alpha: number) => {
      ctx.globalAlpha = alpha
      ctx.drawImage(sprite, x - size / 2, y - size / 2, size, size)
    }

    const strokePath = (pts: Array<[number, number]>, width: number, alpha: number, color: string) => {
      ctx.strokeStyle = color
      ctx.lineWidth = width
      ctx.globalAlpha = alpha
      ctx.beginPath()
      ctx.moveTo(pts[0][0], pts[0][1])
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1])
      ctx.stroke()
      ctx.globalAlpha = 1
    }

    const boltPath = (
      a: [number, number],
      b: [number, number],
      seed: number,
      amp: number,
    ): Array<[number, number]> => {
      const pts: Array<[number, number]> = [a]
      const segs = 12
      const dx = b[0] - a[0]
      const dy = b[1] - a[1]
      const len = Math.hypot(dx, dy) || 1
      const nx = -dy / len
      const ny = dx / len
      for (let i = 1; i < segs; i++) {
        const f = i / segs
        // затухание к цели: разряд входит в угол точно
        const taper = Math.pow(Math.sin(Math.PI * f), 1.5) * (1 - Math.pow(f, 6))
        const off = (hash(seed + i * 3.7) - 0.5) * 2 * amp * taper
        pts.push([a[0] + dx * f + nx * off, a[1] + dy * f + ny * off])
      }
      pts.push(b)
      return pts
    }

    // ── resize ────────────────────────────────
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      W = canvas.clientWidth
      H = canvas.clientHeight
      canvas.width = Math.max(1, Math.round(W * dpr))
      canvas.height = Math.max(1, Math.round(H * dpr))
    }
    resize()

    const ro = new ResizeObserver(resize)
    ro.observe(canvas)

    // ── background ────────────────────────────
    const drawBackground = () => {
      if (!opts.current.background) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
        ctx.clearRect(0, 0, W, H)
        return
      }
      const g = ctx.createRadialGradient(W / 2, H * 0.46, 0, W / 2, H * 0.46, Math.max(W, H) * 0.75)
      g.addColorStop(0, `rgba(${BG.r + 6},${BG.g + 22},${BG.b + 16},1)`)
      g.addColorStop(1, `rgba(${BG.r},${BG.g},${BG.b},1)`)
      ctx.globalAlpha = 1
      ctx.fillStyle = g
      ctx.fillRect(0, 0, W, H)
    }

    const drawGrid = (cx: number, cy: number, s: number) => {
      if (!opts.current.grid) return
      ctx.save()
      ctx.translate(cx, cy)
      ctx.scale(s, s)
      ctx.strokeStyle = `rgba(${NEON.r},${NEON.g},${NEON.b},1)`
      ctx.setLineDash([0.018, 0.03])
      ctx.lineWidth = 0.0035
      for (const rad of [0.62, 0.94, 1.26, 1.55]) {
        ctx.globalAlpha = 0.13
        ctx.beginPath()
        ctx.arc(0, 0, rad, 0, Math.PI * 2)
        ctx.stroke()
      }
      ctx.setLineDash([])
      ctx.globalAlpha = 0.09
      ctx.lineWidth = 0.003
      for (let i = 0; i < 12; i++) {
        const a = (i * Math.PI) / 6
        ctx.beginPath()
        ctx.moveTo(Math.cos(a) * 0.35, Math.sin(a) * 0.35)
        ctx.lineTo(Math.cos(a) * 1.55, Math.sin(a) * 1.55)
        ctx.stroke()
      }
      ctx.globalAlpha = 1
      ctx.restore()
    }

    // ── разряды из засечек в углы ядра ────────
    const drawBolts = (
      t: number,
      tiltOuter: number,
      spinOuter: number,
      pulse: number,
      corePts: Vec3[],
    ) => {
      const corners = corePts.filter((p) => p && Number.isFinite(p[0]))
      if (corners.length < 6) return

      // стартовые точки: внутренние концы засечек
      const starts: Vec3[] = []
      for (let i = 0; i < 6; i++) {
        const v = P(R, 90 + 60 * i)
        const len = Math.hypot(v[0], v[1]) || 1
        const tip: Vec3 = [v[0] - (v[0] / len) * NOTCH_LEN, v[1] - (v[1] / len) * NOTCH_LEN, 0]
        starts.push(project(rot(tip, tiltOuter, spinOuter)))
      }

      // каждой засечке — свой угол (минимум суммарной разницы углов)
      const startAng = starts.map((p) => Math.atan2(p[1], p[0]))
      const cornerAng = corners.map((c) => Math.atan2(c[1], c[0]))
      const angDiff = (a: number, b: number) => {
        const d = Math.abs(a - b) % (Math.PI * 2)
        return d > Math.PI ? Math.PI * 2 - d : d
      }
      let bestPerm = [0, 1, 2, 3, 4, 5]
      let bestCost = Infinity
      const perm = [0, 1, 2, 3, 4, 5]
      const permute = (k: number) => {
        if (k === 6) {
          let cost = 0
          for (let i = 0; i < 6; i++) cost += angDiff(startAng[i], cornerAng[perm[i]])
          if (cost < bestCost) {
            bestCost = cost
            bestPerm = perm.slice()
          }
          return
        }
        for (let i = k; i < 6; i++) {
          const tmp = perm[k]
          perm[k] = perm[i]
          perm[i] = tmp
          permute(k + 1)
          perm[i] = perm[k]
          perm[k] = tmp
        }
      }
      permute(0)

      for (let i = 0; i < 6; i++) {
        const fromA: [number, number] = [starts[i][0], starts[i][1]]
        const target = corners[bestPerm[i]]
        const fromB: [number, number] = [target[0], target[1]]

        // мерцание: дуга горит 86% цикла
        const cycle = 0.42 + hash(i * 9.31) * 0.5
        const phase = (t + hash(i * 4.77) * cycle) % cycle
        const duty = 0.86
        if (phase > duty) continue

        const env = Math.sin((phase / duty) * Math.PI)
        const seed = Math.floor(t * 24) * 13.37 + i * 101.7
        const amp = 0.075 * (0.55 + 0.45 * hash(seed))
        const pts = boltPath(fromA, fromB, seed, amp)

        strokePath(pts, 0.07, 0.1 * env, `rgba(${NEON.r},${NEON.g},${NEON.b},1)`)
        strokePath(pts, 0.032, 0.22 * env, `rgba(${NEON_HOT.r},${NEON_HOT.g},${NEON_HOT.b},1)`)
        strokePath(pts, 0.014, 0.45 * env, `rgba(${NEON_HOT.r},${NEON_HOT.g},${NEON_HOT.b},1)`)
        strokePath(
          pts,
          0.0075,
          (0.85 + 0.15 * hash(seed + 3.1)) * env,
          `rgba(${CORE_COLOR.r},${CORE_COLOR.g},${CORE_COLOR.b},1)`,
        )

        // ответвления-искры, тоже в тот же угол
        const branches = hash(seed + 7.9) > 0.25 ? 2 : 1
        for (let bIdx = 0; bIdx < branches; bIdx++) {
          const k = 2 + Math.floor(hash(seed + 1.3 + bIdx * 17) * 4)
          const from = pts[Math.min(k, pts.length - 2)]
          const branch = boltPath(from, fromB, seed + 55.5 + bIdx * 31, amp * 0.55)
          strokePath(branch, 0.009, 0.3 * env, `rgba(${NEON_HOT.r},${NEON_HOT.g},${NEON_HOT.b},1)`)
          strokePath(branch, 0.0045, 0.7 * env, `rgba(${CORE_COLOR.r},${CORE_COLOR.g},${CORE_COLOR.b},1)`)
        }

        // вспышки контакта
        glow(hot, fromA[0], fromA[1], 0.075 * pulse, 0.95 * env)
        glow(halo, fromA[0], fromA[1], 0.2 * pulse, 0.55 * env)
        glow(hot, fromB[0], fromB[1], 0.075, env)
        glow(halo, fromB[0], fromB[1], 0.16, 0.6 * env)
      }
    }

    // ── сцена ─────────────────────────────────
    const drawScene = (t: number) => {
      const tiltOuter = OUTER_TILT + 0.16 * Math.sin(t * TILT_SPEED)
      const spinOuter = t * 0.16
      const pulse = 1 + PULSE_AMP * Math.sin(t * PULSE_FREQ)

      // внешний шестиугольник + засечки
      const outerCol = `rgba(${NEON.r},${NEON.g},${NEON.b},1)`
      ctx.strokeStyle = outerCol
      for (const seg of GEOMETRY) {
        const a = rot(seg[0], tiltOuter, spinOuter)
        const b = rot(seg[1], tiltOuter, spinOuter)
        const z = (a[2] + b[2]) / 2
        ctx.globalAlpha = 0.2 * depthAlpha(z)
        stroke3(a, b, 0.026, 0.16 * depthAlpha(z))
        ctx.strokeStyle = outerCol
        stroke3(a, b, 0.008, 0.85 * depthAlpha(z))
        ctx.globalAlpha = 1
      }

      // ядро
      const coreVerts: Vec3[] = []
      for (let i = 0; i < 6; i++) {
        const ax = CORE_AXES[i]
        let v: Vec3 = [ax[0] * CORE_R * pulse, ax[1] * CORE_R * pulse, ax[2] * CORE_R * pulse]
        v = rotY(v, t * 0.75)
        v = rot(v, 0.55 + 0.22 * Math.sin(t * 0.5), t * 0.35)
        coreVerts.push(v)
      }
      const coreCol = `rgba(${CORE_COLOR.r},${CORE_COLOR.g},${CORE_COLOR.b},1)`
      ctx.strokeStyle = coreCol
      for (const [i, j] of CORE_EDGES) {
        const a = coreVerts[i]
        const b = coreVerts[j]
        const z = (a[2] + b[2]) / 2
        stroke3(a, b, 0.016, 0.14 * depthAlpha(z))
        ctx.strokeStyle = coreCol
        stroke3(a, b, 0.0045, 0.95 * depthAlpha(z))
      }

      // разряды
      drawBolts(t, tiltOuter, spinOuter, pulse, coreVerts.map(project))

      // свечение центра
      const c0 = project(coreVerts[4])
      glow(core, c0[0], c0[1], 0.42 * pulse, 0.55)
      glow(hot, c0[0], c0[1], 0.1 * pulse, 0.9)
    }

    // ── цикл ──────────────────────────────────
    const frame = (now: number) => {
      if (!running) return
      if (!last) last = now
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      if (!opts.current.paused) time += dt * opts.current.speed

      const t = time
      const s = Math.min(W, H) / 4.4
      const cx = W / 2
      const cy = H / 2

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      drawBackground()
      drawGrid(cx, cy, s)

      ctx.save()
      ctx.translate(cx, cy)
      ctx.scale(s, s)
      ctx.globalCompositeOperation = 'lighter'
      drawScene(t)
      ctx.globalCompositeOperation = 'source-over'
      ctx.restore()

      raf = requestAnimationFrame(frame)
    }

    const start = () => {
      if (raf || !running) return
      last = 0
      raf = requestAnimationFrame(frame)
    }
    const stop = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
    }

    const onVisibility = () => {
      if (document.hidden) stop()
      else if (visible) start()
    }
    document.addEventListener('visibilitychange', onVisibility)

    // экономим батарею: не рисуем, когда сцена вне экрана
    const io = new IntersectionObserver(
      (entries) => {
        visible = entries[0]?.isIntersecting ?? true
        if (visible && !document.hidden) start()
        else stop()
      },
      { threshold: 0 },
    )
    io.observe(canvas)

    start()

    return () => {
      running = false
      stop()
      ro.disconnect()
      io.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ display: 'block', width: '100%', height: '100%' }}
    />
  )
}
