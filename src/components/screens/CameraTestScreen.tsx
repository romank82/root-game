// TEMP: dev-only camera test screen — удалить в Sprint 8.6.g.
// Цель: проверить getUserMedia + CSS-3D куб поверх видео (прототип AR-объекта).
// Если камера/куб не запускаются — пересматриваем концепцию AR.

import { useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { getMissionQrPayload } from '../../api/engineApi'
import jsQR from 'jsqr'

export function CameraTestScreen() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
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
  const [mode, setMode] = useState<'cube' | 'scan'>('cube')
  const [scanResult, setScanResult] = useState<string | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)

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

  function scanFrame() {
    const video = videoRef.current
    if (!video || video.readyState !== video.HAVE_ENOUGH_DATA) return

    let canvas = canvasRef.current
    if (!canvas) {
      canvas = document.createElement('canvas')
      canvasRef.current = canvas
    }
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight

    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const code = jsQR(imageData.data, imageData.width, imageData.height, {
      inversionAttempts: 'dontInvert',
    })

    if (code && code.data) {
      setScanResult(code.data)
      setScanError(null)
    }
  }

  useEffect(() => {
    if (mode !== 'scan' || status !== 'ok') return
    const interval = setInterval(scanFrame, 250)
    return () => clearInterval(interval)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, status])

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

        {/* Переключатель режима: куб / сканер (dev) */}
        <div className="camera-mode-switch">
          <button
            className={mode === 'cube' ? 'active' : ''}
            onClick={() => { setMode('cube'); setScanResult(null); setScanError(null) }}
          >
            Куб
          </button>
          <button
            className={mode === 'scan' ? 'active' : ''}
            onClick={() => { setMode('scan'); setScanResult(null); setScanError(null) }}
          >
            Сканер
          </button>
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
          {qrPayload && (
            <p className="qr-debug-line">
              len: {qrPayload.payload.length + qrPayload.hmac.length + 1}
            </p>
          )}
          {qrError && <p className="qr-debug-error">{qrError}</p>}
          <button className="qr-debug-button" onClick={() => void refreshQr()} disabled={qrLoading}>
            Обновить QR
          </button>
        </div>

        {/* CSS-3D куб — прототип AR-объекта */}
        {status === 'ok' && mode === 'cube' && (
          <>
            <div className="ar-cube-stage">
              <div className="ar-cube-3d">
                <div className="ar-cube-3d-face ar-cube-3d-front">
                  {qrPayload ? (
                    <QRCodeSVG
                      value={`${qrPayload.payload}.${qrPayload.hmac}`}
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
                      value={`${qrPayload.payload}.${qrPayload.hmac}`}
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

        {mode === 'scan' && status === 'ok' && (
          <div className="scan-result-overlay">
            <p className="scan-result-title">РЕЗУЛЬТАТ СКАНИРОВАНИЯ</p>
            {scanResult ? (
              <>
                <p className="scan-result-value">{scanResult.slice(0, 80)}{scanResult.length > 80 ? '…' : ''}</p>
                <p className="scan-result-meta">len: {scanResult.length}</p>
                <p className="scan-result-meta">
                  содержит точку: {scanResult.includes('.') ? 'да' : 'нет'}
                </p>
              </>
            ) : (
              <p className="scan-result-value">наведите на QR…</p>
            )}
            {scanError && <p className="scan-result-error">{scanError}</p>}
          </div>
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
