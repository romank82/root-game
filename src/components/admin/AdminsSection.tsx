import { useEffect, useState } from 'react'
import {
  PERMISSION_CATALOG,
  createAdmin,
  deactivateAdmin,
  grantPermission,
  listAdmins,
  reactivateAdmin,
  revokePermission,
  type AdminUser,
  type AdminUserFull,
  type PermissionCatalogEntry,
} from '../../api/adminApi'

type AdminsSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

export function AdminsSection({
  admin,
  canWrite: _canWrite,
  onError: _onError,
  onNotice: _onNotice,
}: AdminsSectionProps) {
  const [adminsList, setAdminsList] = useState<AdminUserFull[]>([])
  const [selectedAdminId, setSelectedAdminId] = useState<string | null>(null)
  const [loadingAdmins, setLoadingAdmins] = useState(false)
  const [adminsError, setAdminsError] = useState<string | null>(null)
  const [permReason, setPermReason] = useState<string>('')
  const [permSaving, setPermSaving] = useState<string | null>(null)
  const [permError, setPermError] = useState<string | null>(null)
  const [showCreateAdmin, setShowCreateAdmin] = useState(false)
  const [newAdminUsername, setNewAdminUsername] = useState('')
  const [newAdminPassword, setNewAdminPassword] = useState('')
  const [creatingAdmin, setCreatingAdmin] = useState(false)
  const [createAdminError, setCreateAdminError] = useState<string | null>(null)
  const [deactivateReason, setDeactivateReason] = useState('')
  const [togglingActive, setTogglingActive] = useState(false)
  const [activeError, setActiveError] = useState<string | null>(null)

  useEffect(() => {
    if (!(admin?.isSuperAdmin ?? false)) return
    let cancelled = false
    setLoadingAdmins(true)
    setAdminsError(null)
    listAdmins()
      .then((data) => {
        if (cancelled) return
        setAdminsList(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setAdminsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingAdmins(false)
      })
    return () => {
      cancelled = true
    }
  }, [admin])

  useEffect(() => {
    setPermReason('')
    setPermError(null)
    setPermSaving(null)
    setShowCreateAdmin(false)
    setCreateAdminError(null)
    setDeactivateReason('')
    setActiveError('')
  }, [selectedAdminId])

  function selectedAdmin(): AdminUserFull | null {
    if (selectedAdminId === null) return null
    return adminsList.find((a) => a.id === selectedAdminId) ?? null
  }

  async function handleTogglePermission(
    target: AdminUserFull,
    permissionCode: string,
    currentlyGranted: boolean,
  ) {
    if (target.isSuperAdmin) return
    setPermSaving(permissionCode)
    setPermError(null)
    try {
      const updated = currentlyGranted
        ? await revokePermission(target.id, permissionCode)
        : await grantPermission(target.id, {
            permission_code: permissionCode,
            reason: permReason.trim() || undefined,
          })
      setAdminsList((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
    } catch (err) {
      setPermError((err as Error).message)
    } finally {
      setPermSaving(null)
    }
  }

  async function handleCreateAdmin() {
    const username = newAdminUsername.trim()
    if (username.length < 3) {
      setCreateAdminError('Username минимум 3 символа.')
      return
    }
    if (newAdminPassword.length < 12) {
      setCreateAdminError('Пароль минимум 12 символов.')
      return
    }
    setCreatingAdmin(true)
    setCreateAdminError(null)
    try {
      const created = await createAdmin({
        username,
        password: newAdminPassword,
      })
      setAdminsList((prev) =>
        [...prev, created].sort((a, b) =>
          a.username.localeCompare(b.username),
        ),
      )
      setSelectedAdminId(created.id)
      setShowCreateAdmin(false)
      setNewAdminUsername('')
      setNewAdminPassword('')
    } catch (err) {
      setCreateAdminError((err as Error).message)
    } finally {
      setCreatingAdmin(false)
    }
  }

  async function handleDeactivate(target: AdminUserFull) {
    const reason = deactivateReason.trim()
    if (reason.length < 3) {
      setActiveError('Причина минимум 3 символа.')
      return
    }
    setTogglingActive(true)
    setActiveError(null)
    try {
      const updated = await deactivateAdmin(target.id, reason)
      setAdminsList((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
      setDeactivateReason('')
    } catch (err) {
      setActiveError((err as Error).message)
    } finally {
      setTogglingActive(false)
    }
  }

  async function handleReactivate(target: AdminUserFull) {
    setTogglingActive(true)
    setActiveError(null)
    try {
      const updated = await reactivateAdmin(target.id)
      setAdminsList((prev) =>
        prev.map((x) => (x.id === updated.id ? updated : x)),
      )
    } catch (err) {
      setActiveError((err as Error).message)
    } finally {
      setTogglingActive(false)
    }
  }

  return (
        <div className="admin-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-primary"
              onClick={() => {
                setShowCreateAdmin(true)
                setCreateAdminError(null)
                setNewAdminUsername('')
                setNewAdminPassword('')
              }}
            >
              + Новый админ
            </button>

            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedAdminId(null)
                setAdminsList([])
                setAdminsError(null)
                setLoadingAdmins(true)
                listAdmins()
                  .then(setAdminsList)
                  .catch((err: Error) => setAdminsError(err.message))
                  .finally(() => setLoadingAdmins(false))
              }}
              disabled={loadingAdmins}
            >
              {loadingAdmins ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {adminsError && (
              <p className="admin-alert admin-error">{adminsError}</p>
            )}

            <div className="admin-mission-list">
              {adminsList.map((a) => (
                <button
                  className={`admin-mission-row ${selectedAdminId === a.id ? 'is-active' : ''}`}
                  key={a.id}
                  onClick={() => setSelectedAdminId(a.id)}
                >
                  {a.isSuperAdmin && (
                    <span className="admin-badge admin-badge-super">super</span>
                  )}
                  {!a.isActive && (
                    <span className="admin-badge admin-badge-inactive">
                      выключен
                    </span>
                  )}
                  {a.isDeleted && (
                    <span className="admin-badge admin-badge-deleted">
                      удалён
                    </span>
                  )}
                  <strong>{a.username}</strong>
                  <small>
                    {a.permissions.filter((p) => p.isActive).length} прав
                  </small>
                </button>
              ))}
              {!loadingAdmins && adminsList.length === 0 && !adminsError && (
                <p className="admin-muted">Админов нет.</p>
              )}
            </div>
          </aside>

          <section className="admin-editor">
            {showCreateAdmin ? (
              <>
                <div className="admin-editor-title">
                  <h2>Новый администратор</h2>
                </div>

                {createAdminError && (
                  <p className="admin-alert admin-error">
                    {createAdminError}
                  </p>
                )}

                <label className="admin-field">
                  <span>Username (3–64, строчные буквы, цифры, . _ -)</span>
                  <input
                    type="text"
                    value={newAdminUsername}
                    onChange={(e) => setNewAdminUsername(e.target.value)}
                    maxLength={64}
                    disabled={creatingAdmin}
                  />
                </label>

                <label className="admin-field">
                  <span>Пароль (минимум 12 символов)</span>
                  <input
                    type="password"
                    value={newAdminPassword}
                    onChange={(e) => setNewAdminPassword(e.target.value)}
                    maxLength={1024}
                    disabled={creatingAdmin}
                  />
                </label>

                <div className="admin-actions">
                  <button
                    className="admin-primary"
                    onClick={handleCreateAdmin}
                    disabled={creatingAdmin}
                  >
                    {creatingAdmin ? 'Создание…' : 'Создать'}
                  </button>
                  <button
                    className="admin-secondary"
                    onClick={() => setShowCreateAdmin(false)}
                    disabled={creatingAdmin}
                  >
                    Отмена
                  </button>
                </div>

                <p className="admin-muted" style={{ marginTop: 24 }}>
                  Новый админ создаётся без прав. Права выдаются после
                  создания. Учётная запись всегда обычного админа (супер-админ
                  создаётся только через отдельную процедуру).
                </p>
              </>
            ) : selectedAdmin() === null ? (
              <p className="admin-muted">Выберите администратора слева.</p>
            ) : (
              (() => {
                const a = selectedAdmin()!
                return (
                  <>
                    <div className="admin-editor-title">
                      <h2>{a.username}</h2>
                      {a.isSuperAdmin && (
                        <span className="admin-badge admin-badge-super">
                          super
                        </span>
                      )}
                      {!a.isActive && (
                        <span className="admin-badge admin-badge-inactive">
                          выключен
                        </span>
                      )}
                      {a.isDeleted && (
                        <span className="admin-badge admin-badge-deleted">
                          удалён
                        </span>
                      )}
                    </div>

                    {!a.isSuperAdmin && (
                      <div style={{ marginTop: 16 }}>
                        {activeError && (
                          <p className="admin-alert admin-error">
                            {activeError}
                          </p>
                        )}
                        {a.isActive ? (
                          <div className="admin-field">
                            <span>
                              Деактивация (админ сохранится в БД, но не сможет
                              войти)
                            </span>
                            <input
                              type="text"
                              value={deactivateReason}
                              onChange={(e) =>
                                setDeactivateReason(e.target.value)
                              }
                              placeholder="Причина (мин. 3 символа)"
                              maxLength={4000}
                              disabled={togglingActive}
                            />
                            <div
                              className="admin-actions"
                              style={{ marginTop: 8 }}
                            >
                              <button
                                className="admin-secondary"
                                onClick={() => handleDeactivate(a)}
                                disabled={
                                  togglingActive ||
                                  deactivateReason.trim().length < 3
                                }
                              >
                                {togglingActive
                                  ? 'Выключение…'
                                  : 'Выключить доступ'}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="admin-actions">
                            <button
                              className="admin-primary"
                              onClick={() => handleReactivate(a)}
                              disabled={togglingActive}
                            >
                              {togglingActive
                                ? 'Включение…'
                                : 'Включить доступ'}
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                    <p className="admin-muted">
                      <b>ID:</b> <code>{a.id}</code>
                    </p>
                    <p className="admin-muted">
                      <b>Создан:</b> {a.createdAt ?? '—'} ·{' '}
                      <b>Последний вход:</b> {a.lastLoginAt ?? '—'}
                    </p>
                    {a.deactivationReason && (
                      <p className="admin-muted">
                        <b>Причина деактивации:</b> {a.deactivationReason}
                      </p>
                    )}

                    <h3 style={{ marginTop: 24 }}>Права</h3>

                    {a.isSuperAdmin && (
                      <p className="admin-alert admin-notice">
                        Супер-админ имеет все права. Индивидуальные permissions
                        не настраиваются.
                      </p>
                    )}

                    {!a.isSuperAdmin && (
                      <>
                        {permError && (
                          <p className="admin-alert admin-error">
                            {permError}
                          </p>
                        )}

                        <label className="admin-field">
                          <span>
                            Причина изменения (для аудита, необязательно)
                          </span>
                          <input
                            type="text"
                            value={permReason}
                            onChange={(e) =>
                              setPermReason(e.target.value)
                            }
                            maxLength={200}
                            disabled={permSaving !== null}
                          />
                        </label>

                        <div className="admin-permissions">
                          {PERMISSION_CATALOG.map(
                            (p: PermissionCatalogEntry) => {
                              const grant = a.permissions.find(
                                (g) =>
                                  g.permissionCode === p.code && g.isActive,
                              )
                              const isSaving = permSaving === p.code
                              return (
                                <label
                                  key={p.code}
                                  className="admin-permission-row"
                                >
                                  <input
                                    type="checkbox"
                                    checked={!!grant}
                                    onChange={() =>
                                      handleTogglePermission(
                                        a,
                                        p.code,
                                        !!grant,
                                      )
                                    }
                                    disabled={isSaving}
                                  />
                                  <span className="admin-permission-title">
                                    {p.title}
                                    {isSaving && ' …'}
                                  </span>
                                  <code className="admin-permission-code">
                                    {p.code}
                                  </code>
                                  {grant &&
                                    grant.executionMode !== 'direct' && (
                                      <span className="admin-badge admin-badge-approval">
                                        {grant.executionMode}
                                      </span>
                                    )}
                                </label>
                              )
                            },
                          )}
                        </div>
                      </>
                    )}
                  </>
                )
              })()
            )}
          </section>
        </div>
  )
}
