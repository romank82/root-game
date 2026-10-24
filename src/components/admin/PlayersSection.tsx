import { useEffect, useState, type CSSProperties } from 'react'
import {
  getPlayer,
  getPlayerGasTransactions,
  getProfileFields,
  listPlayers,
  updatePlayerGas,
  updatePlayerRoot,
  type AdminPlayerCard,
  type AdminPlayerSummary,
  type AdminProfileField,
  type AdminUser,
  type GasTransaction,
  type RootAdjustmentPayload,
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
  onNotice: _onNotice,
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

  // Карточка выбранного игрока.
  useEffect(() => {
    // 13.7-d: смена выбранного игрока закрывает модалку «Экономика игрока».
    setEconomyOpen(false)
    setEconomyError(null)
    setEconomyNotice(null)
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

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <div className="admin-editor-title">
          <div>
            <p className="admin-kicker">ROOT / PLAYERS</p>
            <h2>Игроки</h2>
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
              <div style={{ marginTop: '12px' }}>
                <button
                  className="admin-secondary"
                  onClick={openEconomyModal}
                  disabled={!canWrite || savingEconomy}
                >
                  Экономика игрока
                </button>
              </div>
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
      </section>
    </div>
  )
}
