import { useTranslation } from 'react-i18next'
import type { ApiStatus, Screen } from '../types/game'
import { formatRootFromNano } from '../utils/formatRoot'

// Sprint 11.8 NanoROOT (этап 2C): 1 ROOT = 10^8 наноROOT.
// Fallback, если nano-значение не передано (legacy).
const NANO_PER_ROOT = 100_000_000

interface SidebarProps {
  echo: number
  // Sprint 11.8 NanoROOT (этап 2C): дробный баланс в nano (1 ROOT = 10^8).
  // null/undefined — родитель не передал, тогда fallback на echo × 10^8.
  rootBalanceNano?: number | null
  apiStatus: ApiStatus
  onScreenChange: (screen: Screen) => void
}

export function Sidebar({
  echo,
  rootBalanceNano,
  apiStatus,
  onScreenChange,
}: SidebarProps) {
  const { t } = useTranslation(['common'])
  const displayBalance = formatRootFromNano(
    rootBalanceNano ?? echo * NANO_PER_ROOT,
  )

  return (
    <aside className="sidebar">
      <p>{t('common:sidebar.navigation')}</p>

      <button className="active" onClick={() => onScreenChange('terminal')}>
        ◉ {t('common:tabs.terminal')}
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
        <span>{t('common:sidebar.resource')}</span>
        <strong>{displayBalance} ROOT</strong>
        <small>
          {apiStatus === 'checking' && t('common:sidebar.syncChecking')}
          {apiStatus === 'online' && t('common:sidebar.syncOnline')}
          {apiStatus === 'offline' && t('common:sidebar.syncOffline')}
        </small>
      </div>
    </aside>
  )
}
