import { useEffect, useState, type CSSProperties } from 'react'
import {
  listWithdrawals,
  rejectWithdrawal,
  runWithdrawalBatch,
  type Withdrawal,
} from '../../api/adminApi'
import { formatRootFromNano } from '../../utils/formatRoot'

// Sprint 11.8 NanoROOT (этап 2C): 1 ROOT = 10^8 наноROOT.
// Fallback, если ответ пришёл без *_nano (legacy).
const NANO_PER_ROOT = 100_000_000

type StatusFilter =
  | ''
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'processing'
  | 'confirmed'
  | 'failed'

type PeriodFilter = 'day' | 'week' | 'month' | 'all'

const PAGE_SIZE = 50
const BATCH_SIZE = 50

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'Все статусы' },
  { value: 'pending', label: 'pending' },
  { value: 'approved', label: 'approved' },
  { value: 'rejected', label: 'rejected' },
  { value: 'processing', label: 'processing' },
  { value: 'confirmed', label: 'confirmed' },
  { value: 'failed', label: 'failed' },
]

const PERIOD_OPTIONS: { value: PeriodFilter; label: string }[] = [
  { value: 'all', label: 'all · всё время' },
  { value: 'day', label: 'day · 24 часа' },
  { value: 'week', label: 'week · 7 дней' },
  { value: 'month', label: 'month · 30 дней' },
]

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

const tableStyle: CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '12px',
  fontFamily: '"IBM Plex Mono", monospace',
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')
}

function shorten(value: string | null | undefined, head = 9, tail = 6): string {
  if (!value) return '—'
  return value.length > head + tail + 1
    ? `${value.slice(0, head)}…${value.slice(-tail)}`
    : value
}

// 11.6-b: админ-фронт заявок на вывод ROOT → TON.
// Список + батч-выплата + отклонение. Ошибки и результаты действий
// показываются ЛОКАЛЬНО (error/actionMsg) и не роняют админку.
// Permission: players.read (чтение) / players.manage (batch/reject) — на бэке.
export function WithdrawalsSection() {
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [playerIdFilter, setPlayerIdFilter] = useState('')
  const [periodFilter, setPeriodFilter] = useState<PeriodFilter>('all')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [acting, setActing] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')

    listWithdrawals({
      status: statusFilter === '' ? undefined : statusFilter,
      playerId: playerIdFilter.trim() || undefined,
      period: periodFilter,
      limit: PAGE_SIZE,
      offset,
    })
      .then((data) => {
        if (!cancelled) {
          setWithdrawals(data.withdrawals)
          setTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить заявки на вывод.',
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
  }, [statusFilter, playerIdFilter, periodFilter, offset, reload])

  const applyFilters = () => {
    setOffset(0)
    setReload((tick) => tick + 1)
  }

  const handleReject = async (withdrawal: Withdrawal) => {
    const reason = window.prompt(`Причина отклонения заявки ${withdrawal.id}:`)
    if (reason === null) return
    if (reason.trim() === '') {
      setError('Укажите причину отклонения.')
      return
    }
    setActing(true)
    setError('')
    setActionMsg('')
    try {
      const result = await rejectWithdrawal(withdrawal.id, reason.trim())
      setActionMsg(`Заявка ${result.withdrawalId} отклонена: ${result.status}.`)
      setReload((tick) => tick + 1)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось отклонить заявку.',
      )
    } finally {
      setActing(false)
    }
  }

  const handleBatch = async () => {
    setActing(true)
    setError('')
    setActionMsg('')
    try {
      const result = await runWithdrawalBatch(BATCH_SIZE)
      setActionMsg(
        `Батч ${result.batchId}: выплачено ${result.confirmed}, ошибок ${result.failed}.`,
      )
      setReload((tick) => tick + 1)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось выполнить батч-выплату.',
      )
    } finally {
      setActing(false)
    }
  }

  const shownFrom = total === 0 ? 0 : offset + 1
  const shownTo = total === 0 ? 0 : Math.min(offset + PAGE_SIZE, total)

  return (
    <>
      <div className="admin-editor-title">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / WITHDRAWALS</p>
          <h2>Заявки на вывод</h2>
          <p className="admin-muted">
            Вывод ROOT → TON: список, батч-выплата, отклонение.
          </p>
        </div>
        <button
          className="admin-primary"
          onClick={handleBatch}
          disabled={acting || loading}
        >
          Выплатить батч ({BATCH_SIZE})
        </button>
      </div>

      <section className="admin-editor" style={{ marginTop: '24px' }}>
        <p className="admin-kicker">WITHDRAWALS / FILTERS</p>
        <h2 style={{ marginTop: '4px', marginBottom: '16px' }}>Фильтры</h2>

        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'end',
            gap: '12px',
            marginBottom: '16px',
          }}
        >
          <label style={{ flex: '0 0 150px' }}>
            Статус
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as StatusFilter)
                setOffset(0)
              }}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ flex: '1 1 220px' }}>
            Player ID
            <input
              type="text"
              value={playerIdFilter}
              onChange={(event) => {
                setPlayerIdFilter(event.target.value)
                setOffset(0)
              }}
              placeholder="например, player-3ab12cd4ef"
            />
          </label>
          <label style={{ flex: '0 0 190px' }}>
            Период
            <select
              value={periodFilter}
              onChange={(event) => {
                setPeriodFilter(event.target.value as PeriodFilter)
                setOffset(0)
              }}
            >
              {PERIOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="admin-primary"
            onClick={applyFilters}
            disabled={loading}
          >
            Применить
          </button>
        </div>

        {loading && <p className="admin-muted">Загрузка заявок…</p>}

        {error && <p className="admin-alert admin-error">{error}</p>}
        {actionMsg && <p className="admin-alert admin-notice">{actionMsg}</p>}

        {!loading && withdrawals.length === 0 && !error && (
          <p className="admin-muted">Заявок на вывод не найдено.</p>
        )}

        {!loading && withdrawals.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>ID</th>
                  <th style={thStyle}>PlayerId</th>
                  <th style={thStyle}>Amount</th>
                  <th style={thStyle}>ToAddress</th>
                  <th style={thStyle}>Статус</th>
                  <th style={thStyle}>TonTxHash</th>
                  <th style={thStyle}>Создана</th>
                  <th style={thStyle} />
                </tr>
              </thead>
              <tbody>
                {withdrawals.map((withdrawal) => (
                  <tr key={withdrawal.id}>
                    <td style={tdStyle}>{shorten(withdrawal.id)}</td>
                    <td style={tdStyle}>{shorten(withdrawal.playerId)}</td>
                    <td style={tdStyle}>
                      {formatRootFromNano(
                        withdrawal.amountRootNano ??
                          (withdrawal.amountRoot ?? 0) * NANO_PER_ROOT,
                      )}
                    </td>
                    <td style={tdStyle}>{shorten(withdrawal.toAddress)}</td>
                    <td style={tdStyle}>
                      {withdrawal.status}
                      {/* Причина отказа выплаты: без неё failed + пустой хеш
                          не отличить по конфигу, сети и балансу. */}
                      {withdrawal.payoutError && (
                        <div
                          style={{
                            marginTop: 4,
                            fontSize: 11,
                            maxWidth: 260,
                            color: '#ff9d9d',
                            wordBreak: 'break-word',
                          }}
                          title={withdrawal.payoutError}
                        >
                          {withdrawal.payoutError}
                        </div>
                      )}
                    </td>
                    <td style={tdStyle}>
                      {withdrawal.tonTxHash ? shorten(withdrawal.tonTxHash) : '—'}
                    </td>
                    <td style={tdStyle}>{formatDate(withdrawal.createdAt)}</td>
                    <td style={tdStyle}>
                      {withdrawal.status === 'pending' && (
                        <button
                          type="button"
                          className="admin-secondary"
                          onClick={() => handleReject(withdrawal)}
                          disabled={acting}
                        >
                          Отклонить
                        </button>
                      )}
                    </td>
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
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={loading || offset === 0}
          >
            ← Назад
          </button>
          <span className="admin-muted">
            Показано {shownFrom}–{shownTo} из {total}
          </span>
          <button
            className="admin-secondary"
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={loading || offset + PAGE_SIZE >= total}
          >
            Вперёд →
          </button>
        </div>
      </section>
    </>
  )
}

