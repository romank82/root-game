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
