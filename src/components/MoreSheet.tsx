import { useTranslation } from 'react-i18next'
import type { Screen } from '../types/game'

interface MoreSheetProps {
  open: boolean
  onClose: () => void
  onScreenChange: (screen: Screen) => void
}

interface MoreItem {
  screen: Screen
  labelKey: string
  icon: string
  devOnly?: boolean
}

const MORE_ITEMS: MoreItem[] = [
  { screen: 'camera-test', labelKey: 'common:tabs.camera', icon: '◐', devOnly: true },
  { screen: 'archive', labelKey: 'common:tabs.archive', icon: '▤' },
  { screen: 'inventory', labelKey: 'common:tabs.inventory', icon: '◈' },
  { screen: 'shop', labelKey: 'common:tabs.shop', icon: '⊕' },
  { screen: 'transfer', labelKey: 'common:tabs.transfer', icon: '⇄' },
]

export function MoreSheet({ open, onClose, onScreenChange }: MoreSheetProps) {
  const { t } = useTranslation(['common'])

  if (!open) return null

  const items = MORE_ITEMS.filter((item) => !item.devOnly || import.meta.env.DEV)

  return (
    <div className="scrim" onClick={onClose}>
      <div className="sheet" onClick={(event) => event.stopPropagation()}>
        <div className="sheet-handle" aria-hidden="true" />
        <div className="sheet-list">
          {items.map((item) => (
            <button
              key={item.screen}
              className="srow"
              onClick={() => {
                onScreenChange(item.screen)
                onClose()
              }}
            >
              <span className="srow-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="srow-label">{t(item.labelKey)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}