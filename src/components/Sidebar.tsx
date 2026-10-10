import type { ApiStatus, Screen } from '../types/game'

interface SidebarProps {
  echo: number
  apiStatus: ApiStatus
  onScreenChange: (screen: Screen) => void
}

export function Sidebar({ echo, apiStatus, onScreenChange }: SidebarProps) {
  return (
    <aside className="sidebar">
      <p>НАВИГАЦИЯ</p>

      <button className="active" onClick={() => onScreenChange('terminal')}>
        ◉ Контур
      </button>

      <button onClick={() => onScreenChange('archive')}>▤ Архив</button>

      <button onClick={() => onScreenChange('inventory')}>
        ◈ Инвентарь
      </button>

      <button onClick={() => onScreenChange('scanner')}>◌ Сканер</button>

      <button onClick={() => onScreenChange('shop')}>⊕ Магазин</button>

      <div className="echo-card">
        <span>РЕСУРС</span>
        <strong>{echo} ROOT</strong>
        <small>
          {apiStatus === 'checking' && 'синхронизация...'}
          {apiStatus === 'online' && 'синхронизация: online'}
          {apiStatus === 'offline' && 'локальный тестовый режим'}
        </small>
      </div>
    </aside>
  )
}
