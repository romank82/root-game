import { useEffect, useState } from 'react'
import type { Screen } from '../../types/game'
import {
  getEngineBootstrap,
  searchPlayers,
  transferRoot,
  type SearchPlayerHit,
} from '../../api/engineApi'

interface TransferScreenProps {
  onScreenChange: (screen: Screen) => void
  // Баланс для отображения: App знает его из bootstrap (echo).
  rootBalance?: number
  // 10.4-j-1: баланс газа из bootstrap (строка). App его пока не хранит —
  // при отсутствии пропса экран сам подтягивает газ при открытии.
  gasBalance?: string
  // После успешного перевода App обновляет bootstrap (как ShopScreen).
  onBalanceChange?: () => void
}

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
      setError('Для поиска нужно минимум 3 символа.')
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
    const value = Number(amount)
    if (!Number.isFinite(value) || value <= 0) {
      setError('Введите сумму больше 0.')
      return
    }
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      // Тело — snake_case (TransferPayload в engineApi),
      // request_id не менялся с открытия экрана (идемпотентность).
      const result = await transferRoot({
        to_player_id: selected.id,
        amount: value,
        request_id: requestId,
      })
      setNotice(`Переведено. Баланс: ${result.fromBalance} ROOT.`)
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
      <p className="eyebrow">ПЕРЕВОД / ROOT</p>
      <h2>Перевод</h2>

      {typeof rootBalance === 'number' && (
        <p>
          Доступно: <b>{rootBalance} ROOT</b>
        </p>
      )}

      {gas !== null && (
        <p>
          Газ: <b>{gas}</b>
        </p>
      )}

      {error && <p className="repair-error">{error}</p>}
      {notice && <p className="mission-success-card">{notice}</p>}

      {selected === null ? (
        <>
          <label>
            Поиск игрока (минимум 3 символа)
            <input
              type="text"
              value={query}
              placeholder="Никнейм игрока"
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
            {loading ? 'Поиск…' : 'Найти'}
          </button>

          {results.map((hit) => (
            <article className="message-card" key={hit.id}>
              <p>
                {hit.nickname ?? 'Без ника'}
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
                Выбрать
              </button>
            </article>
          ))}
        </>
      ) : (
        <>
          <p>
            Получатель:{' '}
            <b>
              {selected.nickname ?? selected.id}
              {selected.country ? ` · ${selected.country}` : ''}
            </b>
          </p>

          <label>
            Сумма (ROOT)
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
            {saving ? 'Перевод…' : 'Перевести'}
          </button>

          <button type="button" onClick={handleCancel}>
            Отмена
          </button>
        </>
      )}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}