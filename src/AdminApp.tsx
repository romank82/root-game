import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './AdminApp.css'
import {
  archiveMinigameProfile,
  createMinigameProfile,
  getAdminMe,
  listARObjects,
  listGeoZones,
  listKeyItems,
  listMinigameProfiles,
  loginAdmin,
  logoutAdmin,
  publishMinigameProfile,
  updateMinigameProfile,
  type AdminARObject,
  type AdminGeoZone,
  type AdminMinigameProfile,
  type AdminUser,
  type KeyItem,
} from './api/adminApi'

import { SettingsSection } from './components/admin/SettingsSection'
import { AdminsSection } from './components/admin/AdminsSection'
import { KeysSection } from './components/admin/KeysSection'
import { ContentSection } from './components/admin/ContentSection'
import { PlayersSection } from './components/admin/PlayersSection'
import { AdminTree } from './components/admin/AdminTree'
import { MonitoringSection } from './components/admin/MonitoringSection'
import { WithdrawalsSection } from './components/admin/WithdrawalsSection'

// 13.7-j: валидные вкладки админки. 'economy' удалена — реестр операций
// перенесён в карточку игрока (PlayersSection), настройки — в CMS.
// Вкладки 'missions', 'seasons', 'chapters', 'story-nodes' заменены единой
// вкладкой 'structure' (AdminTree); 'cascade' («Конструктор») тоже убрана —
// она дублировала дерево для просмотра. Список используется для фолбэка
// старой вкладки из localStorage.
const ADMIN_SECTIONS = [
  'structure',
  'settings',
  'admins',
  'keys',
  'content',
  'minigame-profiles',
  'players',
  'monitoring',
  'withdrawals',
] as const

type AdminSection = (typeof ADMIN_SECTIONS)[number]

function AdminApp() {
  const [admin, setAdmin] = useState<AdminUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [section, setSection] = useState<AdminSection>(() => {
    // 13.7-j: если в localStorage сохранена удалённая вкладка ('economy',
    // 'missions', 'seasons', 'chapters', 'story-nodes', 'cascade' и т.п.) —
    // фолбэк на 'structure'.
    const saved = localStorage.getItem('chimera-admin-section')
    return ADMIN_SECTIONS.includes(saved as (typeof ADMIN_SECTIONS)[number])
      ? (saved as (typeof ADMIN_SECTIONS)[number])
      : 'structure'
  })
  const [geoZones, setGeoZones] = useState<AdminGeoZone[]>([])
  // setGeoZonesError и setARObjectsError всё ещё используются эффектом загрузки
  // общих данных для AdminTree; сами geoZonesError/arObjectsError больше не
  // отображаются в AdminApp (редакторы геозон и AR-объектов показывают ошибки сами).
  const [, setGeoZonesError] = useState<string | null>(null)
  const [, setARObjectsError] = useState<string | null>(null)
  const [arObjects, setARObjects] = useState<AdminARObject[]>([])
  const [keyItems, setKeyItems] = useState<KeyItem[]>([])
  const [loadingKeyItems, setLoadingKeyItems] = useState(false)
  // Minigame profiles (Sprint 8.17)
  const [minigameProfiles, setMinigameProfiles] = useState<
    AdminMinigameProfile[]
  >([])
  const [loadingMinigameProfiles, setLoadingMinigameProfiles] = useState(false)
  const [minigameProfilesError, setMinigameProfilesError] = useState<
    string | null
  >(null)
  const [selectedMinigameProfileId, setSelectedMinigameProfileId] = useState<
    string | null
  >(null)
  const [showCreateMinigameProfile, setShowCreateMinigameProfile] =
    useState(false)
  const [minigameProfileName, setMinigameProfileName] = useState('')
  const [minigameProfileGameType, setMinigameProfileGameType] = useState(
    'cipher',
  )
  // Для cipher:
  const [mgDrumCount, setMgDrumCount] = useState('4')
  const [mgFalseChoices, setMgFalseChoices] = useState('2')
  const [mgTimeLimit, setMgTimeLimit] = useState('60')

  // Для code_repair (пока заглушка):
  const [mgMaxBlocks, setMgMaxBlocks] = useState('3')
  const [savingMinigameProfile, setSavingMinigameProfile] = useState(false)
  const [minigameProfileError, setMinigameProfileError] = useState<
    string | null
  >(null)
  const [minigameProfileNotice, setMinigameProfileNotice] = useState<
    string | null
  >(null)

  useEffect(() => {
    localStorage.setItem('chimera-admin-section', section)
  }, [section])

  useEffect(() => {
    if (section !== 'minigame-profiles') return
    let cancelled = false
    setLoadingMinigameProfiles(true)
    setMinigameProfilesError(null)
    listMinigameProfiles()
      .then((data) => {
        if (cancelled) return
        setMinigameProfiles(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setMinigameProfilesError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingMinigameProfiles(false)
      })
    return () => {
      cancelled = true
    }
  }, [section])
  // Общие данные (геозоны, AR-объекты, мини-игры) для AdminTree и связанных
  // редакторов. Раньше грузились при открытии вкладки 'missions' — теперь
  // грузятся при открытии 'structure', где эти данные нужны MissionsSection.
  useEffect(() => {
    if (section !== 'structure') return
    let cancelled = false

    listGeoZones()
      .then((data) => {
        if (cancelled) return
        setGeoZones(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setGeoZonesError(err.message)
      })

    listARObjects()
      .then((data) => {
        if (cancelled) return
        setARObjects(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setARObjectsError(err.message)
      })

    listMinigameProfiles()
      .then((data) => {
        if (cancelled) return
        setMinigameProfiles(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setMinigameProfilesError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [section])


  useEffect(() => {
    setShowCreateMinigameProfile(false)
    setMinigameProfileError(null)
    setMinigameProfileNotice(null)
  }, [section])

  useEffect(() => {
    if (!selectedMinigameProfileId) {
      setMinigameProfileName('')
      setMinigameProfileGameType('cipher')
      setMgDrumCount('4')
      setMgFalseChoices('2')
      setMgTimeLimit('60')
      setMgMaxBlocks('3')
      setMinigameProfileError(null)
      setMinigameProfileNotice(null)
      return
    }
    const p = minigameProfiles.find((x) => x.id === selectedMinigameProfileId)
    if (!p) return
    setMinigameProfileName(p.name)
    setMinigameProfileGameType(p.gameType)
    const s = p.settings || {}
    if (p.gameType === 'cipher') {
      setMgDrumCount(String(s.drumCount ?? '4'))
      setMgFalseChoices(String(s.falseChoicesPerDrum ?? '2'))
      setMgTimeLimit(
        s.timeLimitSeconds != null ? String(s.timeLimitSeconds) : '',
      )
    } else if (p.gameType === 'code_repair') {
      setMgMaxBlocks(String(s.maxBlocks ?? '3'))
    }
    setMinigameProfileError(null)
    setMinigameProfileNotice(null)
  }, [selectedMinigameProfileId, minigameProfiles])


  const canWrite =
    admin?.isSuperAdmin === true ||
    admin?.role === 'owner' ||
    admin?.role === 'editor'

  useEffect(() => {
    getAdminMe()
      .then(async (currentAdmin) => {
        setAdmin(currentAdmin)
      })
      .catch((err: unknown) => {
        // 8.18: не глотаем молча — сбой сети выглядел как разлогин.
        console.error('[AdminApp] getAdminMe failed', err)
        setAdmin(null)
        setError(
          err instanceof Error ? err.message : 'Не удалось загрузить сессию админа.',
        )
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoadingKeyItems(true)
    listKeyItems('published')
      .then((data) => {
        if (!cancelled) setKeyItems(data)
      })
      .catch((err: unknown) => {
        // 8.18: не глотаем молча — админ видел пустой dropdown и думал «ключей нет».
        console.error('[AdminApp] listKeyItems failed', err)
        setError(
          err instanceof Error
            ? err.message
            : 'Не удалось загрузить каталог ключей.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoadingKeyItems(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function buildSettingsFromForm(): Record<string, unknown> {
    switch (minigameProfileGameType) {
      case 'cipher': {
        return {
          drumCount: Number(mgDrumCount),
          falseChoicesPerDrum: Number(mgFalseChoices),
          timeLimitSeconds: mgTimeLimit.trim() ? Number(mgTimeLimit) : null,
        }
      }
      case 'code_repair': {
        return { maxBlocks: Number(mgMaxBlocks) }
      }
      case 'text_answer': {
        return {}
      }
      default:
        return {}
    }
  }

  function handleShowCreateMinigameProfile() {
    setShowCreateMinigameProfile(true)
    setSelectedMinigameProfileId(null)
    setMinigameProfileName('')
    setMinigameProfileGameType('cipher')
    setMgDrumCount('4')
    setMgFalseChoices('2')
    setMgTimeLimit('60')
    setMgMaxBlocks('3')
    setMinigameProfileError(null)
    setMinigameProfileNotice(null)
  }

  async function handleCreateMinigameProfile() {
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const settings = buildSettingsFromForm()
      const created = await createMinigameProfile({
        name: minigameProfileName,
        game_type: minigameProfileGameType,
        settings,
      })
      setMinigameProfiles((prev) => [...prev, created])
      setSelectedMinigameProfileId(created.id)
      setShowCreateMinigameProfile(false)
      setMinigameProfileNotice('Создано.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }

  async function handleSaveMinigameProfile() {
    if (!selectedMinigameProfileId) return
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const settings = buildSettingsFromForm()
      const updated = await updateMinigameProfile(selectedMinigameProfileId, {
        name: minigameProfileName,
        game_type: minigameProfileGameType,
        settings,
      })
      setMinigameProfiles((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      )
      setMinigameProfileNotice('Сохранено.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }

  async function handlePublishMinigameProfile() {
    if (!selectedMinigameProfileId) return
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const updated = await publishMinigameProfile(selectedMinigameProfileId)
      setMinigameProfiles((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      )
      setMinigameProfileNotice('Опубликовано.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
  }

  async function handleArchiveMinigameProfile() {
    if (!selectedMinigameProfileId) return
    setSavingMinigameProfile(true)
    setMinigameProfileError(null)
    try {
      const updated = await archiveMinigameProfile(selectedMinigameProfileId)
      setMinigameProfiles((prev) =>
        prev.map((p) => (p.id === updated.id ? updated : p)),
      )
      setMinigameProfileNotice('Архивировано.')
    } catch (err) {
      setMinigameProfileError((err as Error).message)
    } finally {
      setSavingMinigameProfile(false)
    }
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
    setNotice('')
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

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <p className="admin-kicker">CHIMERA PROTOCOL / CONTENT CONTROL</p>
          <h1>
            {section === 'structure' && 'Структура игры'}
            {section === 'content' && 'Каталог'}
            {section === 'settings' && 'Настройки'}
            {section === 'admins' && 'Администраторы'}
            {section === 'keys' && 'Ключи'}
            {section === 'minigame-profiles' && 'Мини-игры'}
            {section === 'players' && 'Игроки'}
            {section === 'monitoring' && 'Мониторинг'}
            {section === 'withdrawals' && 'Заявки на вывод'}
          </h1>

          <nav className="admin-nav">
            <button
              className={section === 'structure' ? 'is-active' : ''}
              onClick={() => setSection('structure')}
            >
              Структура игры
            </button>
            <button
              className={section === 'content' ? 'is-active' : ''}
              onClick={() => setSection('content')}
            >
              Каталог
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
            <button
              className={section === 'keys' ? 'is-active' : ''}
              onClick={() => setSection('keys')}
            >
              Ключи
            </button>

            <button
              className={section === 'players' ? 'is-active' : ''}
              onClick={() => setSection('players')}
            >
              Игроки
            </button>

            <button
              className={section === 'monitoring' ? 'is-active' : ''}
              onClick={() => setSection('monitoring')}
            >
              Мониторинг
            </button>

            <button
              className={section === 'withdrawals' ? 'is-active' : ''}
              onClick={() => setSection('withdrawals')}
            >
              Заявки на вывод
            </button>

            <button
              className={section === 'minigame-profiles' ? 'is-active' : ''}
              onClick={() => setSection('minigame-profiles')}
            >
              Мини-игры
            </button>
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

      {section === 'structure' && (
        <AdminTree
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
          keyItems={keyItems}
          loadingKeyItems={loadingKeyItems}
          geoZones={geoZones}
          arObjects={arObjects}
          minigameProfiles={minigameProfiles}
        />
      )}

      {section === 'settings' && (
        <SettingsSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
        />
      )}

      {section === 'admins' && (admin?.isSuperAdmin ?? false) && (
        <AdminsSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
        />
      )}

      {section === 'keys' && (
        <KeysSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
          keyItems={keyItems}
        />
      )}

      {section === 'players' && (
        <PlayersSection
          admin={admin}
          canWrite={canWrite}
          onError={setError}
          onNotice={setNotice}
        />
      )}

      {section === 'monitoring' && (
        <MonitoringSection onError={setError} onNotice={setNotice} />
      )}

      {section === 'withdrawals' && <WithdrawalsSection />}

      {section === 'minigame-profiles' && (
        <div className="admin-layout">
          <aside className="admin-sidebar">
            <button
              className="admin-primary"
              onClick={handleShowCreateMinigameProfile}
              disabled={!canWrite}
            >
              + Новый профиль
            </button>
            <button
              className="admin-refresh"
              onClick={() => {
                setSelectedMinigameProfileId(null)
                setMinigameProfiles([])
                setMinigameProfilesError(null)
                setLoadingMinigameProfiles(true)
                listMinigameProfiles()
                  .then(setMinigameProfiles)
                  .catch((err: Error) => setMinigameProfilesError(err.message))
                  .finally(() => setLoadingMinigameProfiles(false))
              }}
              disabled={loadingMinigameProfiles}
            >
              {loadingMinigameProfiles ? 'Обновление…' : '↻ Обновить список'}
            </button>

            {minigameProfilesError && (
              <p className="admin-alert admin-error">{minigameProfilesError}</p>
            )}

            <div className="admin-mission-list">
              {minigameProfiles.map((p) => (
                <button
                  key={p.id}
                  className={`admin-mission-row ${selectedMinigameProfileId === p.id ? 'is-active' : ''}`}
                  onClick={() => {
                    setSelectedMinigameProfileId(p.id)
                    setShowCreateMinigameProfile(false)
                  }}
                >
                  <span className={`admin-status admin-status-${p.status}`}>
                    {p.status}
                  </span>
                  <strong>{p.name}</strong>
                  <small>{p.gameType}</small>
                </button>
              ))}
              {!loadingMinigameProfiles &&
                minigameProfiles.length === 0 &&
                !minigameProfilesError && (
                  <p className="admin-muted">Профилей нет.</p>
                )}
            </div>
          </aside>

          <section className="admin-editor">
            {showCreateMinigameProfile || selectedMinigameProfileId ? (
              <>
                <div className="admin-editor-title">
                  <h2>
                    {showCreateMinigameProfile
                      ? 'Новый профиль мини-игры'
                      : 'Редактирование профиля'}
                  </h2>
                  {selectedMinigameProfileId && (
                    <code>{selectedMinigameProfileId}</code>
                  )}
                  {selectedMinigameProfileId && (
                    <span
                      className={`admin-status admin-status-${
                        minigameProfiles.find(
                          (p) => p.id === selectedMinigameProfileId,
                        )?.status ?? 'draft'
                      }`}
                    >
                      {minigameProfiles.find(
                        (p) => p.id === selectedMinigameProfileId,
                      )?.status}
                    </span>
                  )}
                </div>

                {minigameProfileError && (
                  <p className="admin-alert admin-error">
                    {minigameProfileError}
                  </p>
                )}
                {minigameProfileNotice && (
                  <p className="admin-alert admin-notice">
                    {minigameProfileNotice}
                  </p>
                )}

                <div className="admin-grid">
                  <label className="admin-span-2">
                    Имя профиля *
                    <input
                      value={minigameProfileName}
                      disabled={!canWrite}
                      onChange={(e) => setMinigameProfileName(e.target.value)}
                    />
                  </label>
                  <label>
                    Тип игры *
                    <select
                      value={minigameProfileGameType}
                      disabled={!canWrite}
                      onChange={(e) => setMinigameProfileGameType(e.target.value)}
                    >
                      <option value="cipher">cipher</option>
                      <option value="code_repair">code_repair</option>
                      <option value="text_answer">text_answer</option>
                    </select>
                  </label>
                  {minigameProfileGameType === 'cipher' && (
                    <>
                      <label>
                        Количество барабанов *
                        <input
                          type="number"
                          min={2}
                          max={12}
                          value={mgDrumCount}
                          disabled={!canWrite}
                          onChange={(e) => setMgDrumCount(e.target.value)}
                        />
                      </label>
                      <label>
                        Ложных символов на барабан *
                        <input
                          type="number"
                          min={0}
                          max={36}
                          value={mgFalseChoices}
                          disabled={!canWrite}
                          onChange={(e) => setMgFalseChoices(e.target.value)}
                        />
                      </label>
                      <label>
                        Время на решение (сек, пусто = без лимита)
                        <input
                          type="number"
                          min={1}
                          max={3600}
                          value={mgTimeLimit}
                          disabled={!canWrite}
                          onChange={(e) => setMgTimeLimit(e.target.value)}
                        />
                      </label>
                    </>
                  )}

                  {minigameProfileGameType === 'code_repair' && (
                    <label>
                      Максимум блоков *
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={mgMaxBlocks}
                        disabled={!canWrite}
                        onChange={(e) => setMgMaxBlocks(e.target.value)}
                      />
                    </label>
                  )}

                  {minigameProfileGameType === 'text_answer' && (
                    <p className="admin-muted">
                      Для этого типа игры параметров пока нет.
                    </p>
                  )}
                </div>

                <div className="admin-actions">
                  {showCreateMinigameProfile ? (
                    <>
                      <button
                        className="admin-primary"
                        onClick={handleCreateMinigameProfile}
                        disabled={!canWrite || savingMinigameProfile}
                      >
                        {savingMinigameProfile ? 'Создание…' : 'Создать'}
                      </button>
                      <button
                        className="admin-secondary"
                        onClick={() => setShowCreateMinigameProfile(false)}
                        disabled={savingMinigameProfile}
                      >
                        Отмена
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="admin-primary"
                        onClick={handleSaveMinigameProfile}
                        disabled={!canWrite || savingMinigameProfile}
                      >
                        {savingMinigameProfile ? 'Сохранение…' : 'Сохранить'}
                      </button>
                      {minigameProfiles.find(
                        (p) => p.id === selectedMinigameProfileId,
                      )?.status === 'draft' && (
                        <button
                          className="admin-publish"
                          onClick={handlePublishMinigameProfile}
                          disabled={!canWrite || savingMinigameProfile}
                        >
                          Опубликовать
                        </button>
                      )}
                      {minigameProfiles.find(
                        (p) => p.id === selectedMinigameProfileId,
                      )?.status === 'published' && (
                        <button
                          className="admin-danger"
                          onClick={handleArchiveMinigameProfile}
                          disabled={!canWrite || savingMinigameProfile}
                        >
                          Архивировать
                        </button>
                      )}
                    </>
                  )}
                </div>
              </>
            ) : (
              <p className="admin-muted">Выберите профиль или создайте новый.</p>
            )}
          </section>
        </div>
      )}

      {section === 'content' && (
        <>
          <ContentSection
            admin={admin}
            canWrite={canWrite}
            onError={setError}
            onNotice={setNotice}
            geoZones={geoZones}
            arObjects={arObjects}
            onGeoZonesChange={setGeoZones}
            onARObjectsChange={setARObjects}
          />
        </>
      )}

    </main>
  )
}

export default AdminApp
