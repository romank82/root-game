import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Screen } from '../../types/game'
import {
  listFallbackOffers,
  purchaseFallbackOffer,
  type EngineInventoryItem,
  type FallbackOffer,
  type FallbackPurchaseResult,
} from '../../api/engineApi'
import { ErrorWithCode } from '../ErrorWithCode'

type ShopScreenProps = {
  inventory: EngineInventoryItem[]
  onScreenChange: (screen: Screen) => void
  onPurchaseComplete?: () => void
}

export function ShopScreen({
  onScreenChange,
  onPurchaseComplete,
}: ShopScreenProps) {
  const { t } = useTranslation(['shop', 'common'])
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
      setNotice(t('shop:notices.purchased', { balance: result.rootBalance }))
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
      <p className="eyebrow">{t('shop:header.eyebrow')}</p>
      <h2>{t('shop:header.title')}</h2>

      {loading && <p>{t('common:loading')}</p>}

      <ErrorWithCode message={error} className="admin-alert admin-error" />
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      {!loading && visibleOffers.length === 0 && !error && (
        <article className="message-card">
          <p>{t('shop:empty.message')}</p>
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
              {t('shop:card.priceLabel')} <b>{offer.priceRoot} ROOT</b>
            </p>

            <p>
              {t('shop:card.stockLabel', { count: offer.remainingQuota })}
            </p>

            {soldOut && (
              <p className="admin-muted">
                {t('shop:card.soldOut')}
              </p>
            )}
            {!soldOut && offerDisabled && (
              <p className="admin-muted">{t('shop:card.disabled')}</p>
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
                ? t('shop:buttons.purchasing')
                : t('shop:buttons.buy', { price: offer.priceRoot })}
            </button>
          </article>
        )
      })}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        {t('common:backToContour')}
      </button>
    </section>
  )
}