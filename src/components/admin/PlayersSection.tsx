import { useEffect, useState, type CSSProperties } from 'react'
import {
  getPlayer,
  getProfileFields,
  listPlayers,
  type AdminPlayerCard,
  type AdminPlayerSummary,
  type AdminProfileField,
  type AdminUser,
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
  canWrite: _canWrite,
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
        if (!cancelled) setSelectedPlayer(card)
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

  function applyFilters() {
    setSearch(draftSearch)
    setStatus(draftStatus)
    setOffset(0)
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
                      value={fieldValue(selectedPlayer, field.key)}
                      disabled
                    >
                      {fieldValue(selectedPlayer, field.key) === '' && (
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
                      value={fieldValue(selectedPlayer, field.key)}
                      readOnly={field.readOnly}
                      disabled
                      maxLength={field.maxLength}
                      min={field.min}
                      max={field.max}
                    />
                  )}
                </label>
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
            </div>
          </>
        ) : null}
      </section>
    </div>
  )
}
