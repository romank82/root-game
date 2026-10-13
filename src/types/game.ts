export type Screen =
  | 'briefing'
  | 'terminal'
  | 'archive'
  | 'inventory'
  | 'scanner'
  | 'shop'
  | 'map'
  | 'camera-test'

export type AuthStatus = 'checking' | 'authenticated' | 'unavailable' | 'error'
export type ApiStatus = 'checking' | 'online' | 'offline'
