import { useEffect, useState, type CSSProperties } from 'react'
import {
  getGeoAuditFlags,
  reviewGeoAuditFlag,
  type GeoAuditFlag,
  type GeoAuditReviewDecision,
  type GeoAuditSignal,
} from '../../api/adminApi'

// Sprint 8.9.c: фронт раздела «Гео-аудит». Список флагов античита
// (velocity/accuracy) + review «Подтвердить/Снять» (players.manage — на бэке).
// Ошибки выборки показываются ЛОКАЛЬНО (error), чтобы сбой не выбивал alert
// всей админки; onNotice — только по явному действию пользователя.

type GeoAuditSectionProps = {
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

type PeriodFilter = 'day' | 'week' | 'month' | 'all'
type SignalFilter = '' | 'velocity' | 'accuracy'

const PAGE_SIZE = 50

const PERIOD_OPTIONS: { value: PeriodFilter; label: string }[] = [
  { value: 'week', label: 'week · 7 дней' },
  { value: 'day', label: 'day · 24 часа' },
  { value: 'month', label: 'month · 30 дней' },
  { value: 'all', label: 'all · всё время' },
]

const SIGNAL_OPTIONS: { value: SignalFilter; label: string }[] = [
  { value: '', label: 'Все сигналы' },
  { value: 'velocity', label: 'velocity' },
  { value: 'accuracy', label: 'accuracy' },
]

// Цвета статуса review — палитра MonitoringSection/StarsPayments (inline:
// отдельных CSS-классов бейджей в проекте нет). null/неизвестный статус — «—».
const REVIEW_STATUS_COLORS: Record<string, string> = {
  review: '#ffcf8a',
  reviewed: '#8affc1',
  dismissed: '#9fb6ff',
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

// Сигналы: только производные числа, без координат.
// Пример: «velocity 459.3 км/ч; accuracy 1 м».
function formatSignals(signals: GeoAuditSignal[]): string {
  if (!signals || signals.length === 0) return '—'
  return signals
    .map((item) => {
      if (item.signal === 'velocity') {
        return `velocity ${item.speedKmh ?? '—'} км/ч`
      }
      if (item.signal === 'accuracy') {
        return `accuracy ${item.accuracyMeters ?? '—'} м`
      }
      return item.signal
    })
    .join('; ')
}

function shorten(value: string | null, head = 9, tail = 6): string {
  if (!value) return '—'
  return value.length > head + tail + 1
    ? `${value.slice(0, head)}…${value.slice(-tail)}`
    : value
}

export function GeoAuditSection(props: GeoAuditSectionProps) {
  const [flags, setFlags] = useState<GeoAuditFlag[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [periodFilter, setPeriodFilter] = useState<PeriodFilter>('week')
  const [signalFilter, setSignalFilter] = useState<SignalFilter>('')
  const [playerIdFilter, setPlayerIdFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const [acting, setActing] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')

    getGeoAuditFlags({
      playerId: playerIdFilter.trim() || undefined,
      period: periodFilter,
      signal: signalFilter || undefined,
      limit: PAGE_SIZE,
      offset,
    })
      .then((data) => {
        if (!cancelled) {
          setFlags(data.flags)
          setTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить флаги гео-аудита.',
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
  }, [periodFilter, signalFilter, playerIdFilter, offset, reload])

  const applyFilters = () => {
    setOffset(0)
    setReload((tick) => tick + 1)
  }

  const handleReview = async (
    flag: GeoAuditFlag,
    decision: GeoAuditReviewDecision,
  ) => {
    if (!flag.missionId) return
    const reasonInput = window.prompt(
      `Причина (${decision}) для флага ${flag.id} (пусто — без причины):`,
    )
    if (reasonInput === null) return
    const reason = reasonInput.trim()
    setActing(true)
    setError('')
    setActionMsg('')
    try {
      const result = await reviewGeoAuditFlag(
        flag.playerId,
        flag.missionId,
        decision,
        reason || undefined,
      )
      setActionMsg(`Флаг ${flag.id}: ${result.status}.`)
      props.onNotice(`Флаг ${flag.id}: ${result.status}.`)
      setReload((tick) => tick + 1)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось выполнить review флага.',
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
          <p className="admin-kicker">CHIMERA PROTOCOL / GEO AUDIT</p>
          <h2>Гео-аудит</h2>
          <p className="admin-muted">
            Флаги античита (velocity/accuracy) и review. Сырые координаты не
            хранятся — только производные числа.
          </p>
        </div>
      </div>

      <section className="admin-editor" style={{ marginTop: '24px' }}>
        <p className="admin-kicker">GEO AUDIT / FILTERS</p>
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
          <label style={{ flex: '0 0 170px' }}>
            Сигнал
            <select
              value={signalFilter}
              onChange={(event) => {
                setSignalFilter(event.target.value as SignalFilter)
                setOffset(0)
              }}
            >
              {SIGNAL_OPTIONS.map((option) => (
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
          <button
            className="admin-primary"
            onClick={applyFilters}
            disabled={loading}
          >
            Применить
          </button>
        </div>

        {loading && <p className="admin-muted">Загрузка флагов…</p>}

        {error && <p className="admin-alert admin-error">{error}</p>}
        {actionMsg && <p className="admin-alert admin-notice">{actionMsg}</p>}

        {!loading && flags.length === 0 && !error && (
          <p className="admin-muted">Флагов не найдено.</p>
        )}

        {!loading && flags.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Дата</th>
                  <th style={thStyle}>Игрок</th>
                  <th style={thStyle}>Миссия</th>
                  <th style={thStyle}>Зона</th>
                  <th style={thStyle}>Сигналы</th>
                  <th style={thStyle}>Статус</th>
                  <th style={thStyle} />
                </tr>
              </thead>
              <tbody>
                {flags.map((flag) => (
                  <tr key={flag.id}>
                    <td style={tdStyle}>{formatDate(flag.createdAt)}</td>
                    <td style={tdStyle}>{shorten(flag.playerId)}</td>
                    <td style={tdStyle}>{shorten(flag.missionId)}</td>
                    <td style={tdStyle}>{flag.zoneId ?? '—'}</td>
                    <td style={tdStyle}>{formatSignals(flag.signals)}</td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          color: flag.reviewStatus
                            ? REVIEW_STATUS_COLORS[flag.reviewStatus]
                            : undefined,
                        }}
                      >
                        {flag.reviewStatus ?? '—'}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      {flag.reviewStatus === 'review' &&
                        flag.missionId &&
                        props.canWrite && (
                          <div style={{ display: 'flex', gap: '8px' }}>
                            <button
                              type="button"
                              className="admin-primary"
                              onClick={() => handleReview(flag, 'reviewed')}
                              disabled={acting}
                            >
                              Подтвердить
                            </button>
                            <button
                              type="button"
                              className="admin-secondary"
                              onClick={() => handleReview(flag, 'dismissed')}
                              disabled={acting}
                            >
                              Снять
                            </button>
                          </div>
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
