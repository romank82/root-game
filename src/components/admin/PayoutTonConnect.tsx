import { toNano } from '@ton/core'
import {
  TonConnectUIProvider,
  useTonConnectUI,
  useTonWallet,
} from '@tonconnect/ui-react'
import { useCallback, useMemo, useState } from 'react'
import type { PayoutBatch } from '../../api/adminApi'
import { formatRootFromNano } from '../../utils/formatRoot'
import { buildTransferPayload } from '../../utils/jettonTransfer'

// Манифест — визитка приложения для Tonkeeper, лежит в public/ и отдаётся
// с корня сайта. Без него кошелёк откажется подписывать.
//
// В dev домен другой (localhost), а Tonkeeper обязан скачать манифест,
// поэтому в разработке берём прод-адрес.
// Абсолютный URL обязателен: кошелёк загружает манифест из своего вебвью, и
// относительный путь он резолвит в СВОЙ домен — отсюда «Failed to load
// Manifest: 404». Домен берём текущий (prod — himeraprotocol.pro).
const MANIFEST_URL = `${window.location.origin}/tonconnect-manifest.json`

// Газ на один перевод: 0.05 TON уходит на jetton-wallet, чтобы он смог
// выполнить transfer. Реальная стоимость ~0.037 TON, остальное — запас.
const TRANSFER_JETTON_AMOUNT = '0.05'

// Больше кошелёк не соберёт в одну транзакцию.
const MAX_TRANSFERS_PER_REQUEST = 255

/** Провайдер TON Connect: useTonConnectUI работает только внутри него. */
export function PayoutTonConnectProvider({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <TonConnectUIProvider manifestUrl={MANIFEST_URL}>
      {children}
    </TonConnectUIProvider>
  )
}

/** Кнопка подключения/отключения кошелька + короткий адрес. */
export function WalletConnectButton() {
  const [tonConnectUI] = useTonConnectUI()
  const wallet = useTonWallet()
  const address = wallet?.account?.address

  if (wallet && address) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span
          style={{
            fontFamily: '"IBM Plex Mono", monospace',
            fontSize: '11px',
            color: '#8affc1',
          }}
          title={address}
        >
          {address.slice(0, 6)}…{address.slice(-4)}
        </span>
        <button
          className="admin-secondary"
          onClick={() => void tonConnectUI.disconnect()}
        >
          Отключить
        </button>
      </div>
    )
  }

  return (
    <button
      className="admin-secondary"
      onClick={() => void tonConnectUI.openModal()}
    >
      Подключить кошелёк
    </button>
  )
}

/**
 * Кнопка «Оплатить батч»: просит кошелёк подписать пачку jetton-переводов.
 *
 * Важно: переводим не на адрес игрока, а на его jetton-wallet — только он
 * умеет принимать ROOT. Адрес приходит с бэкенда в item.jettonWallet.
 */
export function PayBatchButton({
  batch,
  disabled,
  onSigned,
  onError,
}: {
  batch: PayoutBatch
  disabled?: boolean
  onSigned: (boc: string) => void
  onError: (message: string) => void
}) {
  const [tonConnectUI] = useTonConnectUI()
  const wallet = useTonWallet()
  const [signing, setSigning] = useState(false)

  const items = useMemo(() => batch.items ?? [], [batch.items])
  const totalNano = useMemo(
    () => items.reduce((sum, item) => sum + item.amountRootNano, 0),
    [items],
  )

  const handlePay = useCallback(async () => {
    if (!wallet) {
      onError('Сначала подключите кошелёк.')
      return
    }
    if (items.length === 0) {
      onError('В батче нет заявок.')
      return
    }
    if (items.length > MAX_TRANSFERS_PER_REQUEST) {
      onError(
        `Слишком много переводов (${items.length}), максимум ${MAX_TRANSFERS_PER_REQUEST}.`,
      )
      return
    }
    const missingQuery = items.filter((item) => !item.queryId)
    if (missingQuery.length > 0) {
      onError(
        `У ${missingQuery.length} заявок нет query_id — батч сформирован некорректно.`,
      )
      return
    }
    const missingWallet = items.filter((item) => !item.jettonWallet)
    if (missingWallet.length > 0) {
      onError(
        `Бэкенд не вернул jetton-wallet для ${missingWallet.length} заявок — оплата невозможна.`,
      )
      return
    }

    setSigning(true)
    try {
      const messages = items.map((item) => ({
        address: item.jettonWallet as string,
        amount: toNano(TRANSFER_JETTON_AMOUNT).toString(),
        payload: buildTransferPayload(
          item.amountRootNano,
          item.jettonWallet as string,
          item.queryId as string,
        ),
      }))

      const result = await tonConnectUI.sendTransaction({
        validUntil: Math.floor(Date.now() / 1000) + 300, // 5 минут
        messages,
      })

      if (!result?.boc) {
        onError('Кошелёк не вернул подписанное сообщение.')
        return
      }
      onSigned(result.boc)
    } catch (error) {
      // Пользователь мог закрыть окно — это не сбой системы, но причину
      // показать надо.
      onError(
        error instanceof Error
          ? error.message
          : 'Подпись отменена или кошелёк вернул ошибку.',
      )
    } finally {
      setSigning(false)
    }
  }, [wallet, items, tonConnectUI, onSigned, onError])

  const label = signing
    ? 'Ожидание подписи…'
    : `Оплатить батч (${items.length}) · ${formatRootFromNano(totalNano)} ROOT`

  return (
    <button
      className="admin-primary"
      onClick={() => void handlePay()}
      disabled={disabled || signing || !wallet || items.length === 0}
      title={!wallet ? 'Подключите кошелёк, чтобы оплатить батч' : undefined}
    >
      {label}
    </button>
  )
}
