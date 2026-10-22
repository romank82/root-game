import { useEffect, useState, type CSSProperties } from 'react'
import {
  listEconomyTransactions,
  type AdminEconomyTransaction,
  type AdminUser,
} from '../../api/adminApi'

type EconomySectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

const TRANSACTIONS_PAGE_SIZE = 50

const thStyle: CSSProperties = {
  textAlign: 'left',
  padding: '8px 10px',
  borderBottom: '1px solid rgba(190, 255, 226, 0.24)',
  color: '#8aac9d',
  fontSize: '10px',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
}

const tdStyle: CSSProperties = {
  padding: '8px 10px',
  borderBottom: '1px solid rgba(190, 255, 226, 0.08)',
  color: '#dff8eb',
  verticalAlign: 'top',
}

function formatAmount(value: number): string {
  return value.toLocaleString('ru-RU')
}

function formatCreatedAt(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function EconomySection({
  admin: _admin,
  canWrite: _canWrite,
  onError,
  onNotice: _onNotice,
}: EconomySectionProps) {
  const [transactions, setTransactions] = useState<AdminEconomyTransaction[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  // Черновики фильтров — применяются только по кнопке «Применить»,
  // чтобы не дёргать запрос на каждый введённый символ.
  const [draftPlayerId, setDraftPlayerId] = useState('')
  const [draftType, setDraftType] = useState<'' | 'credit' | 'debit'>('')
  const [draftFrom, setDraftFrom] = useState('')
  const [draftTo, setDraftTo] = useState('')

  // Применённые фильтры + пагинация.
  const [playerId, setPlayerId] = useState('')
  const [type, setType] = useState<'' | 'credit' | 'debit'>('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [limit] = useState(TRANSACTIONS_PAGE_SIZE)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    listEconomyTransactions({
      playerId: playerId.trim() || undefined,
      type: type || undefined,
      from: from || undefined,
      to: to || undefined,
      limit,
      offset,
    })
      .then((data) => {
        if (!cancelled) {
          setTransactions(data.transactions)
          setTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          onError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить транзакции.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerId, type, from, to, offset])

  function applyFilters() {
    setPlayerId(draftPlayerId)
    setType(draftType)
    setFrom(draftFrom)
    setTo(draftTo)
    setOffset(0)
  }

  const shownFrom = total === 0 ? 0 : offset + 1
  const shownTo = total === 0 ? 0 : Math.min(offset + limit, total)

  return (
    <section className="admin-editor">
      <div className="admin-editor-title">
        <div>
          <p className="admin-kicker">ROOT / WALLET LEDGER</p>
          <h2>Реестр операций</h2>
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'end',
          gap: '12px',
          marginBottom: '20px',
        }}
      >
        <label style={{ flex: '1 1 180px' }}>
          Player ID
          <input
            type="text"
            value={draftPlayerId}
            onChange={(event) => setDraftPlayerId(event.target.value)}
          />
        </label>
        <label style={{ flex: '0 0 140px' }}>
          Тип
          <select
            value={draftType}
            onChange={(event) =>
              setDraftType(event.target.value as '' | 'credit' | 'debit')
            }
          >
            <option value="">Все</option>
            <option value="credit">Credit</option>
            <option value="debit">Debit</option>
          </select>
        </label>
        <label style={{ flex: '0 0 160px' }}>
          От
          <input
            type="date"
            value={draftFrom}
            onChange={(event) => setDraftFrom(event.target.value)}
          />
        </label>
        <label style={{ flex: '0 0 160px' }}>
          До
          <input
            type="date"
            value={draftTo}
            onChange={(event) => setDraftTo(event.target.value)}
          />
        </label>
        <button className="admin-primary" onClick={applyFilters} disabled={loading}>
          Применить
        </button>
      </div>

      {loading && <p className="admin-muted">Загрузка транзакций…</p>}

      {!loading && transactions.length === 0 && (
        <p className="admin-muted">Транзакций пока нет.</p>
      )}

      {!loading && transactions.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '12px',
              fontFamily: '"IBM Plex Mono", monospace',
            }}
          >
            <thead>
              <tr>
                <th style={thStyle}>Player</th>
                <th style={thStyle}>Type</th>
                <th style={thStyle}>Amount</th>
                <th style={thStyle}>Balance After</th>
                <th style={thStyle}>Reason</th>
                <th style={thStyle}>Reference</th>
                <th style={thStyle}>Created At</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((transaction) => (
                <tr key={transaction.id}>
                  <td style={tdStyle}>
                    {transaction.playerDisplayName ?? transaction.playerId}
                  </td>
                  <td style={tdStyle}>
                    <span
                      className="admin-status"
                      style={
                        transaction.transactionType === 'credit'
                          ? { borderColor: '#59eead', color: '#87fac0' }
                          : {
                              borderColor: 'rgba(255, 114, 114, 0.65)',
                              color: '#ff8a8a',
                            }
                      }
                    >
                      {transaction.transactionType}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    {transaction.transactionType === 'credit' ? '+' : '−'}
                    {formatAmount(transaction.amount)}
                  </td>
                  <td style={tdStyle}>{formatAmount(transaction.balanceAfter)}</td>
                  <td style={tdStyle}>{transaction.reason}</td>
                  <td style={tdStyle}>
                    {transaction.referenceType
                      ? `${transaction.referenceType}${transaction.referenceId ? ` ${transaction.referenceId}` : ''}`
                      : '—'}
                  </td>
                  <td style={tdStyle}>{formatCreatedAt(transaction.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '14px',
          marginTop: '18px',
        }}
      >
        <button
          className="admin-secondary"
          onClick={() => setOffset(Math.max(0, offset - limit))}
          disabled={loading || offset === 0}
        >
          ← Назад
        </button>
        <span className="admin-muted">
          Показано {shownFrom}–{shownTo} из {total}
        </span>
        <button
          className="admin-secondary"
          onClick={() => setOffset(offset + limit)}
          disabled={loading || offset + limit >= total}
        >
          Вперёд →
        </button>
      </div>
    </section>
  )
}