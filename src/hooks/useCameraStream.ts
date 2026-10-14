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
    // Объявлен в теле эффекта, чтобы cleanup имел доступ.
    let timeoutId: number | undefined

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

      // Таймаут: если getUserMedia не отвечает 10 секунд — считаем ошибкой.
      // В Telegram Android WebView автозапуск getUserMedia без пользовательского
      // жеста может висеть бесконечно (промис не resolve и не reject).
      let timedOut = false
      timeoutId = window.setTimeout(() => {
        timedOut = true
        if (cancelled) return
        setError('Камера не отвечает. Нажмите кнопку ещё раз или перезагрузите Mini App.')
        setStatus('error')
      }, 10_000)

      try {
        // Только задняя камера — в AR нужна она.
        const newStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' } },
          audio: false,
        })
        window.clearTimeout(timeoutId)
        if (cancelled || timedOut) {
          newStream.getTracks().forEach((t) => t.stop())
          return
        }
        cachedStream = newStream
        setStream(newStream)
        setStatus('ready')
      } catch (err) {
        window.clearTimeout(timeoutId)
        if (cancelled || timedOut) return
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
      window.clearTimeout(timeoutId)
    }
  }, [])

  return { stream, status, error }
}
