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
  return (
    <section className="inventory">
      <p className="eyebrow">ИНВЕНТАРЬ / ЛИЧНЫЙ КОНТУР</p>

      <div className="inventory-heading">
        <div>
          <h2>Найденные объекты</h2>
          <p>
            Инвентарь отображает только предметы, подтверждённые сервером.
          </p>
        </div>

        <div className="inventory-count">
          <span>ОБЪЕКТОВ</span>
          <strong>{String(inventory.length).padStart(2, '0')}</strong>
        </div>
      </div>

      <div className="item-grid">
        {inventory.length === 0 ? (
          <article className="item-card locked-item">
            <div className="item-symbol">?</div>
            <span className="file-label">ИНВЕНТАРЬ ПУСТ</span>
            <h3>ОБЪЕКТЫ НЕ ОБНАРУЖЕНЫ</h3>
            <p>
              Предметы появятся после подтверждённого сервером игрового
              события.
            </p>
            <small>СТАТУС: ОЖИДАНИЕ</small>
          </article>
        ) : (
          inventory.map((item, index) => (
            <article className="item-card" key={item.id}>
              <div className="item-symbol">{item.symbol}</div>
              <span className="file-label">
                ОБЪЕКТ #{String(index + 1).padStart(2, '0')}
              </span>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <small>
                КОЛИЧЕСТВО: {item.quantity} · {item.rarity}
              </small>
            </article>
          ))
        )}
      </div>

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}
