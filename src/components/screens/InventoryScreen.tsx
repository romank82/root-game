import { useTranslation } from 'react-i18next'
import type { EngineInventoryItem } from '../../api/engineApi'
import type { Screen } from '../../types/game'

interface InventoryScreenProps {
  inventory: EngineInventoryItem[]
  onScreenChange: (screen: Screen) => void
}

export function InventoryScreen({
  inventory,
  onScreenChange,
}: InventoryScreenProps) {
  const { t } = useTranslation(['inventory', 'common'])
  return (
    <section className="inventory">
      <p className="eyebrow">{t('inventory:header.eyebrow')}</p>

      <div className="inventory-heading">
        <div>
          <h2>{t('inventory:header.title')}</h2>
          <p>
            {t('inventory:header.subtitle')}
          </p>
        </div>

        <div className="inventory-count">
          <span>{t('inventory:header.objectsLabel')}</span>
          <strong>{String(inventory.length).padStart(2, '0')}</strong>
        </div>
      </div>

      <div className="item-grid">
        {inventory.length === 0 ? (
          <article className="item-card locked-item">
            <div className="item-symbol">?</div>
            <span className="file-label">{t('inventory:empty.fileLabel')}</span>
            <h3>{t('inventory:empty.title')}</h3>
            <p>
              {t('inventory:empty.hint')}
            </p>
            <small>{t('inventory:empty.statusLabel')}</small>
          </article>
        ) : (
          inventory.map((item, index) => {
            const rarityLabel = t(`inventory:rarity.${item.rarity}`, {
              defaultValue: item.rarity,
            })
            return (
              <article className="item-card" key={item.id}>
                <div className="item-symbol">{item.symbol}</div>
                <span className="file-label">
                  {t('inventory:item.cardLabel', {
                    index: String(index + 1).padStart(2, '0'),
                  })}
                </span>
                <h3>{item.title}</h3>
                <p>{item.description}</p>
                <small>
                  {t('inventory:item.quantityLabel')} {item.quantity} · {rarityLabel}
                </small>
              </article>
            )
          })
        )}
      </div>

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        {t('common:backToContour')}
      </button>
    </section>
  )
}
