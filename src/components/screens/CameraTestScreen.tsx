// TEMP: dev-only camera test screen — удалить в Sprint 8.6.g.
// Цель: проверить getUserMedia + CSS-3D куб поверх видео (прототип AR-объекта).
// Если камера/куб не запускаются — пересматриваем концепцию AR.

import { useEffect, useRef, useState } from 'react'

export function CameraTestScreen() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [status, setStatus] = useState<'idle' | 'starting' | 'ok' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment')
  const [heading, setHeading] = useState<number | null>(null)
  const [compassStatus, setCompassStatus] = useState<'idle' | 'requested' | 'ok' | 'denied' | 'unsupported'>('idle')
  const [compassError, setCompassError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setStatus('starting')
    setError(null)

    async function start() {
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          throw new Error('getUserMedia не поддерживается этим устройством.')
        }
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facingMode } },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => {})
        }
        setStatus('ok')
      } catch (err) {
        if (cancelled) return
        const message = err instanceof Error ? err.message : String(err)
        setError(message)
        setStatus('error')
      }
    }

    void start()

    return () => {
      cancelled = true
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop())
        streamRef.current = null
      }
    }
  }, [facingMode])

  function normalizeHeading(raw: number): number {
    // alpha в DeviceOrientation: 0..360, но отсчёт против часовой от севера.
    // Для «курс вверх» используем именно alpha как «куда смотрит верх телефона».
    const normalized = ((raw % 360) + 360) % 360
    return normalized
  }

  function handleDeviceOrientation(event: DeviceOrientationEvent) {
    const alpha = event.alpha
    if (alpha === null || alpha === undefined) return
    // webkitCompassHeading: iOS-специфичное поле, более точное.
    const webkit = (event as DeviceOrientationEvent & { webkitCompassHeading?: number }).webkitCompassHeading
    if (typeof webkit === 'number') {
      setHeading(webkit)
    } else {
      setHeading(normalizeHeading(alpha))
    }
    setCompassStatus('ok')
  }

  async function requestCompass() {
    setCompassError(null)

    // Сначала проверяем существование глобала — иначе обращение к нему
    // упадёт с ReferenceError на некоторых WebView.
    if (typeof DeviceOrientationEvent === 'undefined') {
      setCompassStatus('unsupported')
      setCompassError('DeviceOrientationEvent не поддерживается.')
      return
    }

    // iOS 13+ требует явное разрешение
    const anyEvent = DeviceOrientationEvent as unknown as {
      requestPermission?: () => Promise<'granted' | 'denied'>
    }
    if (typeof anyEvent.requestPermission === 'function') {
      try {
        const result = await anyEvent.requestPermission()
        if (result !== 'granted') {
          setCompassStatus('denied')
          setCompassError('Пользователь запретил доступ к компасу.')
          return
        }
      } catch (err) {
        setCompassStatus('denied')
        setCompassError(err instanceof Error ? err.message : 'Ошибка запроса компаса.')
        return
      }
    }

    setCompassStatus('requested')
  }

  useEffect(() => {
    if (compassStatus === 'requested' || compassStatus === 'ok') {
      window.addEventListener('deviceorientationabsolute', handleDeviceOrientation as EventListener, true)
      window.addEventListener('deviceorientation', handleDeviceOrientation as EventListener, true)
    }
    return () => {
      window.removeEventListener('deviceorientationabsolute', handleDeviceOrientation as EventListener, true)
      window.removeEventListener('deviceorientation', handleDeviceOrientation as EventListener, true)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compassStatus])

  function switchCamera() {
    setFacingMode((prev) => (prev === 'environment' ? 'user' : 'environment'))
  }

  return (
    <section className="camera-test-screen">
      <div className="camera-test-video-wrapper">
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          className="camera-test-video"
        />

        {/* Компас-heading overlay (dev) */}
        <div className="compass-debug-overlay">
          <p className="compass-debug-line">heading: {heading === null ? '—' : `${heading.toFixed(1)}°`}</p>
          <p className="compass-debug-line">compass: {compassStatus}</p>
          {compassError && <p className="compass-debug-error">{compassError}</p>}
          {compassStatus !== 'ok' && (
            <button className="compass-debug-button" onClick={() => void requestCompass()}>
              Запросить компас
            </button>
          )}
        </div>

        {/* CSS-3D куб — прототип AR-объекта */}
        {status === 'ok' && (
          <>
            <div className="ar-cube-stage">
              <div className="ar-cube-3d">
                <div className="ar-cube-3d-face ar-cube-3d-front" />
                <div className="ar-cube-3d-face ar-cube-3d-back" />
                <div className="ar-cube-3d-face ar-cube-3d-right" />
                <div className="ar-cube-3d-face ar-cube-3d-left" />
                <div className="ar-cube-3d-face ar-cube-3d-top" />
                <div className="ar-cube-3d-face ar-cube-3d-bottom" />
              </div>
            </div>

            {/* Reticle (прицел) в центре — как в AR-приложениях */}
            <div className="ar-reticle-test">
              <span className="ar-reticle-test-cross">+</span>
            </div>

            {/* Подпись снизу — что здесь появится AR-объект */}
            <div className="ar-test-hint">
              Прототип AR-объекта (dev)
            </div>
          </>
        )}

        {status === 'starting' && (
          <div className="camera-test-overlay">Запуск камеры…</div>
        )}
        {status === 'error' && (
          <div className="camera-test-overlay camera-test-overlay-error">
            Ошибка: {error}
          </div>
        )}
      </div>
      <div className="camera-test-controls">
        <p className="camera-test-status">
          status: {status}
          {error && ` — ${error}`}
        </p>
        <button onClick={switchCamera} disabled={status === 'starting'}>
          Переключить камеру ({facingMode})
        </button>
      </div>
    </section>
  )
}
