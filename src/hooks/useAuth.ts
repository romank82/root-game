import { useEffect, useState } from 'react'
import { authenticateTelegram, getEngineBootstrap, type EngineBootstrap } from '../api/engineApi'
import type { AuthStatus } from '../types/game'

export function useAuth(onBootstrap: (bootstrap: EngineBootstrap) => void) {
  const [authStatus, setAuthStatus] = useState<AuthStatus>('checking')
  const [authError, setAuthError] = useState('')

  useEffect(() => {
    let isMounted = true
    const webApp = window.Telegram?.WebApp
    const initData = webApp?.initData?.trim()

    webApp?.ready()
    webApp?.expand()

    if (!initData) {
      setAuthStatus('unavailable')
      setAuthError(
        'Откройте CHIMERA Protocol через Telegram-бота, чтобы начать игровую сессию.',
      )
      return () => {
        isMounted = false
      }
    }

    authenticateTelegram(initData)
      .then(() => getEngineBootstrap())
      .then((bootstrap) => {
        if (!isMounted) return
        onBootstrap(bootstrap)
        setAuthStatus('authenticated')
      })
      .catch((error: unknown) => {
        if (!isMounted) return
        setAuthStatus('error')
        setAuthError(
          error instanceof Error
            ? error.message
            : 'Не удалось подтвердить Telegram-сессию.',
        )
      })

    return () => {
      isMounted = false
    }
  }, [onBootstrap])

  return { authStatus, authError }
}
