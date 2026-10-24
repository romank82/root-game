import { useEffect, useState, type CSSProperties } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  blockPlayer,
  getPlayer,
  getPlayerGasTransactions,
  getPlayerRootTransactions,
  getPlayersStats,
  getProfileFields,
  listPlayers,
  unblockPlayer,
  updatePlayerGas,
  updatePlayerRoot,
  type AdminPlayerCard,
  type AdminPlayerSummary,
  type AdminProfileField,
  type AdminUser,
  type GasTransaction,
  type PlayerBlockPayload,
  type PlayersStats,
  type RootAdjustmentPayload,
  type RootTransaction,
} from '../../api/adminApi'

type PlayersSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

const PLAYERS_PAGE_SIZE = 50

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

// 13.7-f: группируем ROOT-операции по дням (createdAt → 'YYYY-MM-DD'):
// amount в модели WalletTransaction ВСЕГДА положительный (abs), направление
// движения — в transactionType ('credit' — пришло, 'debit' — ушло).
function buildActivityChartData(transactions: RootTransaction[]): {
  date: string
  credit: number
  debit: number
}[] {
  const byDay = new Map<string, { credit: number; debit: number }>()
  for (const tx of transactions) {
    if (!tx.createdAt) continue
    const day = tx.createdAt.slice(0, 10) // YYYY-MM-DD
    const bucket = byDay.get(day) ?? { credit: 0, debit: 0 }
    if (tx.transactionType === 'credit') bucket.credit += tx.amount
    else if (tx.transactionType === 'debit') bucket.debit += tx.amount
    byDay.set(day, bucket)
  }
  return Array.from(byDay.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, value]) => ({
      date,
      credit: value.credit,
      debit: value.debit,
    }))
}

// 13.7-g-2: онлайн/офлайн по lastSeenAt. Колонка обновляется при каждом
// запросе (backend/app/main.py → datetime.now(timezone.utc)) и приходит
// ISO-строкой с +00:00; naive-строки на всякий случай трактуем как UTC.
function parseServerDate(value: string): Date {
  const hasZone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(value)
  return new Date(hasZone ? value : `${value}Z`)
}

function formatAgo(diffMs: number): string {
  const minutes = Math.max(0, Math.floor(diffMs / 60_000))
  if (minutes < 60) return `${minutes} мин назад`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} ч назад`
  return `${Math.floor(hours / 24)} дн назад`
}

function formatOnlineStatus(lastSeenAt: string | null): {
  label: string
  online: boolean
} {
  if (lastSeenAt === null) {
    return { label: 'Офлайн (давно)', online: false }
  }
  const parsed = parseServerDate(lastSeenAt)
  if (Number.isNaN(parsed.getTime())) {
    return { label: 'Офлайн (давно)', online: false }
  }
  const diffMs = Date.now() - parsed.getTime()
  if (diffMs < 5 * 60 * 1000) return { label: 'Онлайн', online: true }
  return { label: `Офлайн (${formatAgo(diffMs)})`, online: false }
}

// Значение поля карточки по ключу из PROFILE_FIELDS (nickname, country,
// gender, age). Неизвестные в будущем ключи отдаём пустой строкой.
function fieldValue(card: AdminPlayerCard, key: string): string {
  const player = card.player
  const value =
    key === 'nickname'
      ? player.nickname
      : key === 'country'
        ? player.country
        : key === 'gender'
          ? player.gender
          : key === 'age'
            ? player.age === null || player.age === undefined
              ? null
              : String(player.age)
            : null
  return value ?? ''
}

export function PlayersSection({
  admin: _admin,
  canWrite,
  onError,
  onNotice,
}: PlayersSectionProps) {
  const [players, setPlayers] = useState<AdminPlayerSummary[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  // Черновики фильтров — применяются только по кнопке «Применить».
  const [draftSearch, setDraftSearch] = useState('')
  const [draftStatus, setDraftStatus] = useState<'' | 'active' | 'blocked'>('')

  // Применённые фильтры + пагинация.
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'' | 'active' | 'blocked'>('')
  const [limit] = useState(PLAYERS_PAGE_SIZE)
  const [offset, setOffset] = useState(0)

  // 13.7-i-2: статистика всех игроков (total/online/active) — блок над
  // списком; period (day/week/month) переключает окно активности.
  const [statsPeriod, setStatsPeriod] = useState<'day' | 'week' | 'month'>('day')
  const [stats, setStats] = useState<PlayersStats | null>(null)
  const [statsError, setStatsError] = useState<string | null>(null)

  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null)
  const [profileFields, setProfileFields] = useState<AdminProfileField[]>([])
  const [selectedPlayer, setSelectedPlayer] = useState<AdminPlayerCard | null>(
    null,
  )
  const [loadingCard, setLoadingCard] = useState(false)
  const [cardError, setCardError] = useState<string | null>(null)

  // 13.7-a: профиль — только чтение (страна/пол/возраст не редактируются
  // в админке; PATCH-эндпоинт на бэке остаётся для точечного API-вызова).
  // Драфт/сохранение профиля (draftProfile/handleSaveProfile) удалены.

  // Газ (10.4-e-2): драфт формы, статусы и история (последние 50).
  const [gasDraft, setGasDraft] = useState<{ amount: string; reason: string }>({
    amount: '',
    reason: '',
  })
  const [savingGas, setSavingGas] = useState(false)
  const [savingGasError, setSavingGasError] = useState<string | null>(null)
  const [savingGasNotice, setSavingGasNotice] = useState<string | null>(null)
  const [gasTransactions, setGasTransactions] = useState<GasTransaction[]>([])

  // История ROOT — последние 50 транзакций выбранного игрока (13.7-e-2),
  // отдельный state от газа: истории живут в своих блоках карточки.
  const [rootTransactions, setRootTransactions] = useState<RootTransaction[]>([])
  const [rootTransactionsError, setRootTransactionsError] = useState<string | null>(
    null,
  )

  // Экономика игрока (13.7-d): модалка ROOT + ГАЗ. Отдельные драфты от
  // газ-формы в карточке (gasDraft), чтобы действия модалки не смешивались
  // с формой 10.4-e-2: обе остаются доступными.
  const [economyOpen, setEconomyOpen] = useState(false)
  const [rootDraft, setRootDraft] = useState<{ amount: string; reason: string }>({
    amount: '',
    reason: '',
  })
  const [gasDraftEconomy, setGasDraftEconomy] = useState<{
    amount: string
    reason: string
  }>({
    amount: '',
    reason: '',
  })
  const [savingEconomy, setSavingEconomy] = useState(false)
  const [economyError, setEconomyError] = useState<string | null>(null)
  const [economyNotice, setEconomyNotice] = useState<string | null>(null)

  // 13.7-h-2: блокировка/разблокировка игрока — модалка с reason.
  // Имя держим отдельно от economy-модалки (blockReason), чтобы не мешать
  // драфтам ROOT/ГАЗ; статус кнопки/заголовка — по selectedPlayer.player.status.
  const [blockModalOpen, setBlockModalOpen] = useState(false)
  const [blockReason, setBlockReason] = useState('')
  const [savingBlock, setSavingBlock] = useState(false)
  const [blockError, setBlockError] = useState<string | null>(null)
  const [blockNotice, setBlockNotice] = useState<string | null>(null)

  // Поля card-карточки (labels для read-only показа, 13.7-a) — один раз на mount.
  useEffect(() => {
    let cancelled = false
    getProfileFields()
      .then((data) => {
        if (!cancelled) setProfileFields(data.fields)
      })
      .catch((requestError) => {
        if (!cancelled) {
          onError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить поля профиля.',
          )
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Список игроков — на применённые фильтры + пагинацию.
  useEffect(() => {
    let cancelled = false
    setLoading(true)

    listPlayers({
      search: search.trim() || undefined,
      status: status || undefined,
      limit,
      offset,
    })
      .then((data) => {
        if (!cancelled) {
          setPlayers(data.players)
          setTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          onError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить игроков.',
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
  }, [search, status, offset])

  // 13.7-i-2: статистика всех игроков — на mount и при смене period.
  useEffect(() => {
    let cancelled = false
    getPlayersStats(statsPeriod)
      .then((data) => {
        if (!cancelled) {
          setStats(data)
          setStatsError(null)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setStats(null)
          setStatsError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить статистику.',
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [statsPeriod])

  // Карточка выбранного игрока.
  useEffect(() => {
    // 13.7-d: смена выбранного игрока закрывает модалку «Экономика игрока».
    setEconomyOpen(false)
    setEconomyError(null)
    setEconomyNotice(null)
    // 13.7-h-2: и модалку блокировки/разблокировки.
    setBlockModalOpen(false)
    setBlockReason('')
    setBlockError(null)
    setBlockNotice(null)
    if (selectedPlayerId === null) {
      setSelectedPlayer(null)
      setCardError(null)
      return
    }
    let cancelled = false
    setLoadingCard(true)
    setCardError(null)

    getPlayer(selectedPlayerId)
      .then((card) => {
        if (!cancelled) {
          setSelectedPlayer(card)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setSelectedPlayer(null)
          setCardError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить карточку игрока.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingCard(false)
      })

    return () => {
      cancelled = true
    }
  }, [selectedPlayerId])

  // История газа — последние 50 транзакций выбранного игрока (10.4-e-2).
  useEffect(() => {
    if (selectedPlayerId === null) {
      setGasTransactions([])
      setSavingGasError(null)
      setSavingGasNotice(null)
      return
    }
    let cancelled = false
    getPlayerGasTransactions(selectedPlayerId, { limit: 50 })
      .then((data) => {
        if (!cancelled) setGasTransactions(data.transactions)
      })
      .catch((requestError) => {
        if (!cancelled) {
          setSavingGasError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить транзакции газа.',
          )
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlayerId])

  // История ROOT — последние 50 транзакций выбранного игрока (13.7-e-2).
  useEffect(() => {
    if (selectedPlayerId === null) {
      setRootTransactions([])
      setRootTransactionsError(null)
      return
    }
    let cancelled = false
    getPlayerRootTransactions(selectedPlayerId, { limit: 50 })
      .then((data) => {
        if (!cancelled) setRootTransactions(data.transactions)
      })
      .catch((requestError) => {
        if (!cancelled) {
          setRootTransactionsError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить транзакции ROOT.',
          )
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlayerId])

  function applyFilters() {
    setSearch(draftSearch)
    setStatus(draftStatus)
    setOffset(0)
  }

  // 13.7-a: PATCH профиля из админки убран — страна/пол/возраст отображаются
  // только для чтения (read-only). Endpoint /admin/players/{id} на бэке
  // не тронут (может пригодиться точечно через API).

  async function handleSaveGas() {
    if (!selectedPlayer) return

    const rawAmount = gasDraft.amount.trim()
    const rawReason = gasDraft.reason.trim()
    const amount = Number(rawAmount)

    // Газ — дробный Numeric(18,4): валидируем число, но в запрос уходит
    // исходная строка (Decimal на бэке парсит её точно).
    if (rawAmount === '' || !Number.isFinite(amount) || amount === 0) {
      setSavingGasError('Сумма газа должна быть числом и не равна 0.')
      return
    }
    if (rawReason === '') {
      setSavingGasError('Укажите причину изменения (она попадёт в аудит).')
      return
    }

    setSavingGas(true)
    setSavingGasError(null)
    setSavingGasNotice(null)
    try {
      const updated = await updatePlayerGas(selectedPlayer.player.id, {
        amount: rawAmount,
        reason: rawReason,
      })
      setSelectedPlayer(updated)
      // Обновляем историю газа (последние 50) и сбрасываем драфт.
      const history = await getPlayerGasTransactions(
        selectedPlayer.player.id,
        { limit: 50 },
      )
      setGasTransactions(history.transactions)
      setGasDraft({ amount: '', reason: '' })
      setSavingGasNotice('Газ обновлён.')
    } catch (err) {
      setSavingGasError((err as Error).message)
    } finally {
      setSavingGas(false)
    }
  }

  // 13.7-d: «Экономика игрока» — модалка ROOT + ГАЗ.
  function openEconomyModal() {
    setRootDraft({ amount: '', reason: '' })
    setGasDraftEconomy({ amount: '', reason: '' })
    setEconomyError(null)
    setEconomyNotice(null)
    setEconomyOpen(true)
  }

  // 13.7-h-2: блокировка/разблокировка игрока — модалка с reason.
  function openBlockModal() {
    setBlockReason('')
    setBlockError(null)
    setBlockNotice(null)
    setBlockModalOpen(true)
  }

  function closeBlockModal() {
    setBlockModalOpen(false)
    setBlockError(null)
    setBlockNotice(null)
  }

  async function handleBlockPlayer() {
    if (!selectedPlayer) return

    const reason = blockReason.trim()
    if (reason === '') {
      setBlockError('Укажите причину блокировки (она попадёт в аудит).')
      return
    }

    setSavingBlock(true)
    setBlockError(null)
    setBlockNotice(null)
    try {
      const payload: PlayerBlockPayload = { reason }
      const updated = await blockPlayer(selectedPlayer.player.id, payload)
      setSelectedPlayer(updated)
      setBlockModalOpen(false)
      setBlockReason('')
      onNotice('Игрок заблокирован.')
    } catch (err) {
      setBlockError((err as Error).message)
    } finally {
      setSavingBlock(false)
    }
  }

  async function handleUnblockPlayer() {
    if (!selectedPlayer) return

    const reason = blockReason.trim()
    if (reason === '') {
      setBlockError('Укажите причину разблокировки (она попадёт в аудит).')
      return
    }

    setSavingBlock(true)
    setBlockError(null)
    setBlockNotice(null)
    try {
      const payload: PlayerBlockPayload = { reason }
      const updated = await unblockPlayer(selectedPlayer.player.id, payload)
      setSelectedPlayer(updated)
      setBlockModalOpen(false)
      setBlockReason('')
      onNotice('Игрок разблокирован.')
    } catch (err) {
      setBlockError((err as Error).message)
    } finally {
      setSavingBlock(false)
    }
  }

  async function handleApplyRoot() {
    if (!selectedPlayer) return

    const rawAmount = rootDraft.amount.trim()
    const rawReason = rootDraft.reason.trim()
    const amount = Number(rawAmount)

    // ROOT — целочисленный баланс: начислить/списать можно только целое число.
    if (rawAmount === '' || !Number.isInteger(amount) || amount === 0) {
      setEconomyError('Сумма ROOT должна быть целым числом и не равна 0.')
      return
    }
    if (rawReason === '') {
      setEconomyError('Укажите причину изменения (она попадёт в аудит).')
      return
    }

    setSavingEconomy(true)
    setEconomyError(null)
    setEconomyNotice(null)
    try {
      const payload: RootAdjustmentPayload = { amount, reason: rawReason }
      const updated = await updatePlayerRoot(selectedPlayer.player.id, payload)
      setSelectedPlayer(updated)
      // 13.7-e-2: перезагружаем историю ROOT в карточке после применения.
      const history = await getPlayerRootTransactions(
        selectedPlayer.player.id,
        { limit: 50 },
      )
      setRootTransactions(history.transactions)
      setRootTransactionsError(null)
      setRootDraft({ amount: '', reason: '' })
      setEconomyNotice('ROOT обновлён.')
    } catch (err) {
      setEconomyError((err as Error).message)
    } finally {
      setSavingEconomy(false)
    }
  }

  async function handleApplyGasEconomy() {
    if (!selectedPlayer) return

    const rawAmount = gasDraftEconomy.amount.trim()
    const rawReason = gasDraftEconomy.reason.trim()
    const amount = Number(rawAmount)

    // Газ — дробный Numeric(18,4): валидируем число, в запрос уходит исходная
    // строка (Decimal на бэке парсит её точно) — как в газ-форме карточки.
    if (rawAmount === '' || !Number.isFinite(amount) || amount === 0) {
      setEconomyError('Сумма газа должна быть числом и не равна 0.')
      return
    }
    if (rawReason === '') {
      setEconomyError('Укажите причину изменения (она попадёт в аудит).')
      return
    }

    setSavingEconomy(true)
    setEconomyError(null)
    setEconomyNotice(null)
    try {
      const updated = await updatePlayerGas(selectedPlayer.player.id, {
        amount: rawAmount,
        reason: rawReason,
      })
      setSelectedPlayer(updated)
      // Обновляем историю газа в карточке (10.4-e-2).
      const history = await getPlayerGasTransactions(
        selectedPlayer.player.id,
        { limit: 50 },
      )
      setGasTransactions(history.transactions)
      setGasDraftEconomy({ amount: '', reason: '' })
      setEconomyNotice('Газ обновлён.')
    } catch (err) {
      setEconomyError((err as Error).message)
    } finally {
      setSavingEconomy(false)
    }
  }

  const shownFrom = total === 0 ? 0 : offset + 1
  const shownTo = total === 0 ? 0 : Math.min(offset + limit, total)

  const cardTitle =
    selectedPlayer?.player.nickname ??
    selectedPlayer?.player.displayName ??
    'Игрок'

  // Статус онлайн/офлайн (13.7-g-2) по lastSeenAt (< 5 минут). Бейдж в шапке
  // рендерится только при выбранном игроке (onlineStatus === null иначе).
  const onlineStatus =
    selectedPlayer !== null
      ? formatOnlineStatus(selectedPlayer.player.lastSeenAt)
      : null

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="admin-editor-title">
          <div>
            <p className="admin-kicker">ROOT / PLAYERS</p>
            <h2>Игроки</h2>
          </div>
        </div>

        {/* 13.7-i-2: статистика всех игроков (Всего/Онлайн/Активность) —
            над поиском и фильтрами; period переключает окно активности. */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '10px',
            marginBottom: '14px',
          }}
        >
          <div>
            <p className="admin-kicker">ВСЕГО</p>
            <p
              style={{
                margin: '4px 0 0',
                fontSize: '22px',
                color: '#87fac0',
                fontFamily: '"IBM Plex Mono", monospace',
              }}
            >
              {stats ? String(stats.total) : '—'}
            </p>
          </div>
          <div>
            <p className="admin-kicker">ОНЛАЙН</p>
            <p
              style={{
                margin: '4px 0 0',
                fontSize: '22px',
                color: '#87fac0',
                fontFamily: '"IBM Plex Mono", monospace',
              }}
            >
              {stats ? String(stats.online) : '—'}
            </p>
          </div>
          <div>
            <p className="admin-kicker">АКТИВНОСТЬ</p>
            <p
              style={{
                margin: '4px 0 0',
                fontSize: '22px',
                color: '#87fac0',
                fontFamily: '"IBM Plex Mono", monospace',
              }}
            >
              {stats ? String(stats.active) : '—'}
            </p>
          </div>
        </div>
        <label style={{ display: 'block', marginBottom: '14px' }}>
          Период активности
          <select
            value={statsPeriod}
            onChange={(event) =>
              setStatsPeriod(event.target.value as 'day' | 'week' | 'month')
            }
          >
            <option value="day">day · 24 часа</option>
            <option value="week">week · 7 дней</option>
            <option value="month">month · 30 дней</option>
          </select>
        </label>
        {statsError && <p className="admin-alert admin-error">{statsError}</p>}

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
            Поиск
            <input
              type="text"
              value={draftSearch}
              onChange={(event) => setDraftSearch(event.target.value)}
              placeholder="ник, имя или telegram"
            />
          </label>
          <label style={{ flex: '0 0 140px' }}>
            Статус
            <select
              value={draftStatus}
              onChange={(event) =>
                setDraftStatus(event.target.value as '' | 'active' | 'blocked')
              }
            >
              <option value="">Все</option>
              <option value="active">Active</option>
              <option value="blocked">Blocked</option>
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

        {loading && <p className="admin-muted">Загрузка игроков…</p>}

        {!loading && players.length === 0 && (
          <p className="admin-muted">Игроков не найдено.</p>
        )}

        {!loading && players.length > 0 && (
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
                  <th style={thStyle}>Ник</th>
                  <th style={thStyle}>Имя</th>
                  <th style={thStyle}>Баланс</th>
                  <th style={thStyle}>Статус</th>
                </tr>
              </thead>
              <tbody>
                {players.map((player) => (
                  <tr
                    key={player.id}
                    onClick={() => setSelectedPlayerId(player.id)}
                    style={{
                      cursor: 'pointer',
                      ...(selectedPlayerId === player.id
                        ? { background: 'rgba(89, 238, 173, 0.07)' }
                        : undefined),
                    }}
                  >
                    <td style={tdStyle}>{player.nickname ?? '—'}</td>
                    <td style={tdStyle}>{player.displayName ?? '—'}</td>
                    <td style={tdStyle}>{formatAmount(player.rootBalance)}</td>
                    <td style={tdStyle}>
                      <span
                        className="admin-status"
                        style={{ color: '#8aac9d' }}
                      >
                        {player.status}
                      </span>
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
      </aside>

      <section className="admin-editor">
        <div className="admin-editor-title">
          <div>
            <p className="admin-kicker">ROOT / PLAYER CARD</p>
            <h2>{cardTitle}</h2>
            {onlineStatus && (
              <p
                style={{
                  marginTop: '4px',
                  fontSize: '11px',
                  letterSpacing: '0.04em',
                  color: onlineStatus.online ? '#87fac0' : '#9fc9b6',
                }}
              >
                <span
                  style={{ color: onlineStatus.online ? '#87fac0' : '#8aac9d' }}
                >
                  ●
                </span>{' '}
                {onlineStatus.label}
              </p>
            )}
          </div>
        </div>

        {loadingCard && <p className="admin-muted">Загрузка карточки…</p>}

        {!loadingCard && cardError && (
          <p className="admin-alert admin-error">{cardError}</p>
        )}

        {selectedPlayerId === null ? (
          <p className="admin-muted">Выберите игрока слева.</p>
        ) : !loadingCard && !cardError && selectedPlayer ? (
          <>
            <div style={{ marginTop: '4px' }}>
              <p className="admin-kicker">PROFILE</p>
              {profileFields.map((field) => (
                <p
                  key={field.key}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: '16px',
                    maxWidth: '400px',
                    margin: '6px 0',
                    fontSize: '13px',
                  }}
                >
                  <span
                    className="admin-muted"
                    style={{
                      textTransform: 'uppercase',
                      fontSize: '10px',
                      letterSpacing: '0.08em',
                      margin: 'auto 0',
                    }}
                  >
                    {field.label}
                  </span>
                  <span
                    style={{
                      fontFamily: '"IBM Plex Mono", monospace',
                      color: '#dff8eb',
                    }}
                  >
                    {fieldValue(selectedPlayer, field.key) || '—'}
                  </span>
                </p>
              ))}
            </div>

            <div style={{ marginTop: '18px' }}>
              <p className="admin-kicker">BALANCE</p>
              <p
                style={{
                  fontSize: '24px',
                  color: '#87fac0',
                  fontFamily: '"IBM Plex Mono", monospace',
                  margin: '4px 0',
                }}
              >
                {formatAmount(selectedPlayer.wallet.availableBalance)}{' '}
                {selectedPlayer.wallet.currency}
              </p>
              <p className="admin-muted">
                Закрыто: {formatAmount(selectedPlayer.wallet.lockedBalance)}{' '}
                {selectedPlayer.wallet.currency}
              </p>
              <div
                style={{
                  marginTop: '12px',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: '10px',
                }}
              >
                <button
                  className="admin-secondary"
                  onClick={openEconomyModal}
                  disabled={!canWrite || savingEconomy}
                >
                  Экономика игрока
                </button>
                {selectedPlayer.player.status === 'blocked' ? (
                  <button
                    className="admin-secondary"
                    onClick={openBlockModal}
                    disabled={!canWrite || savingBlock}
                  >
                    Разблокировать
                  </button>
                ) : (
                  <button
                    className="admin-secondary"
                    onClick={openBlockModal}
                    disabled={!canWrite || savingBlock}
                  >
                    Заблокировать
                  </button>
                )}
              </div>
            </div>

            {/* ACTIVITY (13.7-f): ROOT-операции по дням — credit/debit суммы
                из последних 50 проводок rootTransactions; показываем только
                если есть данные (пусто — скрываем, ниже «Транзакций ROOT
                нет» уже закрывает пустой случай). */}
            {rootTransactions.length > 0 && (
              <div style={{ marginTop: '30px' }}>
                <p className="admin-kicker">ACTIVITY (ROOT)</p>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={buildActivityChartData(rootTransactions)}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="rgba(190, 255, 226, 0.12)"
                    />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#9fc9b6' }} />
                    <YAxis tick={{ fontSize: 10, fill: '#9fc9b6' }} />
                    <Tooltip
                      contentStyle={{
                        background: '#0d1c18',
                        border: '1px solid rgba(190, 255, 226, 0.24)',
                      }}
                      labelStyle={{ color: '#dff8eb' }}
                    />
                    <Bar dataKey="credit" fill="#87fac0" name="Пришло" />
                    <Bar dataKey="debit" fill="#f08a8a" name="Ушло" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ROOT TRANSACTIONS (13.7-e-2): последние 50 проводок ROOT — над
                газ-таблицей, т.к. ROOT первичная валюта; обновляется при
                применении ROOT в модалке «Экономика игрока». */}
            <div style={{ marginTop: '30px' }}>
              <p className="admin-kicker">ROOT TRANSACTIONS</p>
              {rootTransactionsError && (
                <p className="admin-alert admin-error">{rootTransactionsError}</p>
              )}
              {rootTransactions.length === 0 ? (
                <p className="admin-muted">Транзакций ROOT нет.</p>
              ) : (
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
                      <th style={thStyle}>Дата</th>
                      <th style={thStyle}>Тип</th>
                      <th style={thStyle}>Сумма</th>
                      <th style={thStyle}>Баланс</th>
                      <th style={thStyle}>Причина</th>
                      <th style={thStyle}>Ссылка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rootTransactions.map((tx) => (
                      <tr key={tx.id}>
                        <td style={tdStyle}>
                          {tx.createdAt
                            ? new Date(tx.createdAt).toLocaleString('ru-RU')
                            : '—'}
                        </td>
                        <td style={tdStyle}>{tx.transactionType}</td>
                        <td style={tdStyle}>{formatAmount(tx.amount)}</td>
                        <td style={tdStyle}>{formatAmount(tx.balanceAfter)}</td>
                        <td style={tdStyle}>{tx.reason}</td>
                        <td style={tdStyle}>{tx.referenceType ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div style={{ marginTop: '30px' }}>
              <p className="admin-kicker">GAS</p>
              <p
                style={{
                  fontSize: '24px',
                  color: '#87fac0',
                  fontFamily: '"IBM Plex Mono", monospace',
                  margin: '4px 0',
                }}
              >
                {selectedPlayer.gasBalance} GAS
              </p>
            </div>

            <div style={{ marginTop: '18px' }}>
              <div className="admin-grid">
                <label>
                  Сумма
                  <input
                    type="number"
                    step="0.0001"
                    value={gasDraft.amount}
                    disabled={!canWrite || savingGas}
                    placeholder="например 5.5 или -3"
                    onChange={(e) =>
                      setGasDraft((prev) => ({
                        ...prev,
                        amount: e.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Причина (аудит)
                  <input
                    type="text"
                    value={gasDraft.reason}
                    disabled={!canWrite || savingGas}
                    placeholder="например bonus или refill"
                    onChange={(e) =>
                      setGasDraft((prev) => ({
                        ...prev,
                        reason: e.target.value,
                      }))
                    }
                  />
                </label>
              </div>

              <div className="admin-actions">
                <button
                  className="admin-primary"
                  onClick={handleSaveGas}
                  disabled={!canWrite || savingGas}
                >
                  {savingGas ? 'Сохранение…' : 'Сохранить газ'}
                </button>
                <button
                  className="admin-secondary"
                  onClick={() => {
                    setGasDraft({ amount: '', reason: '' })
                    setSavingGasError(null)
                    setSavingGasNotice(null)
                  }}
                  disabled={savingGas}
                >
                  Очистить
                </button>
              </div>

              {savingGasError && (
                <p className="admin-alert admin-error">{savingGasError}</p>
              )}
              {savingGasNotice && (
                <p className="admin-alert admin-notice">{savingGasNotice}</p>
              )}
            </div>

            <div style={{ marginTop: '18px' }}>
              <p className="admin-kicker">GAS TRANSACTIONS</p>
              {gasTransactions.length === 0 ? (
                <p className="admin-muted">Транзакций газа нет.</p>
              ) : (
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
                      <th style={thStyle}>Дата</th>
                      <th style={thStyle}>Тип</th>
                      <th style={thStyle}>Сумма</th>
                      <th style={thStyle}>Баланс</th>
                      <th style={thStyle}>Причина</th>
                      <th style={thStyle}>Ссылка</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gasTransactions.map((tx) => (
                      <tr key={tx.id}>
                        <td style={tdStyle}>
                          {tx.createdAt
                            ? new Date(tx.createdAt).toLocaleString('ru-RU')
                            : '—'}
                        </td>
                        <td style={tdStyle}>{tx.transactionType}</td>
                        <td style={tdStyle}>{tx.amount}</td>
                        <td style={tdStyle}>{tx.balanceAfter}</td>
                        <td style={tdStyle}>{tx.reason}</td>
                        <td style={tdStyle}>{tx.referenceType ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        ) : null}
        {/* 13.7-d: «Экономика игрока» — модалка ROOT + ГАЗ (начислить/списать). */}
        {economyOpen && selectedPlayer ? (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 100,
              background: 'rgba(2, 8, 6, 0.66)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'center',
              overflowY: 'auto',
              padding: '40px 16px',
            }}
          >
            <div
              style={{
                background: '#0d1c18',
                border: '1px solid rgba(190, 255, 226, 0.24)',
                borderRadius: '12px',
                padding: '20px',
                width: 'min(560px, 100%)',
                boxShadow: '0 12px 40px rgba(0, 0, 0, 0.5)',
              }}
            >
              <p className="admin-kicker">PLAYER ECONOMY</p>
              <h3 style={{ margin: '0 0 16px' }}>Экономика игрока</h3>

              {economyError && (
                <p className="admin-alert admin-error">{economyError}</p>
              )}
              {economyNotice && (
                <p className="admin-alert admin-notice">{economyNotice}</p>
              )}

              {/* ROOT */}
              <p className="admin-kicker">ROOT</p>
              <div className="admin-grid">
                <label>
                  Сумма
                  <input
                    type="number"
                    step="1"
                    value={rootDraft.amount}
                    disabled={!canWrite || savingEconomy}
                    placeholder="например 5 или -3"
                    onChange={(e) =>
                      setRootDraft((prev) => ({
                        ...prev,
                        amount: e.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Причина (аудит)
                  <input
                    type="text"
                    value={rootDraft.reason}
                    disabled={!canWrite || savingEconomy}
                    placeholder="например bonus или penalty"
                    onChange={(e) =>
                      setRootDraft((prev) => ({
                        ...prev,
                        reason: e.target.value,
                      }))
                    }
                  />
                </label>
              </div>
              <div className="admin-actions">
                <button
                  className="admin-primary"
                  onClick={handleApplyRoot}
                  disabled={!canWrite || savingEconomy}
                >
                  {savingEconomy ? 'Сохранение…' : 'Применить ROOT'}
                </button>
              </div>

              {/* ГАЗ */}
              <p className="admin-kicker" style={{ marginTop: '18px' }}>
                GAS
              </p>
              <div className="admin-grid">
                <label>
                  Сумма
                  <input
                    type="number"
                    step="0.0001"
                    value={gasDraftEconomy.amount}
                    disabled={!canWrite || savingEconomy}
                    placeholder="например 5.5 или -3"
                    onChange={(e) =>
                      setGasDraftEconomy((prev) => ({
                        ...prev,
                        amount: e.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  Причина (аудит)
                  <input
                    type="text"
                    value={gasDraftEconomy.reason}
                    disabled={!canWrite || savingEconomy}
                    placeholder="например bonus или refill"
                    onChange={(e) =>
                      setGasDraftEconomy((prev) => ({
                        ...prev,
                        reason: e.target.value,
                      }))
                    }
                  />
                </label>
              </div>
              <div className="admin-actions">
                <button
                  className="admin-primary"
                  onClick={handleApplyGasEconomy}
                  disabled={!canWrite || savingEconomy}
                >
                  {savingEconomy ? 'Сохранение…' : 'Применить ГАЗ'}
                </button>
              </div>

              <div className="admin-actions" style={{ marginTop: '18px' }}>
                <button
                  className="admin-secondary"
                  onClick={() => setEconomyOpen(false)}
                  disabled={savingEconomy}
                >
                  Закрыть
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {/* 13.7-h-2: блокировка/разблокировка игрока — модалка с reason.
            Отдельная от economy-модалки (не конфликтует с драфтами ROOT/ГАЗ);
            заголовок/действие зависят от текущего статуса игрока. */}
        {blockModalOpen && selectedPlayer ? (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 110,
              background: 'rgba(2, 8, 6, 0.66)',
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'center',
              overflowY: 'auto',
              padding: '40px 16px',
            }}
          >
            <div
              style={{
                background: '#0d1c18',
                border: '1px solid rgba(190, 255, 226, 0.24)',
                borderRadius: '12px',
                padding: '20px',
                width: 'min(560px, 100%)',
                boxShadow: '0 12px 40px rgba(0, 0, 0, 0.5)',
              }}
            >
              <p className="admin-kicker">PLAYER RESTRICTION</p>
              <h3 style={{ margin: '0 0 16px' }}>
                {selectedPlayer.player.status === 'blocked'
                  ? 'Разблокировать'
                  : 'Заблокировать'}
              </h3>

              {blockError && (
                <p className="admin-alert admin-error">{blockError}</p>
              )}
              {blockNotice && (
                <p className="admin-alert admin-notice">{blockNotice}</p>
              )}

              <p className="admin-kicker">ПРИЧИНА (АУДИТ)</p>
              <label>
                <input
                  type="text"
                  value={blockReason}
                  disabled={!canWrite || savingBlock}
                  placeholder={
                    selectedPlayer.player.status === 'blocked'
                      ? 'например, апелляция принята'
                      : 'например, мошенничество'
                  }
                  onChange={(e) => setBlockReason(e.target.value)}
                />
              </label>

              <div className="admin-actions">
                <button
                  className="admin-primary"
                  onClick={
                    selectedPlayer.player.status === 'blocked'
                      ? handleUnblockPlayer
                      : handleBlockPlayer
                  }
                  disabled={!canWrite || savingBlock}
                >
                  {savingBlock
                    ? 'Сохранение…'
                    : selectedPlayer.player.status === 'blocked'
                      ? 'Разблокировать'
                      : 'Заблокировать'}
                </button>
              </div>

              <div className="admin-actions" style={{ marginTop: '18px' }}>
                <button
                  className="admin-secondary"
                  onClick={closeBlockModal}
                  disabled={savingBlock}
                >
                  Закрыть
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  )
}
