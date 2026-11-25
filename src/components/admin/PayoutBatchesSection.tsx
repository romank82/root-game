import { useEffect, useState, type CSSProperties } from 'react'
import {
  confirmPayoutBatch,
  createPayoutBatch,
  getPayoutBatch,
  listPayoutBatches,
  rollbackPayoutBatch,
  type PayoutBatch,
  type PayoutBatchConfirmResult,
  type PayoutBatchRow,
} from '../../api/adminApi'
import { formatRootFromNano } from '../../utils/formatRoot'
import {
  PayBatchButton,
  WalletConnectButton,
} from './PayoutTonConnect'

const BATCH_SIZE = 50

// Бачти сортируются на бэкенде: ready -> submitted -> закрытые.
const STATUS_LABELS: Record<string, string> = {
  ready: 'на оплату',
  submitted: 'оплачен частично',
  confirmed: 'подтверждён',
  rolled_back: 'откачен',
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

// Ник игрока как ссылка: выглядит как текст, но кликабелен и ведёт в
// карточку игрока. Подчёркивание и цвет — чтобы было видно, что это ссылка.
const playerLinkStyle: CSSProperties = {
  background: 'none',
  border: 'none',
  padding: 0,
  font: 'inherit',
  color: '#8affc1',
  textDecoration: 'underline',
  textDecorationStyle: 'dotted',
  textUnderlineOffset: '3px',
  cursor: 'pointer',
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

function statusColor(status: string): string {
  if (status === 'ready') return '#ffd479'
  if (status === 'submitted') return '#8ab6ff'
  if (status === 'confirmed') return '#8affc1'
  return '#8aac9d'
}

/**
 * Батчи выплат: формирование, оплата через TON Connect, сверка, откат.
 *
 * Раздел работает поверх ручной оплаты: сервер готовит батч и выдаёт
 * query_id, владелец подписывает переводы в Tonkeeper, сервер проверяет
 * блокчейн. Приватный ключ на сервере не нужен.
 */
export function PayoutBatchesSection({
  onOpenPlayer,
}: {
  // Переход в карточку игрока: админ должен иметь возможность посмотреть,
  // кому именно платим, прямо из батча.
  onOpenPlayer?: (playerId: string) => void
} = {}) {
  const [batches, setBatches] = useState<PayoutBatchRow[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<PayoutBatch | null>(null)
  const [expandedLoading, setExpandedLoading] = useState(false)

  const [acting, setActing] = useState(false)
  const [confirmResult, setConfirmResult] =
    useState<PayoutBatchConfirmResult | null>(null)
  const [reload, setReload] = useState(0)

  // Загрузка списка вынесена из loadBatches в эффект-тело: setState в
  // синхронной части эффекта вызывает лишний рендер (правило
  // react(set-state-in-effect)). Здесь состояние меняется только после
  // await — это законно.
  useEffect(() => {
    let cancelled = false

    const load = async () => {
      setLoading(true)
      try {
        const response = await listPayoutBatches({ limit: 20 })
        if (cancelled) return
        setBatches(response.batches)
        setTotal(response.total)
        setError('')
      } catch (requestError) {
        if (cancelled) return
        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Не удалось загрузить батчи.',
        )
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [reload])

  const handleCreate = async () => {
    setActing(true)
    setError('')
    setNotice('')
    setConfirmResult(null)
    try {
      const batch = await createPayoutBatch(BATCH_SIZE)
      setNotice(
        `Батч ${shorten(batch.batchId)}: ${batch.itemCount ?? 0} заявок на ${
          batch.totalRoot
        } ROOT. Оплатите его из кошелька.`,
      )
      setExpandedId(batch.batchId)
      setReload((tick) => tick + 1)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось сформировать батч.',
      )
    } finally {
      setActing(false)
    }
  }

  const openBatch = async (batchId: string) => {
    if (expandedId === batchId) {
      setExpandedId(null)
      setExpanded(null)
      return
    }
    setExpandedId(batchId)
    setExpanded(null)
    setExpandedLoading(true)
    setError('')
    try {
      // getPayoutBatch резолвит jetton-wallet адреса на бэкенде: без них
      // фронт не сможет собрать перевод.
      const batch = await getPayoutBatch(batchId)
      setExpanded(batch)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось загрузить батч.',
      )
    } finally {
      setExpandedLoading(false)
    }
  }

  const handleSigned = async (boc: string) => {
    if (!expanded) return
    setActing(true)
    setError('')
    setNotice('')
    try {
      const result = await confirmPayoutBatch(expanded.batchId, boc)
      setConfirmResult(result)
      setNotice(
        result.status === 'confirmed'
          ? `Батч подтверждён: оплачено ${result.confirmedCount} из ${result.totalCount}.`
          : `Подтверждено ${result.confirmedCount} из ${result.totalCount}. Остальные ещё не видны в блокчейне — повторите сверку позже.`,
      )
      const refreshed = await getPayoutBatch(expanded.batchId)
      setExpanded(refreshed)
      setReload((tick) => tick + 1)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось подтвердить батч.',
      )
    } finally {
      setActing(false)
    }
  }

  const handleRollback = async (batchId: string) => {
    const mode = window.prompt(
      'Как откатить?\\n\\n1 — вернуть заявки в очередь (холд остаётся)\\n' +
        '2 — отклонить и вернуть ROOT игрокам\\n\\nВведите 1 или 2:',
      '1',
    )
    if (mode !== '1' && mode !== '2') return
    const reason = window.prompt('Причина отката (обязательно):', '')
    if (!reason || !reason.trim()) {
      setError('Причина отката обязательна.')
      return
    }

    setActing(true)
    setError('')
    setNotice('')
    try {
      const result = await rollbackPayoutBatch(batchId, {
        reason: reason.trim(),
        mode: mode === '2' ? 'fail_and_refund' : 'return_to_pending',
        force: true,
      })
      setNotice(
        `Батч ${shorten(batchId)} откачен: в очередь ${result.returned.length}, ` +
          `отклонено ${result.failed.length}, оплачено (не тронуто) ${result.skippedConfirmed.length}.`,
      )
      setReload((tick) => tick + 1)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось откатить батч.',
      )
    } finally {
      setActing(false)
    }
  }

  return (
    <>
      <div className="admin-editor-title">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / PAYOUT BATCHES</p>
          <h2>Батчи выплат</h2>
          <p className="admin-muted">
            Сервер готовит батч, вы платите из своего кошелька, сервер
            сверяет блокчейн. Приватный ключ остаётся у вас.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <WalletConnectButton />
          <button
            className="admin-primary"
            onClick={() => void handleCreate()}
            disabled={acting || loading}
          >
            Сформировать батч ({BATCH_SIZE})
          </button>
        </div>
      </div>

      {error && <p className="admin-alert admin-error">{error}</p>}
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      <section className="admin-editor" style={{ marginTop: '24px' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            marginBottom: '12px',
          }}
        >
          <h2 style={{ margin: 0 }}>Список батчей</h2>
          <span className="admin-muted">всего {total}</span>
        </div>

        {loading && <p className="admin-muted">Загрузка батчей…</p>}
        {!loading && batches.length === 0 && (
          <p className="admin-muted">Батчей пока нет.</p>
        )}

        {!loading && batches.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Батч</th>
                  <th style={thStyle}>Статус</th>
                  <th style={thStyle}>Заявок</th>
                  <th style={thStyle}>Сумма</th>
                  <th style={thStyle}>Открыт</th>
                  <th style={thStyle} />
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => (
                  <tr key={batch.batchId}>
                    <td style={tdStyle}>
                      <button
                        type="button"
                        onClick={() => void openBatch(batch.batchId)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: '#dff8eb',
                          cursor: 'pointer',
                          padding: 0,
                          fontFamily: 'inherit',
                          fontSize: 'inherit',
                          textDecoration: 'underline dotted',
                        }}
                      >
                        {shorten(batch.batchId)}
                      </button>
                    </td>
                    <td style={tdStyle}>
                      <span style={{ color: statusColor(batch.status) }}>
                        {STATUS_LABELS[batch.status] ?? batch.status}
                      </span>
                      {/* Батч висит дольше двух дней — деньги игроков ждут. */}
                      {batch.stale && (
                        <div
                          style={{ fontSize: 10, color: '#ffd479', marginTop: 2 }}
                        >
                          висит {batch.ageDays} дн.
                        </div>
                      )}
                    </td>
                    <td style={tdStyle}>{batch.itemCount}</td>
                    <td style={tdStyle}>{formatRootFromNano(batch.totalNano)}</td>
                    <td style={tdStyle}>{formatDate(batch.openedAt)}</td>
                    <td style={tdStyle}>
                      {batch.status !== 'confirmed' &&
                        batch.status !== 'rolled_back' && (
                          <button
                            type="button"
                            className="admin-secondary"
                            onClick={() => void handleRollback(batch.batchId)}
                            disabled={acting}
                          >
                            Откатить
                          </button>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {expandedId && (
          <div
            style={{
              marginTop: '18px',
              padding: '16px',
              border: '1px solid rgba(190, 255, 226, 0.18)',
              borderRadius: '10px',
              background: 'rgba(190, 255, 226, 0.03)',
            }}
          >
            {expandedLoading && (
              <p className="admin-muted">Загрузка заявок батча…</p>
            )}

            {expanded && (
              <>
                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    gap: '14px',
                    marginBottom: '14px',
                  }}
                >
                  <strong>Батч {shorten(expanded.batchId)}</strong>
                  <span style={{ color: statusColor(expanded.status) }}>
                    {STATUS_LABELS[expanded.status] ?? expanded.status}
                  </span>
                  <span className="admin-muted">
                    {expanded.items?.length ?? 0} заявок ·{' '}
                    {formatRootFromNano(expanded.totalNano)}
                  </span>

                  {expanded.status === 'ready' && (
                    <PayBatchButton
                      batch={expanded}
                      disabled={acting}
                      onSigned={(boc) => void handleSigned(boc)}
                      onError={(message) => setError(message)}
                    />
                  )}
                </div>

                {/* Результат сверки: показываем построчно, а не «успех/провал» —
                    TON может выполнить часть переводов. */}
                {confirmResult && (
                  <div style={{ marginBottom: '14px' }}>
                    <p className="admin-muted">
                      Сверка: подтверждено {confirmResult.confirmedCount} из{' '}
                      {confirmResult.totalCount}.
                    </p>
                    {confirmResult.pending.length > 0 && (
                      <p style={{ fontSize: 11, color: '#ffd479' }}>
                        Не найдены в блокчейне:{' '}
                        {confirmResult.pending
                          .map((entry) => shorten(entry.withdrawalId, 12, 4))
                          .join(', ')}
                      </p>
                    )}
                  </div>
                )}

                <div style={{ overflowX: 'auto' }}>
                  <table style={tableStyle}>
                    <thead>
                      <tr>
                        <th style={thStyle}>Заявка</th>
                        <th style={thStyle}>Игрок</th>
                        <th style={thStyle}>Сумма</th>
                        <th style={thStyle}>Адрес игрока</th>
                        <th style={thStyle}>Jetton wallet</th>
                        <th style={thStyle}>queryId</th>
                        <th style={thStyle}>Статус</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(expanded.items ?? []).map((item) => (
                        <tr key={item.withdrawalId}>
                          <td style={tdStyle}>{shorten(item.withdrawalId)}</td>
                          <td style={tdStyle}>
                            {/* player_id админу ничего не говорит — по нему
                                игрока не найти. Показываем ник и ведём в
                                карточку. Если ника ещё нет (старые записи),
                                остаётся id как запасной вариант. */}
                            <button
                              type="button"
                              onClick={() =>
                                onOpenPlayer?.(item.playerId)
                              }
                              title={item.playerId}
                              style={playerLinkStyle}
                            >
                              {item.playerNickname ??
                                shorten(item.playerId)}
                            </button>
                          </td>
                          <td style={tdStyle}>
                            {formatRootFromNano(item.amountRootNano)}
                          </td>
                          <td style={tdStyle}>{shorten(item.toAddress)}</td>
                          <td
                            style={{
                              ...tdStyle,
                              color: item.jettonWallet ? '#dff8eb' : '#ff9d9d',
                            }}
                          >
                            {item.jettonWallet
                              ? shorten(item.jettonWallet)
                              : 'не определён'}
                          </td>
                          <td style={tdStyle}>{item.queryId ?? '—'}</td>
                          <td style={tdStyle}>{item.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </section>
    </>
  )
}
