import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Screen } from '../../types/game'
import {
  getEngineBootstrap,
  searchPlayers,
  transferRoot,
  type SearchPlayerHit,
} from '../../api/engineApi'
import { ErrorWithCode } from '../ErrorWithCode'
import { formatRootFromNano, rootToNano } from '../../utils/formatRoot'

interface TransferScreenProps {
  onScreenChange: (screen: Screen) => void
  // Баланс для отображения: App знает его из bootstrap (echo).
  rootBalance?: number
  // Sprint 11.8 NanoROOT (этап 2C): дробный баланс в nano (1 ROOT = 10^8).
  // null/undefined — старый ответ без поля, тогда fallback на rootBalance.
  rootBalanceNano?: number | null
  // 10.4-j-1: баланс газа из bootstrap (строка). App его пока не хранит —
  // при отсутствии пропса экран сам подтягивает газ при открытии.
  gasBalance?: string
  // После успешного перевода App обновляет bootstrap (как ShopScreen).
  onBalanceChange?: () => void
}

// 1 ROOT = 10^8 наноROOT — fallback, если nano-поле не пришло.
const NANO_PER_ROOT = 100_000_000

// Клиентский request_id для идемпотентности перевода: генерируется при
// открытии экрана и НЕ меняется до успешной отправки. Повторный запрос с
// тем же request_id вернёт первый результат без второго списания.
function makeRequestId(): string {
  if (
    typeof crypto !== 'undefined' &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function TransferScreen({
  onScreenChange,
  rootBalance,
  rootBalanceNano,
  gasBalance,
  onBalanceChange,
}: TransferScreenProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchPlayerHit[]>([])
  const [selected, setSelected] = useState<SearchPlayerHit | null>(null)
  const [amount, setAmount] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [requestId, setRequestId] = useState<string>(() => makeRequestId())
  const { t } = useTranslation(['transfer', 'common'])
  // 10.4-j-1: газ на момент открытия экрана (бootstrap). Пропс из App может
  // отсутствовать — тогда тянем сами, чтобы блок «Газ: N» был виден всегда.
  const [gas, setGas] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (typeof gasBalance === 'string') {
      setGas(gasBalance)
      return () => {
        cancelled = true
      }
    }
    getEngineBootstrap()
      .then((data) => {
        if (!cancelled) setGas(data.gasBalance)
      })
      .catch(() => {
        // Газ — не критичен: без него блок «Газ» просто не показывается.
      })
    return () => {
      cancelled = true
    }
  }, [gasBalance])

  async function handleSearch() {
    const q = query.trim()
    if (q.length < 3) {
      setError(t('transfer:search.error.tooShort'))
      return
    }
    setLoading(true)
    setError(null)
    setNotice(null)
    try {
      const data = await searchPlayers(q)
      setResults(data.players)
    } catch (err) {
      setResults([])
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function handleCancel() {
    setSelected(null)
    setAmount('')
    setError(null)
  }

  async function handleTransfer() {
    if (selected === null || saving) return
    // Sprint 8.x-fractional-transfer (шаг B): принимаем дробный ввод
    // («0,5» и «0.5»), нормализуем запятую, вычисляем nanoROOT.
    const normalized = amount.replace(',', '.')
    const parsed = parseFloat(normalized)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError(t('transfer:amount.error.notPositive'))
      return
    }
    const nano = rootToNano(parsed)
    if (nano <= 0) {
      setError(t('transfer:amount.error.notPositive'))
      return
    }
    if (rootBalanceNano != null && nano > rootBalanceNano) {
      setError(t('transfer:amount.error.insufficient'))
      return
    }
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      // Тело — snake_case (TransferPayload в engineApi). Отправляем точное
      // наноROOT (дробный ввод), amount не шлём (additive-контракт A1).
      const result = await transferRoot({
        to_player_id: selected.id,
        amount_nano: nano,
        request_id: requestId,
      })
      setNotice(
        t('transfer:notices.transferSuccess', {
          fromBalance: formatRootFromNano(
            result.fromBalanceNano ?? rootToNano(result.fromBalance),
          ),
        }),
      )
      // Успешная отправка: новый request_id для следующего перевода.
      setRequestId(makeRequestId())
      setSelected(null)
      setAmount('')
      setResults([])
      setQuery('')
      onBalanceChange?.()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="inventory">
      <p className="eyebrow">{t('transfer:header.eyebrow')}</p>
      <h2>{t('transfer:header.title')}</h2>

      {typeof rootBalance === 'number' && (
        <p>
          {t('transfer:header.availableLabel')}{' '}
          <b>
            {formatRootFromNano(rootBalanceNano ?? rootBalance * NANO_PER_ROOT)} ROOT
          </b>
        </p>
      )}

      {gas !== null && (
        <p>
          {t('transfer:gas.label')} <b>{gas}</b>
        </p>
      )}

      <ErrorWithCode message={error} className="repair-error" />
      {notice && <p className="mission-success-card">{notice}</p>}

      {selected === null ? (
        <>
          <label>
            {t('transfer:search.label')}
            <input
              type="text"
              value={query}
              placeholder={t('transfer:search.placeholder')}
              onChange={(e) => {
                setQuery(e.target.value)
                setError(null)
              }}
            />
          </label>

          <button
            type="button"
            className="primary-button"
            disabled={loading || query.trim().length < 3}
            onClick={handleSearch}
          >
            {loading ? t('transfer:search.buttons.searching') : t('common:search')}
          </button>

          {results.map((hit) => (
            <article className="message-card" key={hit.id}>
              <p>
                {hit.nickname ?? t('transfer:search.noNickname')}
                {hit.country ? ` · ${hit.country}` : ''}
              </p>
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  setSelected(hit)
                  setError(null)
                }}
              >
                {t('transfer:search.buttons.select')}
              </button>
            </article>
          ))}
        </>
      ) : (
        <>
          <p>
            {t('transfer:recipient.label')}{' '}
            <b>
              {selected.nickname ?? selected.id}
              {selected.country ? ` · ${selected.country}` : ''}
            </b>
          </p>

          <label>
            {t('transfer:amount.label')}
            <input
              type="number"
              min={1}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value)
                setError(null)
              }}
            />
          </label>

          <button
            type="button"
            className="primary-button"
            disabled={saving}
            onClick={handleTransfer}
          >
            {saving ? t('transfer:buttons.transferring') : t('transfer:buttons.transfer')}
          </button>

          <button type="button" onClick={handleCancel}>
            {t('common:cancel')}
          </button>
        </>
      )}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        {t('common:backToContour')}
      </button>
    </section>
  )
}