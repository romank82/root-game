import { useTranslation } from 'react-i18next'
import type { Screen } from '../types/game'

interface MobileNavigationProps {
  screen: Screen
  onScreenChange: (screen: Screen) => void
}

export function MobileNavigation({ screen, onScreenChange }: MobileNavigationProps) {
  const { t } = useTranslation(['common'])

  return (
    <nav className="mobile-navigation" aria-label="Игровая навигация">
      <button
        className={screen === 'terminal' ? 'active' : ''}
        onClick={() => onScreenChange('terminal')}
      >
        <span>◉</span>
        {t('common:tabs.terminal')}
      </button>

      <button
        className={screen === 'archive' ? 'active' : ''}
        onClick={() => onScreenChange('archive')}
      >
        <span>▤</span>
        {t('common:tabs.archive')}
      </button>

      <button
        className={screen === 'scanner' ? 'active' : ''}
        onClick={() => onScreenChange('scanner')}
      >
        <span>⌗</span>
        {t('common:tabs.scanner')}
      </button>

      <button
        className={screen === 'map' ? 'active' : ''}
        onClick={() => onScreenChange('map')}
      >
        <span>◎</span>
        {t('common:tabs.map')}
      </button>

      {/* TEMP: dev-only camera test button — удалить в Sprint 8.6.g. */}
      {import.meta.env.DEV && (
        <button
          className={screen === 'camera-test' ? 'active' : ''}
          onClick={() => onScreenChange('camera-test')}
        >
          <span>◐</span>
          {t('common:tabs.camera')}
        </button>
      )}

      <button
        className={screen === 'inventory' ? 'active' : ''}
        onClick={() => onScreenChange('inventory')}
      >
        <span>◈</span>
        {t('common:tabs.inventory')}
      </button>

      <button
        className={screen === 'shop' ? 'active' : ''}
        onClick={() => onScreenChange('shop')}
      >
        <span>⊕</span>
        {t('common:tabs.shop')}
      </button>

      <button
        className={screen === 'transfer' ? 'active' : ''}
        onClick={() => onScreenChange('transfer')}
      >
        <span>⇄</span>
        {t('common:tabs.transfer')}
      </button>

      <button
        className={screen === 'profile' ? 'active' : ''}
        onClick={() => onScreenChange('profile')}
      >
        <span>◔</span>
        {t('common:tabs.profile')}
      </button>
    </nav>
  )
}
