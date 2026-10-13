export type Screen =
  | 'briefing'
  | 'terminal'
  | 'archive'
  | 'inventory'
  | 'scanner'
  | 'shop'
  | 'map'

export type AuthStatus = 'checking' | 'authenticated' | 'unavailable' | 'error'
export type ApiStatus = 'checking' | 'online' | 'offline'
