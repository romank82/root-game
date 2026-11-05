import { useTranslation } from 'react-i18next'
import type { Screen } from '../types/game'

interface MobileNavigationProps {
  screen: Screen
  onScreenChange: (screen: Screen) => void
  onOpenMore: () => void
}

const MORE_SCREENS: Screen[] = ['camera-test', 'archive', 'inventory', 'shop', 'transfer']

export function MobileNavigation({ screen, onScreenChange, onOpenMore }: MobileNavigationProps) {
  const { t } = useTranslation(['common'])

  return (
    <nav className="mobile-navigation" aria-label="Игровая навигация">
      <button
        className={`tab${screen === 'terminal' ? ' active' : ''}`}
        onClick={() => onScreenChange('terminal')}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="4 17 10 11 4 5" />
          <line x1="12" y1="19" x2="20" y2="19" />
        </svg>
        <span className="lbl">{t('common:tabs.terminal')}</span>
      </button>

      <button
        className={`tab${screen === 'scanner' ? ' active' : ''}`}
        onClick={() => onScreenChange('scanner')}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3 7V5a2 2 0 0 1 2-2h2" />
          <path d="M17 3h2a2 2 0 0 1 2 2v2" />
          <path d="M21 17v2a2 2 0 0 1-2 2h-2" />
          <path d="M7 21H5a2 2 0 0 1-2-2v-2" />
          <circle cx="12" cy="12" r="3" />
        </svg>
        <span className="lbl">{t('common:tabs.scanner')}</span>
      </button>

      <button
        className={`tab${screen === 'map' ? ' active' : ''}`}
        onClick={() => onScreenChange('map')}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
          <circle cx="12" cy="10" r="3" />
        </svg>
        <span className="lbl">{t('common:tabs.map')}</span>
      </button>

      <button
        className={`tab${screen === 'profile' ? ' active' : ''}`}
        onClick={() => onScreenChange('profile')}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
        <span className="lbl">{t('common:tabs.profile')}</span>
      </button>

      <button
        className={`tab${MORE_SCREENS.includes(screen) ? ' active' : ''}`}
        onClick={onOpenMore}
        aria-haspopup="dialog"
      >
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="12" cy="12" r="2" />
          <circle cx="19" cy="12" r="2" />
          <circle cx="5" cy="12" r="2" />
        </svg>
        <span className="lbl">{t('common:tabs.more')}</span>
      </button>
    </nav>
  )
}
