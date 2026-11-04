import { Fragment, useEffect, useState, type CSSProperties } from 'react'
import {
  getErrorGroups,
  getMonitoringErrors,
  getMonitoringEvents,
  type MonitoringError,
  type MonitoringErrorGroup,
  type MonitoringEvent,
} from '../../api/adminApi'

type MonitoringSectionProps = {
  onError: (message: string) => void
  onNotice: (message: string) => void
}

const PAGE_SIZE = 50

/*
 * 13.5-b-2: фронт раздела «Мониторинг».
 * Read-only: ошибки фильтрации показываются ЛОКАЛЬНО через errorsError /
 * eventsError (не глобальный onError — чтобы сбой выборки Ошибок не выбивал
 * notice/alert всей админки). onNotice используется только по явному
 * действию пользователя (кнопка «Обновить»).
 */

type SeverityFilter = 'all' | 'error' | 'critical'
type PeriodFilter = 'all' | 'day' | 'week' | 'month'

const PERIOD_OPTIONS: { value: PeriodFilter; label: string }[] = [
  { value: 'all', label: 'all · всё время' },
  { value: 'day', label: 'day · 24 часа' },
  { value: 'week', label: 'week · 7 дней' },
  { value: 'month', label: 'month · 30 дней' },
]

const SEVERITY_OPTIONS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'error', label: 'error' },
  { value: 'critical', label: 'critical' },
]

const EVENT_TYPES = [
  'auth.login',
  'mission.accepted',
  'mission.completed',
  'transfer.completed',
  'gas.purchased',
] as const

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

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#ff8a9a',
  error: '#ffd479',
}

function groupKey(group: MonitoringErrorGroup): string {
  return `${group.errorType}|${group.endpoint ?? '∅'}|${group.statusCode ?? '∅'}`
}

export function MonitoringSection(_props: MonitoringSectionProps) {
  const [errors, setErrors] = useState<MonitoringError[]>([])
  const [errorsTotal, setErrorsTotal] = useState(0)
  const [errorsLoading, setErrorsLoading] = useState(false)
  const [errorsError, setErrorsError] = useState('')
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const [errorsPeriod, setErrorsPeriod] = useState<PeriodFilter>('all')
  const [correlationIdInput, setCorrelationIdInput] = useState('')
  const [correlationIdFilter, setCorrelationIdFilter] = useState('')
  const [errorsOffset, setErrorsOffset] = useState(0)
  const [errorsReload, setErrorsReload] = useState(0)

  const [activeTab, setActiveTab] = useState<'groups' | 'records'>('groups')
  const [groups, setGroups] = useState<MonitoringErrorGroup[]>([])
  const [groupsTotal, setGroupsTotal] = useState(0)
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [groupsError, setGroupsError] = useState('')
  const [groupsPeriod, setGroupsPeriod] = useState<PeriodFilter>('all')
  const [groupsSeverity, setGroupsSeverity] = useState<SeverityFilter>('all')
  const [groupsMinCount, setGroupsMinCount] = useState<number>(1)
  const [groupsOffset, setGroupsOffset] = useState(0)
  const [groupsReload, setGroupsReload] = useState(0)
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
  const [drilldownErrors, setDrilldownErrors] = useState<MonitoringError[]>([])
  const [drilldownLoading, setDrilldownLoading] = useState(false)
  const [drilldownError, setDrilldownError] = useState('')

  const [events, setEvents] = useState<MonitoringEvent[]>([])
  const [eventsTotal, setEventsTotal] = useState(0)
  const [eventsLoading, setEventsLoading] = useState(false)
  const [eventsError, setEventsError] = useState('')
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('all')
  const [eventsPeriod, setEventsPeriod] = useState<PeriodFilter>('all')
  const [playerIdFilter, setPlayerIdFilter] = useState('')
  const [eventsOffset, setEventsOffset] = useState(0)
  const [eventsReload, setEventsReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    setErrorsLoading(true)
    setErrorsError('')

    getMonitoringErrors({
      severity: severityFilter === 'all' ? undefined : severityFilter,
      period: errorsPeriod,
      correlationId: correlationIdFilter.trim() || undefined,
      limit: PAGE_SIZE,
      offset: errorsOffset,
    })
      .then((data) => {
        if (!cancelled) {
          setErrors(data.errors)
          setErrorsTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setErrorsError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить ошибки.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setErrorsLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [severityFilter, errorsPeriod, correlationIdFilter, errorsOffset, errorsReload])

  useEffect(() => {
    if (activeTab !== 'groups') return
    let cancelled = false
    setGroupsLoading(true)
    setGroupsError('')

    getErrorGroups({
      severity: groupsSeverity === 'all' ? undefined : groupsSeverity,
      period: groupsPeriod,
      minCount: groupsMinCount,
      limit: PAGE_SIZE,
      offset: groupsOffset,
    })
      .then((data) => {
        if (!cancelled) {
          setGroups(data.groups)
          setGroupsTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setGroupsError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить группы ошибок.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setGroupsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [
    activeTab,
    groupsSeverity,
    groupsPeriod,
    groupsMinCount,
    groupsOffset,
    groupsReload,
  ])

  useEffect(() => {
    if (!expandedGroup) {
      setDrilldownErrors([])
      setDrilldownError('')
      return
    }
    const group = groups.find((item) => groupKey(item) === expandedGroup)
    if (!group) return
    let cancelled = false
    setDrilldownLoading(true)
    setDrilldownError('')

    getMonitoringErrors({
      errorType: group.errorType,
      endpoint: group.endpoint ?? undefined,
      statusCode: group.statusCode ?? undefined,
      period: groupsPeriod,
      limit: PAGE_SIZE,
      offset: 0,
    })
      .then((data) => {
        if (!cancelled) setDrilldownErrors(data.errors)
      })
      .catch((requestError) => {
        if (!cancelled) {
          setDrilldownError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить ошибки группы.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setDrilldownLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedGroup, groups, groupsPeriod])

  useEffect(() => {
    let cancelled = false
    setEventsLoading(true)
    setEventsError('')

    getMonitoringEvents({
      eventType: eventTypeFilter === 'all' ? undefined : eventTypeFilter,
      playerId: playerIdFilter.trim() || undefined,
      period: eventsPeriod,
      limit: PAGE_SIZE,
      offset: eventsOffset,
    })
      .then((data) => {
        if (!cancelled) {
          setEvents(data.events)
          setEventsTotal(data.total)
        }
      })
      .catch((requestError) => {
        if (!cancelled) {
          setEventsError(
            requestError instanceof Error
              ? requestError.message
              : 'Не удалось загрузить события.',
          )
        }
      })
      .finally(() => {
        if (!cancelled) setEventsLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventTypeFilter, eventsPeriod, playerIdFilter, eventsOffset, eventsReload])

  const errorsShownFrom = errorsTotal === 0 ? 0 : errorsOffset + 1
  const errorsShownTo =
    errorsTotal === 0 ? 0 : Math.min(errorsOffset + PAGE_SIZE, errorsTotal)
  const groupsShownFrom = groupsTotal === 0 ? 0 : groupsOffset + 1
  const groupsShownTo =
    groupsTotal === 0 ? 0 : Math.min(groupsOffset + PAGE_SIZE, groupsTotal)
  const eventsShownFrom = eventsTotal === 0 ? 0 : eventsOffset + 1
  const eventsShownTo =
    eventsTotal === 0 ? 0 : Math.min(eventsOffset + PAGE_SIZE, eventsTotal)

  const tableStyle: CSSProperties = {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '12px',
    fontFamily: '"IBM Plex Mono", monospace',
  }

  return (
    <>
      <div className="admin-editor-title">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / MONITORING</p>
          <h2>Мониторинг</h2>
          <p className="admin-muted">
            Ошибки и события игровых операций (read-only).
          </p>
        </div>
      </div>

      <section className="admin-editor" style={{ marginTop: '24px' }}>
        <p className="admin-kicker">MONITORING / ERRORS</p>
        <h2 style={{ marginTop: '4px', marginBottom: '16px' }}>Ошибки</h2>

        <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
          <button
            className={
              activeTab === 'groups' ? 'admin-primary' : 'admin-secondary'
            }
            onClick={() => setActiveTab('groups')}
          >
            Группы
          </button>
          <button
            className={
              activeTab === 'records' ? 'admin-primary' : 'admin-secondary'
            }
            onClick={() => setActiveTab('records')}
          >
            Записи
          </button>
        </div>

        {activeTab === 'records' && (
          <>

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
            Severity
            <select
              value={severityFilter}
              onChange={(event) => {
                setSeverityFilter(event.target.value as SeverityFilter)
                setErrorsOffset(0)
              }}
            >
              {SEVERITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ flex: '0 0 190px' }}>
            Период
            <select
              value={errorsPeriod}
              onChange={(event) => {
                setErrorsPeriod(event.target.value as PeriodFilter)
                setErrorsOffset(0)
              }}
            >
              {PERIOD_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ flex: '1 1 260px' }}>
            Код ошибки (correlation_id)
            <input
              type="text"
              placeholder="Например: 3a5b941b…"
              value={correlationIdInput}
              onChange={(event) => setCorrelationIdInput(event.target.value)}
            />
          </label>
          <button
            className="admin-primary"
            onClick={() => {
              setCorrelationIdFilter(correlationIdInput.trim())
              setErrorsOffset(0)
              setErrorsReload((tick) => tick + 1)
            }}
            disabled={errorsLoading}
          >
            Найти
          </button>
          <button
            className="admin-secondary"
            onClick={() => {
              setCorrelationIdInput('')
              setCorrelationIdFilter('')
              setErrorsOffset(0)
              setErrorsReload((tick) => tick + 1)
            }}
            disabled={errorsLoading}
          >
            Сбросить
          </button>
          <button
            className="admin-primary"
            onClick={() => {
              setErrorsOffset(0)
              setErrorsReload((tick) => tick + 1)
              _props.onNotice('Ошибки обновлены.')
            }}
            disabled={errorsLoading}
          >
            Обновить
          </button>
        </div>

        {errorsLoading && <p className="admin-muted">Загрузка ошибок…</p>}

        {errorsError && <p className="admin-alert admin-error">{errorsError}</p>}

        {!errorsLoading && errors.length === 0 && !errorsError && (
          <p className="admin-muted">Ошибок не найдено.</p>
        )}

        {!errorsLoading && errors.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Дата</th>
                  <th style={thStyle}>Severity</th>
                  <th style={thStyle}>Тип</th>
                  <th style={thStyle}>Сообщение</th>
                  <th style={thStyle}>CorrelationId</th>
                </tr>
              </thead>
              <tbody>
                {errors.map((error) => (
                  <tr key={error.id}>
                    <td style={tdStyle}>{formatDate(error.createdAt)}</td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          color: SEVERITY_COLORS[error.severity] ?? '#8aac9d',
                        }}
                      >
                        {error.severity}
                      </span>
                    </td>
                    <td style={tdStyle}>{error.errorType}</td>
                    <td style={tdStyle}>{error.message}</td>
                    <td style={tdStyle}>{error.correlationId}</td>
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
            onClick={() =>
              setErrorsOffset(Math.max(0, errorsOffset - PAGE_SIZE))
            }
            disabled={errorsLoading || errorsOffset === 0}
          >
            ← Назад
          </button>
          <span className="admin-muted">
            Показано {errorsShownFrom}–{errorsShownTo} из {errorsTotal}
          </span>
          <button
            className="admin-secondary"
            onClick={() => setErrorsOffset(errorsOffset + PAGE_SIZE)}
            disabled={errorsLoading || errorsOffset + PAGE_SIZE >= errorsTotal}
          >
            Вперёд →
          </button>
        </div>
          </>
        )}

        {activeTab === 'groups' && (
          <>
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
                  value={groupsPeriod}
                  onChange={(event) => {
                    setGroupsPeriod(event.target.value as PeriodFilter)
                    setGroupsOffset(0)
                    setExpandedGroup(null)
                  }}
                >
                  {PERIOD_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: '0 0 150px' }}>
                Severity
                <select
                  value={groupsSeverity}
                  onChange={(event) => {
                    setGroupsSeverity(event.target.value as SeverityFilter)
                    setGroupsOffset(0)
                    setExpandedGroup(null)
                  }}
                >
                  {SEVERITY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: '0 0 130px' }}>
                Min count
                <input
                  type="number"
                  min={1}
                  value={groupsMinCount}
                  onChange={(event) => {
                    const parsed = Number(event.target.value)
                    setGroupsMinCount(
                      Number.isFinite(parsed) && parsed >= 1 ? parsed : 1,
                    )
                    setGroupsOffset(0)
                    setExpandedGroup(null)
                  }}
                />
              </label>
              <button
                className="admin-primary"
                onClick={() => {
                  setGroupsOffset(0)
                  setGroupsReload((tick) => tick + 1)
                  setExpandedGroup(null)
                  _props.onNotice('Группы ошибок обновлены.')
                }}
                disabled={groupsLoading}
              >
                Обновить
              </button>
            </div>

            {groupsLoading && <p className="admin-muted">Загрузка групп…</p>}

            {groupsError && (
              <p className="admin-alert admin-error">{groupsError}</p>
            )}

            {!groupsLoading && groups.length === 0 && !groupsError && (
              <p className="admin-muted">Групп ошибок не найдено.</p>
            )}

            {!groupsLoading && groups.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>Тип ошибки</th>
                      <th style={thStyle}>Endpoint</th>
                      <th style={thStyle}>Кол-во</th>
                      <th style={thStyle}>Игроков</th>
                      <th style={thStyle}>Последний раз</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((group) => {
                      const key = groupKey(group)
                      const isExpanded = expandedGroup === key
                      return (
                        <Fragment key={key}>
                          <tr
                            onClick={() =>
                              setExpandedGroup(isExpanded ? null : key)
                            }
                            style={{
                              cursor: 'pointer',
                              background: group.isGlobal
                                ? 'rgba(255, 138, 154, 0.12)'
                                : undefined,
                            }}
                          >
                            <td style={tdStyle}>
                              {group.isGlobal && (
                                <span
                                  style={{
                                    color: '#ff8a9a',
                                    fontWeight: 700,
                                    marginRight: '8px',
                                  }}
                                >
                                  GLOBAL
                                </span>
                              )}
                              {group.errorType}
                            </td>
                            <td style={tdStyle}>{group.endpoint ?? '—'}</td>
                            <td style={tdStyle}>
                              <b>{group.count}</b>
                            </td>
                            <td style={tdStyle}>{group.affectedPlayers}</td>
                            <td style={tdStyle}>{formatDate(group.lastSeen)}</td>
                          </tr>
                          {isExpanded && (
                            <tr>
                              <td colSpan={5} style={{ padding: '12px 16px' }}>
                                {drilldownLoading ? (
                                  <span className="admin-muted">
                                    Загрузка ошибок…
                                  </span>
                                ) : drilldownError ? (
                                  <span className="admin-alert admin-error">
                                    {drilldownError}
                                  </span>
                                ) : drilldownErrors.length === 0 ? (
                                  <span className="admin-muted">
                                    Ошибок не найдено.
                                  </span>
                                ) : (
                                  <table style={tableStyle}>
                                    <thead>
                                      <tr>
                                        <th style={thStyle}>Дата</th>
                                        <th style={thStyle}>Severity</th>
                                        <th style={thStyle}>Сообщение</th>
                                        <th style={thStyle}>CorrelationId</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {drilldownErrors.map((error) => (
                                        <tr key={error.id}>
                                          <td style={tdStyle}>
                                            {formatDate(error.createdAt)}
                                          </td>
                                          <td style={tdStyle}>
                                            <span
                                              style={{
                                                color:
                                                  SEVERITY_COLORS[
                                                    error.severity
                                                  ] ?? '#8aac9d',
                                              }}
                                            >
                                              {error.severity}
                                            </span>
                                          </td>
                                          <td style={tdStyle}>
                                            {error.message}
                                          </td>
                                          <td style={tdStyle}>
                                            {error.correlationId}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
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
                onClick={() =>
                  setGroupsOffset(Math.max(0, groupsOffset - PAGE_SIZE))
                }
                disabled={groupsLoading || groupsOffset === 0}
              >
                ← Назад
              </button>
              <span className="admin-muted">
                Показано {groupsShownFrom}–{groupsShownTo} из {groupsTotal}
              </span>
              <button
                className="admin-secondary"
                onClick={() => setGroupsOffset(groupsOffset + PAGE_SIZE)}
                disabled={
                  groupsLoading || groupsOffset + PAGE_SIZE >= groupsTotal
                }
              >
                Вперёд →
              </button>
            </div>
          </>
        )}
      </section>

      <section className="admin-editor" style={{ marginTop: '24px' }}>
        <p className="admin-kicker">MONITORING / EVENTS</p>
        <h2 style={{ marginTop: '4px', marginBottom: '16px' }}>События</h2>

        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'end',
            gap: '12px',
            marginBottom: '16px',
          }}
        >
          <label style={{ flex: '0 0 220px' }}>
            Event Type
            <select
              value={eventTypeFilter}
              onChange={(event) => {
                setEventTypeFilter(event.target.value)
                setEventsOffset(0)
              }}
            >
              <option value="all">Все</option>
              {EVENT_TYPES.map((eventType) => (
                <option key={eventType} value={eventType}>
                  {eventType}
                </option>
              ))}
            </select>
          </label>
          <label style={{ flex: '0 0 190px' }}>
            Период
            <select
              value={eventsPeriod}
              onChange={(event) => {
                setEventsPeriod(event.target.value as PeriodFilter)
                setEventsOffset(0)
              }}
            >
              {PERIOD_OPTIONS.map((option) => (
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
                setEventsOffset(0)
              }}
              placeholder="например, player-3ab12cd4ef"
            />
          </label>
          <button
            className="admin-primary"
            onClick={() => {
              setEventsOffset(0)
              setEventsReload((tick) => tick + 1)
              _props.onNotice('События обновлены.')
            }}
            disabled={eventsLoading}
          >
            Обновить
          </button>
        </div>

        {eventsLoading && <p className="admin-muted">Загрузка событий…</p>}

        {eventsError && <p className="admin-alert admin-error">{eventsError}</p>}

        {!eventsLoading && events.length === 0 && !eventsError && (
          <p className="admin-muted">Событий не найдено.</p>
        )}

        {!eventsLoading && events.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Дата</th>
                  <th style={thStyle}>PlayerId</th>
                  <th style={thStyle}>EventType</th>
                  <th style={thStyle}>CorrelationId</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td style={tdStyle}>{formatDate(event.createdAt)}</td>
                    <td style={tdStyle}>{event.playerId}</td>
                    <td style={tdStyle}>{event.eventType}</td>
                    <td style={tdStyle}>{event.correlationId ?? '—'}</td>
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
            onClick={() =>
              setEventsOffset(Math.max(0, eventsOffset - PAGE_SIZE))
            }
            disabled={eventsLoading || eventsOffset === 0}
          >
            ← Назад
          </button>
          <span className="admin-muted">
            Показано {eventsShownFrom}–{eventsShownTo} из {eventsTotal}
          </span>
          <button
            className="admin-secondary"
            onClick={() => setEventsOffset(eventsOffset + PAGE_SIZE)}
            disabled={eventsLoading || eventsOffset + PAGE_SIZE >= eventsTotal}
          >
            Вперёд →
          </button>
        </div>
      </section>
    </>
  )
}