import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  listShopItems,
  purchaseShopItem,
  type EngineInventoryItem,
  type ShopCatalogItem,
} from '../../api/engineApi'

type ShopScreenProps = {
  inventory: EngineInventoryItem[]
  onScreenChange: (screen: Screen) => void
  onPurchaseComplete?: () => void
}

export function ShopScreen({
  onScreenChange,
  onPurchaseComplete,
}: ShopScreenProps) {
  const [items, setItems] = useState<ShopCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [purchasingId, setPurchasingId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listShopItems()
      .then((data) => {
        if (!cancelled) setItems(data.items)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handlePurchase(item: ShopCatalogItem) {
    setPurchasingId(item.itemId)
    setError(null)
    setNotice(null)
    try {
      const result = await purchaseShopItem(item.itemId)
      setNotice(`Куплено. Баланс: ${result.rootBalance} ROOT.`)
      // Обновить список (owned мог измениться).
      const refreshed = await listShopItems()
      setItems(refreshed.items)
      // Передать наверх: refetch bootstrap (inventory + rootBalance в App).
      onPurchaseComplete?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPurchasingId(null)
    }
  }

  return (
    <section className="shop">
      <p className="eyebrow">МАГАЗИН / КЛЮЧИ</p>
      <h2>Магазин</h2>

      {loading && <p className="admin-muted">Загрузка…</p>}

      {error && <p className="admin-alert admin-error">{error}</p>}
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      {!loading && items.length === 0 && !error && (
        <article className="message-card">
          <p>Магазин пуст.</p>
        </article>
      )}

      {items.map((item) => (
        <article className="message-card" key={item.itemId}>
          <h3>
            {item.symbol ? `${item.symbol} ` : ''}
            {item.title}
          </h3>
          <p>
            <code>{item.code}</code>
          </p>

          <p>
            Цена: <b>{item.priceRoot} ROOT</b>
          </p>

          <p className="admin-muted">У вас: {item.owned} шт.</p>

          <button
            className="admin-primary"
            onClick={() => handlePurchase(item)}
            disabled={purchasingId === item.itemId}
          >
            {purchasingId === item.itemId
              ? 'Покупка…'
              : `Купить за ${item.priceRoot} ROOT`}
          </button>
        </article>
      ))}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}