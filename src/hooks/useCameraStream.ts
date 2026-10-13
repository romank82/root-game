import { useEffect, useState } from 'react'

type CameraStatus = 'idle' | 'starting' | 'ready' | 'error'

/**
 * Кэш MediaStream на уровне модуля — переживает unmount/remount компонента
 * и переключение экранов. Благодаря этому WebView не переспрашивает
 * разрешение при каждом входе в камеру.
 */
let cachedStream: MediaStream | null = null

/**
 * Освободить камеру полностью (например, при выходе из игры).
 */
export function releaseCameraStream() {
  if (cachedStream) {
    cachedStream.getTracks().forEach((t) => t.stop())
    cachedStream = null
  }
}

export function useCameraStream() {
  const [stream, setStream] = useState<MediaStream | null>(cachedStream)
  const [status, setStatus] = useState<CameraStatus>(cachedStream ? 'ready' : 'idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function init() {
      if (cachedStream && cachedStream.active) {
        setStream(cachedStream)
        setStatus('ready')
        return
      }

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setError('Камера не поддерживается устройством.')
        setStatus('error')
        return
      }

      setStatus('starting')
      setError(null)

      try {
        // Только задняя камера — в AR нужна она.
        const newStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' } },
          audio: false,
        })
        if (cancelled) {
          newStream.getTracks().forEach((t) => t.stop())
          return
        }
        cachedStream = newStream
        setStream(newStream)
        setStatus('ready')
      } catch (err) {
        if (cancelled) return
        const message = err instanceof Error ? err.message : 'Ошибка доступа к камере.'
        setError(message)
        setStatus('error')
      }
    }

    void init()

    // ВАЖНО: при unmount НЕ закрываем stream — он в кэше.
    // Он закроется через releaseCameraStream() явным вызовом.
    return () => {
      cancelled = true
    }
  }, [])

  return { stream, status, error }
}
