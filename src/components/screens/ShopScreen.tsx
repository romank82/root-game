import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  listFallbackOffers,
  purchaseFallbackOffer,
  type EngineInventoryItem,
  type FallbackOffer,
  type FallbackPurchaseResult,
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
  const [offers, setOffers] = useState<FallbackOffer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [purchasingId, setPurchasingId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listFallbackOffers()
      .then((data) => {
        if (!cancelled) setOffers(data)
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

  async function handlePurchase(offer: FallbackOffer) {
    setPurchasingId(offer.entitlementId)
    setError(null)
    setNotice(null)
    try {
      const result: FallbackPurchaseResult = await purchaseFallbackOffer(
        offer.entitlementId,
      )
      setNotice(`Куплено. Баланс: ${result.rootBalance} ROOT.`)
      // Обновить квоту офферов после покупки.
      const refreshed = await listFallbackOffers()
      setOffers(refreshed)
      // Передать наверх: refetch bootstrap (inventory + rootBalance в App).
      onPurchaseComplete?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPurchasingId(null)
    }
  }

  // Офферы с неопубликованным предметом ключа (item === null) бэкенд помечает
  // статусом "disabled" и покупка недоступна — такие карточки не рендерим.
  const visibleOffers = offers.filter((offer) => offer.item !== null)

  return (
    <section className="shop">
      <p className="eyebrow">МАГАЗИН / КЛЮЧИ</p>
      <h2>Магазин</h2>

      {loading && <p>Загрузка…</p>}

      {error && <p className="admin-alert admin-error">{error}</p>}
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      {!loading && visibleOffers.length === 0 && !error && (
        <article className="message-card">
          <p>Магазин пуст. Провалите миссию — ключи появятся здесь.</p>
        </article>
      )}

      {visibleOffers.map((offer) => {
        const item = offer.item
        if (item === null) return null // defensive: отфильтрованы выше
        const soldOut = offer.remainingQuota <= 0
        const offerDisabled = offer.status !== 'available'

        return (
          <article className="message-card" key={offer.entitlementId}>
            <p className="eyebrow">{offer.missionTitle}</p>
            <h3>
              {item.symbol ? `${item.symbol} ` : ''}
              {item.title}
            </h3>
            <p>
              <code>{item.code}</code>
            </p>

            <p>
              Цена: <b>{offer.priceRoot} ROOT</b>
            </p>

            <p>
              В магазине: <b>{offer.remainingQuota} шт.</b>
            </p>

            {soldOut && (
              <p className="admin-muted">
                Распродано. Следующий провал добавит ключ.
              </p>
            )}
            {!soldOut && offerDisabled && (
              <p className="admin-muted">Оффер отключён.</p>
            )}

            <button
              className="admin-primary"
              onClick={() => handlePurchase(offer)}
              disabled={
                purchasingId === offer.entitlementId ||
                soldOut ||
                offerDisabled
              }
            >
              {purchasingId === offer.entitlementId
                ? 'Покупка…'
                : `Купить за ${offer.priceRoot} ROOT`}
            </button>
          </article>
        )
      })}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}