import { useTranslation } from 'react-i18next'
import { formatRootFromNano } from '../utils/formatRoot'

interface TopbarProps {
  accepted: boolean
  rootBalance: number
  // Sprint 11.8 NanoROOT (этап 2C): дробный баланс в nano (1 ROOT = 10^8).
  // null/undefined — старый ответ без поля, тогда fallback на rootBalance.
  rootBalanceNano?: number | null
  onBrandClick: () => void
}

// 1 ROOT = 10^8 наноROOT — fallback, если nano-поле не пришло.
const NANO_PER_ROOT = 100_000_000

export function Topbar({
  accepted,
  rootBalance,
  rootBalanceNano,
  onBrandClick,
}: TopbarProps) {
  const { t } = useTranslation(['common'])
  const displayBalance = formatRootFromNano(
    rootBalanceNano ?? rootBalance * NANO_PER_ROOT,
  )
  return (
    <header className="topbar">
      <button
        className="brand"
        onClick={() => {
          if (accepted) {
            onBrandClick()
          }
        }}
      >
        <span className="brand-mark">◈</span>
        <span>
          <strong>CHIMERA</strong>
          <small>PROTOCOL // 01</small>
        </span>
      </button>

      {accepted && (
        <div className="topbar-session">
          <div className="status">
            <span className="status-dot" />
            {t('common:topbar.sessionActive')}
          </div>
          <div className="topbar-wallet" aria-label={t('common:topbar.balanceAria', { balance: displayBalance })}>
            <span>ROOT</span>
            <strong>{displayBalance}</strong>
          </div>
        </div>
      )}
    </header>
  )
}
