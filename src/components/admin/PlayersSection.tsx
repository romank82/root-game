import { useEffect, useState, type CSSProperties } from 'react'
import {
  getPlayer,
  getPlayerGasTransactions,
  getProfileFields,
  listPlayers,
  updatePlayerGas,
  updatePlayerProfile,
  type AdminPlayerCard,
  type AdminPlayerSummary,
  type AdminProfileField,
  type AdminUser,
  type GasTransaction,
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

// Снимок редактируемых полей карточки (значения строк — как в форме).
function snapshotProfile(card: AdminPlayerCard): Record<string, string> {
  return {
    nickname: fieldValue(card, 'nickname'),
    country: fieldValue(card, 'country'),
    gender: fieldValue(card, 'gender'),
    age: fieldValue(card, 'age'),
  }
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

  // Драфт редактируемых полей профиля — применяется кнопкой «Сохранить».
  const [draftProfile, setDraftProfile] = useState<Record<string, string>>({})
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingProfileError, setSavingProfileError] = useState<string | null>(
    null,
  )
  const [savingProfileNotice, setSavingProfileNotice] = useState<string | null>(
    null,
  )

  // Газ (10.4-e-2): драфт формы, статусы и история (последние 50).
  const [gasDraft, setGasDraft] = useState<{ amount: string; reason: string }>({
    amount: '',
    reason: '',
  })
  const [savingGas, setSavingGas] = useState(false)
  const [savingGasError, setSavingGasError] = useState<string | null>(null)
  const [savingGasNotice, setSavingGasNotice] = useState<string | null>(null)
  const [gasTransactions, setGasTransactions] = useState<GasTransaction[]>([])

  // Поля форм профиля — один раз на mount.
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
          setDraftProfile(snapshotProfile(card))
          setSavingProfileNotice(null)
          setSavingProfileError(null)
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

  function handleResetProfile() {
    if (!selectedPlayer) return
    setDraftProfile(snapshotProfile(selectedPlayer))
    setSavingProfileError(null)
    setSavingProfileNotice(null)
  }

  async function handleSaveProfile() {
    if (!selectedPlayer) return

    const rawCountry = (draftProfile.country ?? '').trim()
    const rawGender = (draftProfile.gender ?? '').trim()
    const rawAge = (draftProfile.age ?? '').trim()
    const ageField = profileFields.find((field) => field.key === 'age')
    const genderField = profileFields.find((field) => field.key === 'gender')
    const countryField = profileFields.find((field) => field.key === 'country')

    // Возраст: целое число в диапазоне из конфига полей (10.0.4).
    if (rawAge !== '') {
      const age = Number(rawAge)
      const minAge = ageField?.min ?? 0
      const maxAge = ageField?.max ?? 120
      if (!Number.isInteger(age) || age < minAge || age > maxAge) {
        setSavingProfileError(
          `Возраст должен быть целым числом от ${minAge} до ${maxAge}.`,
        )
        return
      }
    }

    // Пол: только из набора options конфига.
    if (rawGender !== '' && genderField && !genderField.options?.includes(rawGender)) {
      setSavingProfileError(`Недопустимое значение пола: ${rawGender}.`)
      return
    }

    // Страна: ISO-2 (2 буквы), ограничение из конфига.
    if (
      rawCountry !== '' &&
      countryField?.maxLength !== undefined &&
      rawCountry.length > countryField.maxLength
    ) {
      setSavingProfileError(
        `Страна — ISO-2: максимум ${countryField.maxLength} буквы.`,
      )
      return
    }

    setSavingProfile(true)
    setSavingProfileError(null)
    setSavingProfileNotice(null)
    try {
      const updated = await updatePlayerProfile(selectedPlayer.player.id, {
        country: rawCountry === '' ? null : rawCountry,
        gender: rawGender === '' ? null : rawGender,
        age: rawAge === '' ? null : Number(rawAge),
      })
      setSelectedPlayer(updated)
      setDraftProfile(snapshotProfile(updated))
      setSavingProfileNotice('Профиль сохранён.')
    } catch (err) {
      setSavingProfileError((err as Error).message)
    } finally {
      setSavingProfile(false)
    }
  }

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
            <div className="admin-grid">
              {profileFields.map((field) => (
                <label key={field.key} className="admin-span-2">
                  {field.label}
                  {field.type === 'select' ? (
                    <select
                      value={
                        draftProfile[field.key] ?? fieldValue(selectedPlayer, field.key)
                      }
                      disabled={!canWrite || savingProfile}
                      onChange={(e) =>
                        setDraftProfile((prev) => ({
                          ...prev,
                          [field.key]: e.target.value,
                        }))
                      }
                    >
                      {(draftProfile[field.key] ??
                        fieldValue(selectedPlayer, field.key)) === '' && (
                        <option value="">—</option>
                      )}
                      {(field.options ?? []).map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={field.type}
                      value={
                        draftProfile[field.key] ?? fieldValue(selectedPlayer, field.key)
                      }
                      readOnly={field.readOnly}
                      disabled={!canWrite || savingProfile}
                      maxLength={field.maxLength}
                      min={field.min}
                      max={field.max}
                      onChange={(e) =>
                        setDraftProfile((prev) => ({
                          ...prev,
                          [field.key]: e.target.value,
                        }))
                      }
                    />
                  )}
                </label>
              ))}
            </div>

            <div className="admin-actions">
              <button
                className="admin-primary"
                onClick={handleSaveProfile}
                disabled={!canWrite || savingProfile}
              >
                {savingProfile ? 'Сохранение…' : 'Сохранить'}
              </button>
              <button
                className="admin-secondary"
                onClick={handleResetProfile}
                disabled={savingProfile}
              >
                Отмена
              </button>
            </div>

            {savingProfileError && (
              <p className="admin-alert admin-error">{savingProfileError}</p>
            )}
            {savingProfileNotice && (
              <p className="admin-alert admin-notice">{savingProfileNotice}</p>
            )}

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
      </section>
    </div>
  )
}
