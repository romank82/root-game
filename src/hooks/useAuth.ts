import { useEffect, useState } from 'react'
import {
  authenticateTelegram,
  getEngineBootstrap,
  type EngineBootstrap,
} from '../api/engineApi'
import type { AuthStatus } from '../types/game'

type AuthState = {
  status: AuthStatus
  error: string
}

function initialAuthState(): AuthState {
  const webApp = window.Telegram?.WebApp
  const initData = webApp?.initData?.trim()

  if (!webApp) {
    return {
      status: 'unavailable',
      error: (
        'Telegram WebApp SDK недоступен. '
        + 'Откройте игру кнопкой Mini App в чате с ботом.'
      ),
    }
  }

  if (!initData) {
    return {
      status: 'unavailable',
      error: (
        'Telegram WebApp SDK доступен, но данные запуска Mini App не переданы.'
      ),
    }
  }

  return { status: 'checking', error: '' }
}

export function useAuth(onBootstrap: (bootstrap: EngineBootstrap) => void) {
  const [auth, setAuth] = useState<AuthState>(initialAuthState)

  useEffect(() => {
    let isMounted = true
    const webApp = window.Telegram?.WebApp
    const initData = webApp?.initData?.trim()

    webApp?.ready()
    webApp?.expand()

    // The unavailable state is derived during initialization. Do not attempt
    // authentication without Telegram-controlled Mini App launch data.
    if (!webApp || !initData) {
      return () => {
        isMounted = false
      }
    }

    authenticateTelegram(initData)
      .then(() => getEngineBootstrap())
      .then((bootstrap) => {
        if (!isMounted) return
        onBootstrap(bootstrap)
        setAuth({ status: 'authenticated', error: '' })
      })
      .catch((error: unknown) => {
        if (!isMounted) return
        setAuth({
          status: 'error',
          error: error instanceof Error
            ? error.message
            : 'Не удалось подтвердить Telegram-сессию.',
        })
      })

    return () => {
      isMounted = false
    }
  }, [onBootstrap])

  return { authStatus: auth.status, authError: auth.error }
}
