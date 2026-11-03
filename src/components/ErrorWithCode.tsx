import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { getLastErrorCorrelationId } from '../api/engineApi'

type ErrorWithCodeProps = {
  message: string | null | undefined
  className?: string
  /** Инлайн-стиль для текста ошибки (для мест, где нет класса, напр. MissionModal). */
  style?: CSSProperties
  /** Показывать «Код для поддержки» только при серверных/сетевых ошибках. */
  showCodeOnlyForServer?: boolean
}

function isServerError(message: string): boolean {
  if (/^HTTP 5\d\d/.test(message)) return true
  if (/^HTTP 4\d\d/.test(message)) return false
  return /Сервер|Нет соединения|network|timeout/i.test(message)
}

/**
 * Sprint E-2: текст ошибки + «Код для поддержки» (correlation_id), если это
 * серверная/сетевая ошибка. Сам текст по-прежнему приходит строкой из
 * setError(err.message), поэтому 29 мест setError не меняются.
 */
export function ErrorWithCode({
  message,
  className,
  style,
  showCodeOnlyForServer = true,
}: ErrorWithCodeProps) {
  const { t } = useTranslation('errors')
  const [code, setCode] = useState<string | null>(null)

  useEffect(() => {
    if (!message) {
      setCode(null)
      return
    }
    if (showCodeOnlyForServer && !isServerError(message)) {
      setCode(null)
      return
    }
    setCode(getLastErrorCorrelationId())
  }, [message, showCodeOnlyForServer])

  if (!message) return null

  return (
    <div>
      <p className={className} style={style}>
        {message}
      </p>
      {code && (
        <small
          style={{ display: 'block', marginTop: 4, fontSize: 10, opacity: 0.7 }}
        >
          {t('supportCode', { id: code })}
        </small>
      )}
    </div>
  )
}
