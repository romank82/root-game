import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  listFallbackOffers,
  purchaseFallbackOffer,
  type FallbackOffer,
} from '../../api/engineApi'

type ShopScreenProps = {
  onScreenChange: (screen: Screen) => void
}

export function ShopScreen({ onScreenChange }: ShopScreenProps) {
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
      const result = await purchaseFallbackOffer(offer.entitlementId)
      setNotice(
        `Куплено. Баланс: ${result.rootBalance} ROOT. ` +
          `Осталось попыток: ${result.remainingQuota}.`,
      )
      // Обновить список (quota могла уменьшиться, status → exhausted).
      const refreshed = await listFallbackOffers()
      setOffers(refreshed)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPurchasingId(null)
    }
  }

  return (
    <section className="shop">
      <p className="eyebrow">МАГАЗИН / ПЕРСОНАЛЬНЫЕ ПРЕДЛОЖЕНИЯ</p>
      <h2>Магазин</h2>

      {loading && <p className="admin-muted">Загрузка…</p>}

      {error && <p className="admin-alert admin-error">{error}</p>}
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      {!loading && offers.length === 0 && !error && (
        <article className="message-card">
          <p>
            У вас нет персональных предложений. Они открываются
            после первой неудачной попытки миссии.
          </p>
        </article>
      )}

      {offers.map((offer) => (
        <article className="message-card" key={offer.entitlementId}>
          <p className="eyebrow">{offer.missionTitle}</p>
          {offer.item && (
            <h3>
              {offer.item.symbol ? `${offer.item.symbol} ` : ''}
              {offer.item.title}
            </h3>
          )}
          {offer.item && (
            <p>
              <code>{offer.item.code}</code>
            </p>
          )}

          <p>
            Цена: <b>{offer.priceRoot} ROOT</b>
            {' · '}
            Осталось попыток: {offer.remainingQuota} из {offer.quotaLimit}
          </p>

          {offer.status === 'available' && offer.remainingQuota > 0 ? (
            <button
              className="admin-primary"
              onClick={() => handlePurchase(offer)}
              disabled={purchasingId === offer.entitlementId}
            >
              {purchasingId === offer.entitlementId
                ? 'Покупка…'
                : `Купить за ${offer.priceRoot} ROOT`}
            </button>
          ) : (
            <p className="admin-muted">
              {offer.status === 'exhausted'
                ? 'Лимит покупок исчерпан.'
                : 'Предложение недоступно.'}
            </p>
          )}
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