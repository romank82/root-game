// TEMP: dev-only camera test screen — удалить в Sprint 8.6.g.
// Цель: проверить getUserMedia + CSS-3D куб поверх видео (прототип AR-объекта).
// Если камера/куб не запускаются — пересматриваем концепцию AR.

import { useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { getMissionQrPayload } from '../../api/engineApi'

export function CameraTestScreen() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [status, setStatus] = useState<'idle' | 'starting' | 'ok' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment')
  const [heading, setHeading] = useState<number | null>(null)
  const [compassStatus, setCompassStatus] = useState<'idle' | 'requested' | 'ok' | 'denied' | 'unsupported'>('idle')
  const [compassError, setCompassError] = useState<string | null>(null)

  // Захардкоженная миссия для dev-проверки. test-code-01 — in_progress.
  const DEV_MISSION_ID = 'mission-d36d8f9130944783bce7dc1d4dcd15c3'

  const [qrPayload, setQrPayload] = useState<{ payload: string; hmac: string; expiresAt: string } | null>(null)
  const [qrError, setQrError] = useState<string | null>(null)
  const [qrLoading, setQrLoading] = useState(false)

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

  async function refreshQr() {
    setQrLoading(true)
    setQrError(null)
    try {
      const data = await getMissionQrPayload(DEV_MISSION_ID)
      setQrPayload({
        payload: data.payload,
        hmac: data.hmac,
        expiresAt: data.expiresAt,
      })
    } catch (err) {
      setQrError(err instanceof Error ? err.message : 'Ошибка загрузки QR.')
    } finally {
      setQrLoading(false)
    }
  }

  useEffect(() => {
    if (status !== 'ok') return
    let cancelled = false

    async function initialLoad() {
      try {
        const data = await getMissionQrPayload(DEV_MISSION_ID)
        if (cancelled) return
        setQrPayload({
          payload: data.payload,
          hmac: data.hmac,
          expiresAt: data.expiresAt,
        })
      } catch (err) {
        if (cancelled) return
        setQrError(err instanceof Error ? err.message : 'Ошибка загрузки QR.')
      }
    }

    void initialLoad()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  // Автообновление за 60 секунд до истечения.
  useEffect(() => {
    if (!qrPayload) return
    const expiresAtMs = new Date(qrPayload.expiresAt).getTime()
    const nowMs = Date.now()
    const refreshIn = Math.max(expiresAtMs - nowMs - 60_000, 10_000)
    const timer = setTimeout(() => {
      void refreshQr()
    }, refreshIn)
    return () => clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qrPayload])

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

        {/* QR-дебаг (dev) */}
        <div className="qr-debug-overlay">
          <p className="qr-debug-line">
            QR: {qrLoading ? 'загрузка…' : qrPayload ? 'готов' : '—'}
          </p>
          {qrPayload && (
            <p className="qr-debug-line">
              exp: {new Date(qrPayload.expiresAt).toLocaleTimeString()}
            </p>
          )}
          {qrError && <p className="qr-debug-error">{qrError}</p>}
          <button className="qr-debug-button" onClick={() => void refreshQr()} disabled={qrLoading}>
            Обновить QR
          </button>
        </div>

        {/* CSS-3D куб — прототип AR-объекта */}
        {status === 'ok' && (
          <>
            <div className="ar-cube-stage">
              <div className="ar-cube-3d">
                <div className="ar-cube-3d-face ar-cube-3d-front">
                  {qrPayload ? (
                    <QRCodeSVG
                      value={qrPayload.payload}
                      size={120}
                      bgColor="#000000"
                      fgColor="#00ff88"
                      level="M"
                      style={{ width: '100%', height: '100%' }}
                    />
                  ) : null}
                </div>
                <div className="ar-cube-3d-face ar-cube-3d-back">
                  {qrPayload ? (
                    <QRCodeSVG
                      value={qrPayload.payload}
                      size={120}
                      bgColor="#000000"
                      fgColor="#00ff88"
                      level="M"
                      style={{ width: '100%', height: '100%' }}
                    />
                  ) : null}
                </div>
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
