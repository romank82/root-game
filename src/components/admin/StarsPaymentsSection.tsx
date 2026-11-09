import { useEffect, useState, type CSSProperties } from 'react'
import {
  listStarsPayments,
  type AdminStarsPayment,
  type AdminStarsPaymentStatus,
} from '../../api/adminApi'

type StatusFilter = '' | AdminStarsPaymentStatus

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const
const DEFAULT_PAGE_SIZE = 50

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'Все статусы' },
  { value: 'pending', label: 'pending' },
  { value: 'completed', label: 'completed' },
  { value: 'refunded', label: 'refunded' },
]

// Цвета бейджа статуса — палитра MonitoringSection (inline-цвета:
// отдельных CSS-классов бейджей в проекте нет). Неизвестный статус
// (теоретически невозможен: CHECK ck_stars_payments_status) — цвет текста
// по умолчанию, поэтому fallback не нужен.
const STATUS_COLORS: Record<AdminStarsPaymentStatus, string> = {
  pending: '#ffcf8a',
  completed: '#8affc1',
  refunded: '#9fb6ff',
}

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

// Sprint 12.2: журнал Stars-платежей (покупка газа за Telegram Stars, 10.4).
// Только просмотр: кнопок мутаций нет — записи stars_payments создаёт
// stars_service (createInvoiceLink + webhook successful_payment), админка
// только читает GET /api/v1/admin/economy/stars-payments.
// Право economy.read проверяется на бэке (require_permission).
export function StarsPaymentsSection() {
  const [payments, setPayments] = useState<AdminStarsPayment[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [playerIdFilter, setPlayerIdFilter] = useState('')
  const [searchFilter, setSearchFilter] = useState('')
  const [fromFilter, setFromFilter] = useState('')
  const [toFilter, setToFilter] = useState('')
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE)
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')

    listStarsPayments({
      status: statusFilter === '' ? undefined : statusFilter,
      playerId: playerIdFilter.trim() || undefined,
      search: searchFilter.trim() || undefined,
      // <input type="date"> даёт yyyy-mm-dd: from — начало суток, to — конец
      // суток, чтобы фильтр «по дату» включал весь выбранный день (бэкенд
      // сравнивает created_at, а из голой даты вышла бы полночь).
      from: fromFilter ? `${fromFilter}T00:00:00` : undefined,
      to: toFilter ? `${toFilter}T23:59:59` : undefined,
      limit: pageSize,
      offset,
    })
      .then((data) => {
        if (!cancelled) {
          setPayments(data.items)
          setTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить журнал Stars-платежей.',
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
  }, [
    statusFilter,
    playerIdFilter,
    searchFilter,
    fromFilter,
    toFilter,
    pageSize,
    offset,
    reload,
  ])

  const applyFilters = () => {
    setOffset(0)
    setReload((tick) => tick + 1)
    setActionMsg('')
  }

  const resetFilters = () => {
    setStatusFilter('')
    setPlayerIdFilter('')
    setSearchFilter('')
    setFromFilter('')
    setToFilter('')
    setPageSize(DEFAULT_PAGE_SIZE)
    setOffset(0)
    setReload((tick) => tick + 1)
    setActionMsg('Фильтры сброшены.')
  }

  const shownFrom = total === 0 ? 0 : offset + 1
  const shownTo = total === 0 ? 0 : Math.min(offset + pageSize, total)

  return (
    <>
      <div className="admin-editor-title">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / STARS</p>
          <h2>Журнал Stars-платежей</h2>
          <p className="admin-muted">
            Покупка газа за Telegram Stars (10.4): инвойсы, статусы, charge
            id. Только просмотр, без операций.
          </p>
        </div>
      </div>

      <section className="admin-editor" style={{ marginTop: '24px' }}>
        <p className="admin-kicker">STARS / FILTERS</p>
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
          <label style={{ flex: '1 1 200px' }}>
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
          <label style={{ flex: '1 1 200px' }}>
            Поиск
            <input
              type="text"
              value={searchFilter}
              onChange={(event) => {
                setSearchFilter(event.target.value)
                setOffset(0)
              }}
              placeholder="reference_id / charge_id / payload"
            />
          </label>
          <label style={{ flex: '0 0 160px' }}>
            С даты
            <input
              type="date"
              value={fromFilter}
              onChange={(event) => {
                setFromFilter(event.target.value)
                setOffset(0)
              }}
            />
          </label>
          <label style={{ flex: '0 0 160px' }}>
            По дату
            <input
              type="date"
              value={toFilter}
              onChange={(event) => {
                setToFilter(event.target.value)
                setOffset(0)
              }}
            />
          </label>
          <label style={{ flex: '0 0 120px' }}>
            На страницу
            <select
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number.parseInt(event.target.value, 10))
                setOffset(0)
              }}
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={String(size)}>
                  {size}
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
          <button
            className="admin-secondary"
            onClick={resetFilters}
            disabled={loading}
          >
            Сбросить
          </button>
        </div>

        {loading && <p className="admin-muted">Загрузка платежей…</p>}

        {error && <p className="admin-alert admin-error">{error}</p>}
        {actionMsg && <p className="admin-alert admin-notice">{actionMsg}</p>}

        {!loading && payments.length === 0 && !error && (
          <p className="admin-muted">Платежей не найдено.</p>
        )}

        {!loading && payments.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>ID</th>
                  <th style={thStyle}>PlayerId</th>
                  <th style={thStyle}>Stars</th>
                  <th style={thStyle}>Gas</th>
                  <th style={thStyle}>Статус</th>
                  <th style={thStyle}>ChargeId</th>
                  <th style={thStyle}>ReferenceId</th>
                  <th style={thStyle}>Создан</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((payment) => (
                  <tr key={payment.id}>
                    <td style={tdStyle}>{shorten(payment.id)}</td>
                    <td style={tdStyle}>{shorten(payment.playerId)}</td>
                    <td style={tdStyle}>{payment.amountStars}</td>
                    <td style={tdStyle}>{payment.gasAmount}</td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          color: STATUS_COLORS[payment.status],
                          letterSpacing: '0.04em',
                        }}
                      >
                        {payment.status}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      {payment.telegramPaymentChargeId
                        ? shorten(payment.telegramPaymentChargeId, 8, 6)
                        : '—'}
                    </td>
                    <td style={tdStyle}>{shorten(payment.referenceId)}</td>
                    <td style={tdStyle}>{formatDate(payment.createdAt)}</td>
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
            onClick={() => setOffset(Math.max(0, offset - pageSize))}
            disabled={loading || offset === 0}
          >
            ← Назад
          </button>
          <span className="admin-muted">
            Показано {shownFrom}–{shownTo} из {total}
          </span>
          <button
            className="admin-secondary"
            onClick={() => setOffset(offset + pageSize)}
            disabled={loading || offset + pageSize >= total}
          >
            Вперёд →
          </button>
        </div>
      </section>
    </>
  )
}
