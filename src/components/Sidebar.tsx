import { useTranslation } from 'react-i18next'
import type { ApiStatus, Screen } from '../types/game'

interface SidebarProps {
  echo: number
  apiStatus: ApiStatus
  onScreenChange: (screen: Screen) => void
}

export function Sidebar({ echo, apiStatus, onScreenChange }: SidebarProps) {
  const { t } = useTranslation(['common'])

  return (
    <aside className="sidebar">
      <p>НАВИГАЦИЯ</p>

      <button className="active" onClick={() => onScreenChange('terminal')}>
        ◉ {t('common:tabs.terminal')}
      </button>

      <button onClick={() => onScreenChange('archive')}>
        ▤ {t('common:tabs.archive')}
      </button>

      <button onClick={() => onScreenChange('inventory')}>
        ◈ {t('common:tabs.inventory')}
      </button>

      <button onClick={() => onScreenChange('scanner')}>
        ◌ {t('common:tabs.scanner')}
      </button>

      <button onClick={() => onScreenChange('shop')}>
        ⊕ {t('common:tabs.shop')}
      </button>

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
