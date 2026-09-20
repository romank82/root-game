import type { EngineInventoryItem } from '../../api/engineApi'
import type { Screen } from '../../types/game'

interface InventoryScreenProps {
  inventory: EngineInventoryItem[]
  onScreenChange: (screen: Screen) => void
}

export function InventoryScreen({ inventory, onScreenChange }: InventoryScreenProps) {
  const keyA01 = inventory.find((item) => item.id === 'item-key-a01')
  const archiveA17 = inventory.find(
    (item) => item.id === 'item-archive-a17',
  )

  return (
    <section className="inventory">
      <p className="eyebrow">ИНВЕНТАРЬ / ЛИЧНЫЙ КОНТУР</p>

      <div className="inventory-heading">
        <div>
          <h2>Найденные объекты</h2>
          <p>
            Предметы не имеют реальной ценности и существуют только внутри
            истории «Протокола Химера».
          </p>
        </div>

        <div className="inventory-count">
          <span>ОБЪЕКТОВ</span>
          <strong>{String(inventory.length).padStart(2, '0')} / 03</strong>
        </div>
      </div>

      <div className="item-grid">
        {keyA01 ? (
          <article className="item-card">
            <div className="item-symbol">{keyA01.symbol}</div>
            <span className="file-label">ОБЪЕКТ #01</span>
            <h3>{keyA01.title}</h3>
            <p>{keyA01.description}</p>
            <small>СТАТУС: СТАБИЛЬНЫЙ</small>
          </article>
        ) : (
          <article className="item-card locked-item">
            <div className="item-symbol">?</div>
            <span className="file-label">ОБЪЕКТ #01</span>
            <h3>НЕ ОБНАРУЖЕН</h3>
            <p>Пройдите первую проверку, чтобы извлечь объект.</p>
            <small>СТАТУС: ЗАБЛОКИРОВАН</small>
          </article>
        )}

        {archiveA17 ? (
          <article className="item-card">
            <div className="item-symbol">{archiveA17.symbol}</div>
            <span className="file-label">ОБЪЕКТ #02</span>
            <h3>{archiveA17.title}</h3>
            <p>{archiveA17.description}</p>
            <small>СТАТУС: ТРЕБУЕТ АНАЛИЗА</small>
          </article>
        ) : (
          <article className="item-card locked-item">
            <div className="item-symbol">?</div>
            <span className="file-label">ОБЪЕКТ #02</span>
            <h3>НЕ ОБНАРУЖЕН</h3>
            <p>
              Восстановите Сегмент ARCHIVE-017, чтобы извлечь объект.
            </p>
            <small>СТАТУС: ЗАБЛОКИРОВАН</small>
          </article>
        )}

        <article className="item-card locked-item">
          <div className="item-symbol">?</div>
          <span className="file-label">ОБЪЕКТ #03</span>
          <h3>НЕИЗВЕСТНЫЙ НОСИТЕЛЬ</h3>
          <p>
            Контур фиксирует присутствие ещё одного объекта. Доступа к
            данным пока нет.
          </p>
          <small>СТАТУС: СИГНАЛ НЕ РАСПОЗНАН</small>
        </article>
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
