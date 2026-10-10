import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import './AdminApp.css'
import {
  createAdmin,
  createAdminMission,
  deactivateAdmin,
  getAdminMe,
  grantPermission,
  listAdminMissions,
  listAdmins,
  listSystemSettings,
  loginAdmin,
  logoutAdmin,
  publishAdminMission,
  reactivateAdmin,
  revokePermission,
  unpublishAdminMission,
  updateAdminMission,
  updateSystemSetting,
  PERMISSION_CATALOG,
  type AdminMission,
  type AdminMissionPayload,
  type AdminSystemSetting,
  type AdminUser,
  type AdminUserFull,
  type PermissionCatalogEntry,
} from './api/adminApi'

type RewardForm = {
  rewardType: string
  amount: string
  itemId: string
  storyNodeId: string
  rewardValue: string
  sortOrder: string
}

type MissionForm = {
  chapterId: string
  storyNodeId: string
  slug: string
  missionType: string
  title: string
  description: string
  content: string
  validationConfig: string
  sortOrder: string
  rewards: RewardForm[]
}

const emptyReward = (): RewardForm => ({
  rewardType: 'currency',
  amount: '1',
  itemId: '',
  storyNodeId: '',
  rewardValue: '{"currency":"ROOT"}',
  sortOrder: '0',
})

const emptyForm = (): MissionForm => ({
  chapterId: '',
  storyNodeId: '',
  slug: '',
  missionType: 'text_answer',
  title: '',
  description: '',
  content: '{}',
  validationConfig:
    '{"validator":"normalized_text_match","acceptedAnswers":[]}',
  sortOrder: '0',
  rewards: [emptyReward()],
})

function prettyJson(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2)
}

function formFromMission(mission: AdminMission): MissionForm {
  return {
    chapterId: mission.chapterId,
    storyNodeId: mission.storyNodeId ?? '',
    slug: mission.slug,
    missionType: mission.missionType,
    title: mission.title,
    description: mission.description ?? '',
    content: prettyJson(mission.content),
    validationConfig: prettyJson(mission.validationConfig),
    sortOrder: String(mission.sortOrder),
    rewards: mission.rewards.map((reward) => ({
      rewardType: reward.rewardType,
      amount: reward.amount === null ? '' : String(reward.amount),
      itemId: reward.itemId ?? '',
      storyNodeId: reward.storyNodeId ?? '',
      rewardValue: prettyJson(reward.rewardValue),
      sortOrder: String(reward.sortOrder),
    })),
  }
}

function parseObject(value: string, label: string): Record<string, unknown> {
  let parsed: unknown

  try {
    parsed = JSON.parse(value)
  } catch {
    throw new Error(`${label}: введите корректный JSON.`)
  }

  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label}: ожидается JSON-объект.`)
  }

  return parsed as Record<string, unknown>
}

function formToPayload(form: MissionForm): AdminMissionPayload {
  const rewards = form.rewards.map((reward) => ({
    reward_type: reward.rewardType.trim(),
    amount: reward.amount.trim() ? Number(reward.amount) : null,
    item_id: reward.itemId.trim() || null,
    story_node_id: reward.storyNodeId.trim() || null,
    reward_value: parseObject(reward.rewardValue, 'Reward value'),
    sort_order: Number(reward.sortOrder || 0),
  }))

  return {
    chapter_id: form.chapterId.trim(),
    story_node_id: form.storyNodeId.trim() || null,
    slug: form.slug.trim(),
    mission_type: form.missionType.trim(),
    title: form.title.trim(),
    description: form.description.trim() || null,
    content: parseObject(form.content, 'Content'),
    validation_config: parseObject(
      form.validationConfig,
      'Validation config',
    ),
    sort_order: Number(form.sortOrder || 0),
    rewards,
  }
}

function AdminApp() {
  const [admin, setAdmin] = useState<AdminUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMissions, setLoadingMissions] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [missions, setMissions] = useState<AdminMission[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [form, setForm] = useState<MissionForm>(emptyForm)
  const [section, setSection] = useState<'missions' | 'settings' | 'admins'>(
    () =>
      (localStorage.getItem('chimera-admin-section') as
        | 'missions'
        | 'settings'
        | 'admins') ?? 'missions',
  )
  const [settings, setSettings] = useState<AdminSystemSetting[]>([])
  const [selectedSettingKey, setSelectedSettingKey] = useState<string | null>(
    null,
  )
  const [loadingSettings, setLoadingSettings] = useState(false)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [settingDraft, setSettingDraft] = useState<string>('')
  const [settingReason, setSettingReason] = useState<string>('')
  const [savingSetting, setSavingSetting] = useState(false)
  const [savingError, setSavingError] = useState<string | null>(null)
  const [savingNotice, setSavingNotice] = useState<string | null>(null)
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
    localStorage.setItem('chimera-admin-section', section)
  }, [section])

  useEffect(() => {
    if (section !== 'settings') return
    let cancelled = false
    setLoadingSettings(true)
    setSettingsError(null)
    listSystemSettings()
      .then((data) => {
        if (cancelled) return
        setSettings(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setSettingsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingSettings(false)
      })
    return () => {
      cancelled = true
    }
  }, [section])

  useEffect(() => {
    if (section !== 'settings') return
    if (selectedSettingKey !== null) return
    if (settings.length === 0) return
    setSelectedSettingKey(settings[0].key)
  }, [section, settings, selectedSettingKey])

  useEffect(() => {
    if (section !== 'admins') return
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
  }, [section, admin])

  useEffect(() => {
    setPermReason('')
    setPermError(null)
    setPermSaving(null)
    setShowCreateAdmin(false)
    setCreateAdminError(null)
    setDeactivateReason('')
    setActiveError('')
  }, [selectedAdminId])

  useEffect(() => {
    if (selectedSettingKey === null) {
      setSettingDraft('')
      setSettingReason('')
      setSavingError(null)
      setSavingNotice(null)
      return
    }
    const s = settings.find((x) => x.key === selectedSettingKey)
    if (!s) return
    if (s.valueType === 'boolean') {
      setSettingDraft(s.value === true ? 'true' : 'false')
    } else if (s.valueType === 'integer') {
      setSettingDraft(String(s.value ?? 0))
    } else if (s.valueType === 'string') {
      setSettingDraft(typeof s.value === 'string' ? s.value : '')
    } else {
      setSettingDraft(JSON.stringify(s.value, null, 2))
    }
    setSettingReason('')
    setSavingError(null)
    setSavingNotice(null)
  }, [selectedSettingKey, settings])

  const selectedMission = useMemo(
    () => missions.find((mission) => mission.id === selectedId) ?? null,
    [missions, selectedId],
  )

  const canWrite =
    admin?.isSuperAdmin === true ||
    admin?.role === 'owner' ||
    admin?.role === 'editor'

  async function refreshMissions() {
    setLoadingMissions(true)

    try {
      const nextMissions = await listAdminMissions()
      setMissions(nextMissions)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось загрузить миссии.',
      )
    } finally {
      setLoadingMissions(false)
    }
  }

  useEffect(() => {
    getAdminMe()
      .then(async (currentAdmin) => {
        setAdmin(currentAdmin)
        await refreshMissions()
      })
      .catch(() => {
        setAdmin(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const groupedSettings = useMemo(() => {
    const groups = new Map<string, AdminSystemSetting[]>()
    for (const s of settings) {
      const arr = groups.get(s.category) ?? []
      arr.push(s)
      groups.set(s.category, arr)
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [settings])

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

  function selectMission(mission: AdminMission) {
    setSelectedId(mission.id)
    setForm(formFromMission(mission))
    setError('')
    setNotice('')
  }

  function startNewMission() {
    setSelectedId(null)
    setForm(emptyForm())
    setError('')
    setNotice('')
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      await loginAdmin(username, password)
      setPassword('')
      const currentAdmin = await getAdminMe()
      setAdmin(currentAdmin)
      await refreshMissions()
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось выполнить вход.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function handleLogout() {
    setError('')

    try {
      await logoutAdmin()
    } catch {
      // Cookie might already be absent; local UI state still must be cleared.
    }

    setAdmin(null)
    setMissions([])
    setSelectedId(null)
    setForm(emptyForm())
    setNotice('')
  }

  function changeReward(
    index: number,
    field: keyof RewardForm,
    value: string,
  ) {
    setForm((current) => ({
      ...current,
      rewards: current.rewards.map((reward, rewardIndex) =>
        rewardIndex === index ? { ...reward, [field]: value } : reward,
      ),
    }))
  }

  function addReward() {
    setForm((current) => ({
      ...current,
      rewards: [...current.rewards, emptyReward()],
    }))
  }

  function removeReward(index: number) {
    setForm((current) => ({
      ...current,
      rewards: current.rewards.filter(
        (_, rewardIndex) => rewardIndex !== index,
      ),
    }))
  }

  async function saveMission() {
    setError('')
    setNotice('')
    setSubmitting(true)

    try {
      const payload = formToPayload(form)

      if (!payload.chapter_id || !payload.slug || !payload.title) {
        throw new Error('Заполните chapter ID, slug и название миссии.')
      }

      const mission = selectedMission
        ? await updateAdminMission(selectedMission.id, payload)
        : await createAdminMission(payload)

      setMissions((current) => {
        const exists = current.some((entry) => entry.id === mission.id)
        const next = exists
          ? current.map((entry) => (entry.id === mission.id ? mission : entry))
          : [...current, mission]

        return [...next].sort((first, second) =>
          first.status === second.status
            ? first.sortOrder - second.sortOrder
            : first.status.localeCompare(second.status),
        )
      })

      setSelectedId(mission.id)
      setForm(formFromMission(mission))
      setNotice(
        selectedMission
          ? 'Изменения сохранены.'
          : 'Черновик миссии создан.',
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось сохранить миссию.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  async function changePublication(action: 'publish' | 'unpublish') {
    if (!selectedMission) {
      return
    }

    setError('')
    setNotice('')
    setSubmitting(true)

    try {
      const mission =
        action === 'publish'
          ? await publishAdminMission(selectedMission.id)
          : await unpublishAdminMission(selectedMission.id)

      setMissions((current) =>
        current.map((entry) => (entry.id === mission.id ? mission : entry)),
      )
      setForm(formFromMission(mission))
      setNotice(
        action === 'publish'
          ? 'Миссия опубликована.'
          : 'Миссия возвращена в черновики.',
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось изменить статус публикации.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <main className="admin-shell">Загрузка admin-панели…</main>
  }

  if (!admin) {
    return (
      <main className="admin-shell admin-login-page">
        <section className="admin-login-card">
          <p className="admin-kicker">CHIMERA PROTOCOL</p>
          <h1>Админ-панель</h1>
          <p className="admin-muted">
            Вход доступен только для авторизованных администраторов.
          </p>

          <form className="admin-login-form" onSubmit={handleLogin}>
            <label>
              Логин
              <input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>

            <label>
              Пароль
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>

            {error && <p className="admin-error">{error}</p>}

            <button className="admin-primary" disabled={submitting}>
              {submitting ? 'Вход…' : 'Войти'}
            </button>
          </form>

          <a className="admin-back-link" href="/">
            ← Вернуться к игре
          </a>
        </section>
      </main>
    )
  }

  function selectedSetting(): AdminSystemSetting | null {
    if (selectedSettingKey === null) return null
    return settings.find((s) => s.key === selectedSettingKey) ?? null
  }

  async function handleSaveSetting() {
    const s = selectedSetting()
    if (!s) return
    if (s.isSensitive && !(admin?.isSuperAdmin ?? false)) {
      setSavingError(
        'Чувствительные настройки нельзя менять напрямую — требуется approval супер-админа.',
      )
      return
    }
    let parsed: unknown
    if (s.valueType === 'boolean') {
      parsed = settingDraft === 'true'
    } else if (s.valueType === 'integer') {
      const n = Number.parseInt(settingDraft, 10)
      if (!Number.isFinite(n) || n < 0) {
        setSavingError('Значение должно быть неотрицательным целым числом.')
        return
      }
      parsed = n
    } else if (s.valueType === 'string') {
      parsed = settingDraft
    } else {
      try {
        parsed = JSON.parse(settingDraft)
      } catch {
        setSavingError('Значение — невалидный JSON.')
        return
      }
    }
    setSavingSetting(true)
    setSavingError(null)
    setSavingNotice(null)
    try {
      const updated = await updateSystemSetting(
        s.key,
        parsed,
        settingReason.trim() || undefined,
      )
      setSettings((prev) =>
        prev.map((x) => (x.key === updated.key ? updated : x)),
      )
      setSavingNotice('Сохранено.')
    } catch (err) {
      setSavingError((err as Error).message)
    } finally {
      setSavingSetting(false)
    }
  }

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / CONTENT CONTROL</p>
          <h1>
            {section === 'missions' && 'Миссии'}
            {section === 'settings' && 'Настройки'}
            {section === 'admins' && 'Администраторы'}
          </h1>

          <nav className="admin-nav">
            <button
              className={section === 'missions' ? 'is-active' : ''}
              onClick={() => setSection('missions')}
            >
              Миссии
            </button>
            <button
              className={section === 'settings' ? 'is-active' : ''}
              onClick={() => setSection('settings')}
            >
              Настройки
            </button>
            {(admin?.isSuperAdmin ?? false) && (
              <button
                className={section === 'admins' ? 'is-active' : ''}
                onClick={() => setSection('admins')}
              >
                Администраторы
              </button>
            )}
          </nav>
        </div>

        <div className="admin-user">
          <span>
            {admin.username} · <b>{admin.role}</b>
          </span>
          <button className="admin-secondary" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </header>

      {error && <p className="admin-alert admin-error">{error}</p>}
      {notice && <p className="admin-alert admin-notice">{notice}</p>}

      {section === 'missions' && (
        <div className="admin-layout">
        <aside className="admin-sidebar">
          <button
            className="admin-primary"
            onClick={startNewMission}
            disabled={!canWrite}
          >
            + Новая миссия
          </button>

          <button
            className="admin-refresh"
            onClick={refreshMissions}
            disabled={loadingMissions}
          >
            {loadingMissions ? 'Обновление…' : '↻ Обновить список'}
          </button>

          <div className="admin-mission-list">
            {missions.map((mission) => (
              <button
                className={`admin-mission-row ${
                  selectedId === mission.id ? 'is-active' : ''
                }`}
                key={mission.id}
                onClick={() => selectMission(mission)}
              >
                <span
                  className={`admin-status admin-status-${mission.status}`}
                >
                  {mission.status}
                </span>
                <strong>{mission.title}</strong>
                <small>{mission.slug}</small>
              </button>
            ))}

            {!loadingMissions && missions.length === 0 && (
              <p className="admin-muted">Миссий пока нет.</p>
            )}
          </div>
        </aside>

        <section className="admin-editor">
          <div className="admin-editor-title">
            <div>
              <p className="admin-kicker">
                {selectedMission ? selectedMission.id : 'НОВЫЙ ЧЕРНОВИК'}
              </p>
              <h2>
                {selectedMission ? 'Редактирование миссии' : 'Создание миссии'}
              </h2>
            </div>

            {selectedMission && (
              <span
                className={`admin-status admin-status-${selectedMission.status}`}
              >
                {selectedMission.status}
              </span>
            )}
          </div>

          {!canWrite && (
            <p className="admin-readonly">
              Роль viewer позволяет просматривать миссии, но не изменять их.
            </p>
          )}

          <div className="admin-grid">
            <label>
              Chapter ID *
              <input
                value={form.chapterId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, chapterId: event.target.value })
                }
              />
            </label>

            <label>
              Story node ID
              <input
                value={form.storyNodeId}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, storyNodeId: event.target.value })
                }
              />
            </label>

            <label>
              Slug *
              <input
                value={form.slug}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, slug: event.target.value })
                }
              />
            </label>

            <label>
              Тип миссии *
              <input
                value={form.missionType}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, missionType: event.target.value })
                }
              />
            </label>

            <label className="admin-span-2">
              Название *
              <input
                value={form.title}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, title: event.target.value })
                }
              />
            </label>

            <label className="admin-span-2">
              Описание
              <textarea
                value={form.description}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </label>

            <label>
              Порядок сортировки
              <input
                type="number"
                value={form.sortOrder}
                disabled={!canWrite}
                onChange={(event) =>
                  setForm({ ...form, sortOrder: event.target.value })
                }
              />
            </label>
          </div>

          <label className="admin-json-field">
            Content (JSON)
            <textarea
              spellCheck={false}
              value={form.content}
              disabled={!canWrite}
              onChange={(event) =>
                setForm({ ...form, content: event.target.value })
              }
            />
          </label>

          <label className="admin-json-field">
            Validation config (JSON, закрытые данные)
            <textarea
              spellCheck={false}
              value={form.validationConfig}
              disabled={!canWrite}
              onChange={(event) =>
                setForm({ ...form, validationConfig: event.target.value })
              }
            />
          </label>

          <section className="admin-rewards">
            <div className="admin-section-heading">
              <h3>Награды</h3>
              <button
                className="admin-secondary"
                onClick={addReward}
                disabled={!canWrite}
              >
                + Награда
              </button>
            </div>

            {form.rewards.map((reward, index) => (
              <div className="admin-reward-card" key={index}>
                <label>
                  Тип
                  <select
                    value={reward.rewardType}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'rewardType', event.target.value)
                    }
                  >
                    <option value="currency">currency</option>
                    <option value="item">item</option>
                    <option value="story_node">story_node</option>
                  </select>
                </label>

                <label>
                  Amount
                  <input
                    type="number"
                    value={reward.amount}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'amount', event.target.value)
                    }
                  />
                </label>

                <label>
                  Item ID
                  <input
                    value={reward.itemId}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'itemId', event.target.value)
                    }
                  />
                </label>

                <label>
                  Story node ID
                  <input
                    value={reward.storyNodeId}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'storyNodeId', event.target.value)
                    }
                  />
                </label>

                <label>
                  Sort
                  <input
                    type="number"
                    value={reward.sortOrder}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'sortOrder', event.target.value)
                    }
                  />
                </label>

                <label className="admin-reward-json">
                  Reward value (JSON)
                  <input
                    value={reward.rewardValue}
                    disabled={!canWrite}
                    onChange={(event) =>
                      changeReward(index, 'rewardValue', event.target.value)
                    }
                  />
                </label>

                <button
                  className="admin-danger"
                  onClick={() => removeReward(index)}
                  disabled={!canWrite}
                >
                  Удалить
                </button>
              </div>
            ))}
          </section>

          <div className="admin-actions">
            <button
              className="admin-primary"
              onClick={saveMission}
              disabled={!canWrite || submitting}
            >
              {submitting ? 'Сохранение…' : 'Сохранить'}
            </button>

            {selectedMission?.status === 'draft' && (
              <button
                className="admin-publish"
                onClick={() => changePublication('publish')}
                disabled={!canWrite || submitting}
              >
                Опубликовать
              </button>
            )}

            {selectedMission?.status === 'published' && (
              <button
                className="admin-secondary"
                onClick={() => changePublication('unpublish')}
                disabled={!canWrite || submitting}
              >
                Снять с публикации
              </button>
            )}
          </div>
        </section>
        </div>
      )}

      {section === 'settings' && (
        <div className="admin-layout admin-settings-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedSettingKey(null)
                setSettings([])
                setSettingsError(null)
                setLoadingSettings(true)
                listSystemSettings()
                  .then(setSettings)
                  .catch((err: Error) => setSettingsError(err.message))
                  .finally(() => setLoadingSettings(false))
              }}
              disabled={loadingSettings}
            >
              {loadingSettings ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {settingsError && (
              <p className="admin-alert admin-error">{settingsError}</p>
            )}

            <div className="admin-mission-list">
              {groupedSettings.map(([category, items]) => (
                <div key={category}>
                  <p className="admin-category-label">{category}</p>
                  {items.map((s) => (
                    <button
                      className={`admin-mission-row ${selectedSettingKey === s.key ? 'is-active' : ''}`}
                      key={s.key}
                      onClick={() => setSelectedSettingKey(s.key)}
                    >
                      {s.isSensitive && (
                        <span className="admin-badge admin-badge-sensitive">
                          sensitive
                        </span>
                      )}
                      <strong>{s.title}</strong>
                      <small>{s.key}</small>
                    </button>
                  ))}
                </div>
              ))}
              {!loadingSettings && settings.length === 0 && !settingsError && (
                <p className="admin-muted">Настроек нет.</p>
              )}
            </div>
          </aside>

          <section className="admin-editor">
            {selectedSetting() === null ? (
              <p className="admin-muted">Выберите настройку слева.</p>
            ) : (
              (() => {
                const s = selectedSetting()!
                const canEditSetting = !s.isSensitive || (admin?.isSuperAdmin ?? false)
                return (
                  <>
                    <div className="admin-editor-title">
                      <h2>{s.title}</h2>
                      {s.isSensitive && (
                        <span className="admin-badge admin-badge-sensitive">
                          sensitive
                          {admin?.isSuperAdmin ? ' · изменение напрямую' : ' · только через approval'}
                        </span>
                      )}
                    </div>

                    {s.description && (
                      <p className="admin-muted">{s.description}</p>
                    )}

                    <p className="admin-muted">
                      <b>Ключ:</b> <code>{s.key}</code>
                    </p>
                    <p className="admin-muted">
                      <b>Категория:</b> {s.category} · <b>Тип:</b> {s.valueType}
                    </p>

                    {savingError && (
                      <p className="admin-alert admin-error">{savingError}</p>
                    )}
                    {savingNotice && (
                      <p className="admin-alert admin-notice">{savingNotice}</p>
                    )}

                    <label className="admin-field">
                      <span>
                        Значение
                        {s.valueType === 'json' && ' (JSON)'}
                      </span>
                      {s.valueType === 'boolean' ? (
                        <input
                          type="checkbox"
                          checked={settingDraft === 'true'}
                          onChange={(e) => setSettingDraft(e.target.checked ? 'true' : 'false')}
                          disabled={!canEditSetting || savingSetting}
                        />
                      ) : s.valueType === 'integer' ? (
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={settingDraft}
                          onChange={(e) => setSettingDraft(e.target.value)}
                          disabled={!canEditSetting || savingSetting}
                        />
                      ) : s.valueType === 'string' ? (
                        <input
                          type="text"
                          value={settingDraft}
                          onChange={(e) => setSettingDraft(e.target.value)}
                          disabled={!canEditSetting || savingSetting}
                        />
                      ) : s.key === 'missions.default_attempt_reward_multipliers' ? (
                        (() => {
                          // Парсим draft в массив долей 0..1.
                          let multipliers: number[] = []
                          try {
                            const parsed = JSON.parse(settingDraft)
                            if (Array.isArray(parsed)) {
                              multipliers = parsed.map(Number)
                            }
                          } catch {
                            multipliers = []
                          }
                          if (multipliers.length === 0) multipliers = [1.0]

                          const updateMultipliers = (next: number[]) => {
                            setSettingDraft(JSON.stringify(next))
                          }

                          return (
                            <div className="admin-multipliers">
                              {multipliers.map((value, idx) => (
                                <div className="admin-multiplier-row" key={idx}>
                                  <span className="admin-multiplier-label">
                                    Попытка {idx + 1}
                                  </span>
                                  <input
                                    type="number"
                                    min={0}
                                    max={100}
                                    step={1}
                                    value={Math.round(value * 100)}
                                    onChange={(e) => {
                                      const pct = Number.parseInt(e.target.value, 10)
                                      if (!Number.isFinite(pct)) return
                                      const next = [...multipliers]
                                      next[idx] = Math.max(0, Math.min(100, pct)) / 100
                                      updateMultipliers(next)
                                    }}
                                    disabled={!canEditSetting || savingSetting}
                                  />
                                  <span className="admin-multiplier-percent">%</span>
                                  {idx > 0 && (
                                    <button
                                      type="button"
                                      className="admin-multiplier-remove"
                                      onClick={() => {
                                        const next = multipliers.filter((_, i) => i !== idx)
                                        updateMultipliers(next.length > 0 ? next : [1.0])
                                      }}
                                      disabled={!canEditSetting || savingSetting}
                                    >
                                      ×
                                    </button>
                                  )}
                                </div>
                              ))}
                              {multipliers.length < 10 && (
                                <button
                                  type="button"
                                  className="admin-multiplier-add"
                                  onClick={() => {
                                    const last = multipliers[multipliers.length - 1] ?? 1.0
                                    const next = Math.max(0, last / 2)
                                    updateMultipliers([...multipliers, next])
                                  }}
                                  disabled={!canEditSetting || savingSetting}
                                >
                                  + Добавить попытку
                                </button>
                              )}
                            </div>
                          )
                        })()
                      ) : (
                        <textarea
                          value={settingDraft}
                          onChange={(e) => setSettingDraft(e.target.value)}
                          rows={6}
                          disabled={!canEditSetting || savingSetting}
                        />
                      )}
                    </label>

                    <label className="admin-field">
                      <span>Причина (для аудита, необязательно)</span>
                      <input
                        type="text"
                        value={settingReason}
                        onChange={(e) => setSettingReason(e.target.value)}
                        disabled={!canEditSetting || savingSetting}
                        maxLength={200}
                      />
                    </label>

                    <div className="admin-actions">
                      <button
                        className="admin-primary"
                        onClick={handleSaveSetting}
                        disabled={!canEditSetting || savingSetting}
                      >
                        {savingSetting ? 'Сохранение…' : 'Сохранить'}
                      </button>
                    </div>
                  </>
                )
              })()
            )}
          </section>
        </div>
      )}

      {section === 'admins' && (admin?.isSuperAdmin ?? false) && (
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
      )}
    </main>
  )
}

export default AdminApp
