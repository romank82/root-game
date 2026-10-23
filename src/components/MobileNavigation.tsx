import type { Screen } from '../types/game'

interface MobileNavigationProps {
  screen: Screen
  onScreenChange: (screen: Screen) => void
}

export function MobileNavigation({ screen, onScreenChange }: MobileNavigationProps) {
  return (
    <nav className="mobile-navigation" aria-label="Игровая навигация">
      <button
        className={screen === 'terminal' ? 'active' : ''}
        onClick={() => onScreenChange('terminal')}
      >
        <span>◉</span>
        Контур
      </button>

      <button
        className={screen === 'archive' ? 'active' : ''}
        onClick={() => onScreenChange('archive')}
      >
        <span>▤</span>
        Архив
      </button>

      <button
        className={screen === 'scanner' ? 'active' : ''}
        onClick={() => onScreenChange('scanner')}
      >
        <span>⌗</span>
        Сканер
      </button>

      <button
        className={screen === 'map' ? 'active' : ''}
        onClick={() => onScreenChange('map')}
      >
        <span>◎</span>
        Карта
      </button>

      {/* TEMP: dev-only camera test button — удалить в Sprint 8.6.g. */}
      {import.meta.env.DEV && (
        <button
          className={screen === 'camera-test' ? 'active' : ''}
          onClick={() => onScreenChange('camera-test')}
        >
          <span>◐</span>
          Камера
        </button>
      )}

      <button
        className={screen === 'inventory' ? 'active' : ''}
        onClick={() => onScreenChange('inventory')}
      >
        <span>◈</span>
        Вещи
      </button>

      <button
        className={screen === 'shop' ? 'active' : ''}
        onClick={() => onScreenChange('shop')}
      >
        <span>⊕</span>
        Магазин
      </button>

      <button
        className={screen === 'transfer' ? 'active' : ''}
        onClick={() => onScreenChange('transfer')}
      >
        <span>⇄</span>
        Перевод
      </button>

      <button
        className={screen === 'profile' ? 'active' : ''}
        onClick={() => onScreenChange('profile')}
      >
        <span>◔</span>
        Профиль
      </button>
    </nav>
  )
}
