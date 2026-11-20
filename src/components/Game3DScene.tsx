/**
 * 3D-композиция «золотое кольцо + ROOT» (react-three-fiber).
 *
 * Собрано кодом, без внешних .glb-моделей и без CDN-зависимостей:
 * - кольцо-«шайба»: THREE.Shape + ExtrudeGeometry (внешний радиус 1.5,
 *   внутренний 1.3, толщина 0.2, curveSegments 32 — вдвое меньше сегментов
 *   окружности, чем было (64), визуально почти неотличимо);
 * - <Text3D> из drei — объёмная надпись ROOT (шрифт public/models/root-font.json,
 *   сконвертирован локально из DejaVu Sans Bold через facetype-js). Фаска
 *   отключена (bevelEnabled=false), curveSegments=8 — минимально необходимая
 *   геометрия букв;
 * - окружение — <Environment> с Lightformer'ами: HDR-куб рендерится локально
 *   (CubeCamera), без файлов/HDRI с CDN. Это даёт металлике блики.
 *
 * Оптимизация рендера (телефон): dpr ограничен [1, 1.5] (на мобильных
 *   devicePixelRatio часто 2–3x — главный пожиратель GPU: с cap 1.5 кадр
 *   легче в разы, картинка чуть мягче); antialias отключён; теней нет;
 *   useFrame — один инкремент rotation.y без аллокаций и setState.
 */
import { Suspense, useMemo, useRef } from 'react'
import { Canvas, useFrame, useLoader } from '@react-three/fiber'
import { FontLoader } from 'three/examples/jsm/loaders/FontLoader.js'
import { Text3D, Environment, Lightformer } from '@react-three/drei'
import * as THREE from 'three'
import type { FontData } from '@react-three/drei'
import type { Group } from 'three'

/** Локальный typeface.json (из DejaVu Sans Bold), без CDN. */
const FONT_URL = '/models/root-font.json'

function GoldenComposition() {
  const groupRef = useRef<Group>(null)
  const font = useLoader(FontLoader, FONT_URL)

  // Плоское кольцо-«шайба»: внешний радиус 1.5, внутренний 1.3.
  // curveSegments 32 (было 64) — плавность окружности сохраняется,
  // а треугольников вдвое меньше (важно для телефона). */
  const { ringShape, extrudeSettings } = useMemo(() => {
    const shape = new THREE.Shape()
    shape.absarc(0, 0, 1.5, 0, Math.PI * 2, false)
    const hole = new THREE.Path()
    hole.absarc(0, 0, 1.3, 0, Math.PI * 2, true)
    shape.holes.push(hole)
    return {
      ringShape: shape,
      extrudeSettings: { depth: 0.2, bevelEnabled: false, curveSegments: 32 },
    }
  }, [])

  useFrame((_state, delta) => {
    if (!groupRef.current) return
    groupRef.current.rotation.y += delta * 0.4
  })

  return (
    <group ref={groupRef} rotation={[0.12, 0, 0]}>
      {/* Кольцо-шайба. ExtrudeGeometry идёт вдоль +Z от 0 до depth (0.2),
          поэтому mesh сдвинут на z = -0.1: толщина кольца центрирована
          по z = 0. */}
      <mesh position={[0, 0, -0.1]}>
        <extrudeGeometry args={[ringShape, extrudeSettings]} />
        <meshStandardMaterial color="#ffd700" metalness={0.9} roughness={0.1} />
      </mesh>

      {/* Объёмная надпись ROOT без фаски (bevelEnabled=false — дефолт drei,
          здесь прописан явно) и с curveSegments=8 (тоже дефолт) — минимум
          треугольников при сохранении формы букв. Ширина чернил ≈ 2.12 при
          size 0.5 — внутри внутреннего диаметра 2.6. Центрирование по bbox
          (посчитано по реальным глифам R/O/T): x = -1.125, y = -0.253. */}
      <Text3D
        font={font.data as unknown as FontData}
        position={[-1.125, -0.253, 0]}
        size={0.5}
        height={0.15}
        bevelEnabled={false}
        curveSegments={8}
      >
        ROOT
        <meshStandardMaterial color="#ffd700" metalness={0.9} roughness={0.1} />
      </Text3D>
    </group>
  )
}

export default function Game3DScene() {
  return (
    <Canvas
      camera={{ position: [0, 0.4, 5.2], fov: 55 }}
      dpr={[1, 1.5]}
      gl={{ antialias: false }}
      // offsetSize: замер layout-размера вместо getBoundingClientRect —
      // родитель .ar-cube-world масштабируется через transform: scale(),
      // иначе канвас больше бокса и сцена обрезается.
      resize={{ offsetSize: true }}
    >
      {/* Локальное окружение: куб-текстура из Lightformer'ов рендерится на
          клиенте (без HDRI/CDN) и даёт металлике яркие блики. */}
      <Environment resolution={256}>
        <Lightformer intensity={2} position={[0, 5, -5]} scale={10} />
        <Lightformer intensity={1} position={[5, 0, 5]} scale={10} />
        <Lightformer intensity={1} position={[-5, 0, 5]} scale={10} />
      </Environment>
      <ambientLight intensity={0.4} />
      <Suspense fallback={null}>
        <GoldenComposition />
      </Suspense>
    </Canvas>
  )
}
