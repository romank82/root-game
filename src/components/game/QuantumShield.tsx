/**
 * Квантовый щит — объёмная 3D-отрисовка нового типа AR-объекта.
 *
 * Собрано кодом, без внешних .glb-моделей и CDN-зависимостей:
 * - центральное ядро — сфера с emissive-свечением (зелёный);
 * - 2 кольца (TorusGeometry) под разными углами, вращаются вокруг ядра;
 * - 6 лучей (CylinderGeometry) от центра по осям +X/-X/+Y/-Y/+Z/-Z;
 * - Hexagon-рамка (EdgesGeometry + LineSegments) вокруг композиции;
 * - анимация (useFrame): вращение колец и пульсация свечения ядра.
 *
 * Оптимизация рендера (телефон): dpr ограничен [1, 1.5], antialias отключён,
 * теней нет; useFrame — один инкремент без аллокаций и setState.
 */
import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import type { Group, Mesh, MeshStandardMaterial } from 'three'

/** Радиусы колец (внутренний/внешний) и их наклоны вокруг осей X/Z. */
const RING_RADIUS = 1.6
const RING_TUBE = 0.06
const RING_TILT_X = Math.PI / 2.6
const RING_TILT_Z = Math.PI / 3.4

/** Длина лучей от центра (половина — вверх, половина — вниз по каждой оси). */
const RAY_LENGTH = 1.15
const RAY_RADIUS = 0.04

/** Вершины hexagon-рамки в плоскости XY (радиус 2.1). */
function hexagonVertices(radius: number): THREE.Vector3[] {
  const pts: THREE.Vector3[] = []
  for (let i = 0; i < 6; i += 1) {
    const angle = (Math.PI / 3) * i
    pts.push(new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0))
  }
  return pts
}

/** Зелёная эмиссивная материя для ядра (переиспользуется на всех лучах/рамке). */
function useEmissiveMaterial() {
  return useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#00ff88',
        emissive: '#00ff66',
        emissiveIntensity: 1.2,
        metalness: 0.3,
        roughness: 0.25,
      }),
    [],
  )
}

/** Ядро + кольца + лучи + рамка в одной группе с общей анимацией. */
function ShieldComposition() {
  const groupRef = useRef<Group>(null)
  const coreRef = useRef<Mesh>(null)
  const ringARef = useRef<Mesh>(null)
  const ringBRef = useRef<Mesh>(null)
  const coreMaterial = useEmissiveMaterial()

  // Кольца: torus (внутренний/внешний радиус + сечение трубы).
  const ringGeometry = useMemo(
    () => new THREE.TorusGeometry(RING_RADIUS, RING_TUBE, 16, 96),
    [],
  )
  const ringMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#22ffaa',
        emissive: '#00cc77',
        emissiveIntensity: 0.8,
        metalness: 0.4,
        roughness: 0.2,
      }),
    [],
  )

  // Лучи: 6 цилиндров по осям (половина в плюс, половина в минус).
  const rayGeometry = useMemo(
    () => new THREE.CylinderGeometry(RAY_RADIUS, RAY_RADIUS, RAY_LENGTH, 12),
    [],
  )

  // Hexagon-рамка: EdgesGeometry по Shape, LineSegments с LineBasicMaterial.
  const hexEdges = useMemo(() => {
    const shape = new THREE.Shape()
    const pts = hexagonVertices(2.1)
    shape.moveTo(pts[0].x, pts[0].y)
    for (let i = 1; i < pts.length; i += 1) shape.lineTo(pts[i].x, pts[i].y)
    shape.lineTo(pts[0].x, pts[0].y)
    return new THREE.EdgesGeometry(new THREE.ShapeGeometry(shape))
  }, [])

  const rayPositions = useMemo(
    () =>
      [
        [1, 0, 0],
        [-1, 0, 0],
        [0, 1, 0],
        [0, -1, 0],
        [0, 0, 1],
        [0, 0, -1],
      ].map(([x, y, z]) => new THREE.Vector3(x, y, z)),
    [],
  )

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime

    if (groupRef.current) {
      groupRef.current.rotation.y += delta * 0.25
    }
    if (ringARef.current) {
      ringARef.current.rotation.z += delta * 0.5
    }
    if (ringBRef.current) {
      ringBRef.current.rotation.x += delta * 0.4
      ringBRef.current.rotation.y += delta * 0.35
    }
    // Пульсация свечения ядра (мягкий синус, без setState/аллокаций).
    if (coreRef.current) {
      const mat = coreRef.current.material as MeshStandardMaterial
      mat.emissiveIntensity = 1.2 + Math.sin(t * 2.4) * 0.5
    }
  })

  return (
    <group ref={groupRef}>
      {/* Центральное ядро с эмиссивным свечением. */}
      <mesh ref={coreRef} material={coreMaterial}>
        <sphereGeometry args={[0.5, 32, 32]} />
      </mesh>

      {/* Кольца под разными углами. */}
      <mesh
        ref={ringARef}
        geometry={ringGeometry}
        material={ringMaterial}
        rotation={[RING_TILT_X, 0, 0]}
      />
      <mesh
        ref={ringBRef}
        geometry={ringGeometry}
        material={ringMaterial}
        rotation={[RING_TILT_Z, 0, RING_TILT_Z]}
      />

      {/* 6 лучей от центра. */}
      {rayPositions.map((pos, i) => {
        const isX = Math.abs(pos.x) === 1
        const isZ = Math.abs(pos.z) === 1
        // Цилиндр направлен по +Y; для осей X/Z поворачиваем его на 90°.
        const rotation = isX
          ? [0, 0, Math.PI / 2]
          : isZ
            ? [Math.PI / 2, 0, 0]
            : [0, 0, 0]
        return (
          <mesh
            key={i}
            geometry={rayGeometry}
            material={coreMaterial}
            position={pos}
            rotation={rotation as unknown as [number, number, number]}
          />
        )
      })}

      {/* Hexagon-рамка вокруг. */}
      <lineSegments geometry={hexEdges}>
        <lineBasicMaterial color="#00ffaa" transparent opacity={0.7} />
      </lineSegments>
    </group>
  )
}

export default function QuantumShield() {
  return (
    <Canvas
      camera={{ position: [0, 0.2, 5.4], fov: 55 }}
      dpr={[1, 1.5]}
      gl={{ antialias: false }}
      style={{ background: '#05070a' }}
    >
      <ambientLight intensity={0.5} />
      <pointLight position={[3, 3, 3]} intensity={40} color="#00ff88" />
      <pointLight position={[-3, -2, -3]} intensity={20} color="#00ccff" />
      <ShieldComposition />
    </Canvas>
  )
}
