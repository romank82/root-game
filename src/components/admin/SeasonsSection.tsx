import { useEffect, useState } from 'react'
import {
  archiveSeason,
  createSeason,
  listSeasons,
  publishSeason,
  updateSeason,
  type AdminSeason,
  type AdminUser,
} from '../../api/adminApi'

type SeasonsSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

export function SeasonsSection({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
}: SeasonsSectionProps) {
  const [seasons, setSeasons] = useState<AdminSeason[]>([])
  const [selectedSeasonId, setSelectedSeasonId] = useState<string | null>(null)
  const [loadingSeasons, setLoadingSeasons] = useState(false)
  const [seasonsError, setSeasonsError] = useState<string | null>(null)
  const [showCreateSeason, setShowCreateSeason] = useState(false)
  const [seasonSlug, setSeasonSlug] = useState('')
  const [seasonTitle, setSeasonTitle] = useState('')
  const [seasonDescription, setSeasonDescription] = useState('')
  const [seasonSortOrder, setSeasonSortOrder] = useState('0')
  const [savingSeason, setSavingSeason] = useState(false)
  const [savingSeasonError, setSavingSeasonError] = useState<string | null>(null)
  const [savingSeasonNotice, setSavingSeasonNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoadingSeasons(true)
    setSeasonsError(null)
    listSeasons()
      .then((data) => {
        if (cancelled) return
        setSeasons(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setSeasonsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingSeasons(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function selectedSeason(): AdminSeason | null {
    if (selectedSeasonId === null) return null
    return seasons.find((item) => item.id === selectedSeasonId) ?? null
  }

  useEffect(() => {
    const season = seasons.find((item) => item.id === selectedSeasonId) ?? null
    if (!season) return
    setSeasonSlug(season.slug)
    setSeasonTitle(season.title)
    setSeasonDescription(season.description ?? '')
    setSeasonSortOrder(String(season.sortOrder))
  }, [selectedSeasonId, seasons])

  function handleShowCreateSeason() {
    setShowCreateSeason(true)
    setSelectedSeasonId(null)
    setSeasonSlug('')
    setSeasonTitle('')
    setSeasonDescription('')
    setSeasonSortOrder('0')
    setSavingSeasonError(null)
    setSavingSeasonNotice(null)
  }

  function parseSortOrder(): number | null {
    const raw = seasonSortOrder.trim()
    if (raw === '') return 0
    const parsed = Number.parseInt(raw, 10)
    if (!Number.isFinite(parsed) || parsed < 0) {
      setSavingSeasonError('Порядок отображения — неотрицательное целое число.')
      return null
    }
    return parsed
  }

  async function handleCreateSeason() {
    const title = seasonTitle.trim()
    if (title.length === 0) {
      setSavingSeasonError('Укажите название сезона.')
      return
    }
    const sortOrder = parseSortOrder()
    if (sortOrder === null) return

    setSavingSeason(true)
    setSavingSeasonError(null)
    setSavingSeasonNotice(null)
    try {
      const created = await createSeason({
        title,
        description:
          seasonDescription.trim() === '' ? undefined : seasonDescription.trim(),
        sort_order: sortOrder,
      })
      setSeasons((prev) => [...prev, created])
      setShowCreateSeason(false)
      setSelectedSeasonId(created.id)
      setSavingSeasonNotice('Сезон создан.')
    } catch (err) {
      setSavingSeasonError((err as Error).message)
    } finally {
      setSavingSeason(false)
    }
  }

  async function handleSaveSeason() {
    const season = selectedSeason()
    if (!season) return

    const title = seasonTitle.trim()
    if (title.length === 0) {
      setSavingSeasonError('Название сезона не может быть пустым.')
      return
    }
    const sortOrder = parseSortOrder()
    if (sortOrder === null) return

    setSavingSeason(true)
    setSavingSeasonError(null)
    setSavingSeasonNotice(null)
    try {
      const updated = await updateSeason(season.id, {
        title,
        description:
          seasonDescription.trim() === '' ? null : seasonDescription.trim(),
        sort_order: sortOrder,
      })
      setSeasons((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      setSavingSeasonNotice('Сезон сохранён.')
    } catch (err) {
      setSavingSeasonError((err as Error).message)
    } finally {
      setSavingSeason(false)
    }
  }

  async function handlePublishSeason() {
    const season = selectedSeason()
    if (!season) return

    setSavingSeason(true)
    setSavingSeasonError(null)
    setSavingSeasonNotice(null)
    try {
      const updated = await publishSeason(season.id)
      setSeasons((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      setSavingSeasonNotice('Сезон опубликован.')
    } catch (err) {
      setSavingSeasonError((err as Error).message)
    } finally {
      setSavingSeason(false)
    }
  }

  async function handleArchiveSeason() {
    const season = selectedSeason()
    if (!season) return

    setSavingSeason(true)
    setSavingSeasonError(null)
    setSavingSeasonNotice(null)
    try {
      const updated = await archiveSeason(season.id)
      setSeasons((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      setSavingSeasonNotice('Сезон архивирован.')
    } catch (err) {
      setSavingSeasonError((err as Error).message)
    } finally {
      setSavingSeason(false)
    }
  }

  const editorSeason = selectedSeason()

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <button
          className="admin-primary"
          onClick={handleShowCreateSeason}
          disabled={!canWrite}
        >
          + Новый сезон
        </button>
        <button
          className="admin-refresh"
          onClick={() => {
            setSelectedSeasonId(null)
            setShowCreateSeason(false)
            setSeasonsError(null)
            setLoadingSeasons(true)
            listSeasons()
              .then(setSeasons)
              .catch((err: Error) => setSeasonsError(err.message))
              .finally(() => setLoadingSeasons(false))
          }}
          disabled={loadingSeasons}
        >
          {loadingSeasons ? 'Обновление…' : '↻ Обновить список'}
        </button>

        {seasonsError && (
          <p className="admin-alert admin-error">{seasonsError}</p>
        )}

        <div className="admin-mission-list">
          {seasons.map((season) => (
            <button
              className={`admin-mission-row ${selectedSeasonId === season.id ? 'is-active' : ''}`}
              key={season.id}
              onClick={() => {
                setSelectedSeasonId(season.id)
                setShowCreateSeason(false)
              }}
            >
              <span className={`admin-status admin-status-${season.status}`}>
                {season.status}
              </span>
              <strong>{season.title}</strong>
              <small>{season.slug}</small>
            </button>
          ))}
          {!loadingSeasons && seasons.length === 0 && !seasonsError && (
            <p className="admin-muted">Сезонов пока нет.</p>
          )}
        </div>
      </aside>

      <section className="admin-editor">
        {showCreateSeason || editorSeason ? (
          <>
            <div className="admin-editor-title">
              <h2>
                {showCreateSeason ? 'Новый сезон' : 'Редактирование сезона'}
              </h2>
              {editorSeason && <code>{editorSeason.id}</code>}
              {editorSeason && (
                <span
                  className={`admin-status admin-status-${editorSeason.status}`}
                >
                  {editorSeason.status}
                </span>
              )}
            </div>

            {savingSeasonError && (
              <p className="admin-alert admin-error">{savingSeasonError}</p>
            )}
            {savingSeasonNotice && (
              <p className="admin-alert admin-notice">{savingSeasonNotice}</p>
            )}

            <div className="admin-grid">
              <label className="admin-span-2">
                Название *
                <input
                  type="text"
                  value={seasonTitle}
                  onChange={(e) => setSeasonTitle(e.target.value)}
                  disabled={!canWrite || savingSeason}
                  maxLength={255}
                />
              </label>

              <label className="admin-span-2">
                Slug (генерируется из названия)
                <input
                  type="text"
                  value={seasonSlug}
                  onChange={(e) => setSeasonSlug(e.target.value)}
                  disabled={!canWrite || savingSeason}
                  readOnly
                  placeholder="сгенерируется автоматически"
                  maxLength={128}
                />
              </label>

              <label className="admin-span-2">
                Описание
                <textarea
                  value={seasonDescription}
                  onChange={(e) => setSeasonDescription(e.target.value)}
                  disabled={!canWrite || savingSeason}
                  rows={4}
                />
              </label>

              <label>
                Порядок отображения (меньше — выше)
                <input
                  type="number"
                  min={0}
                  value={seasonSortOrder}
                  onChange={(e) => setSeasonSortOrder(e.target.value)}
                  disabled={!canWrite || savingSeason}
                />
              </label>
            </div>

            <div className="admin-actions">
              {showCreateSeason ? (
                <>
                  <button
                    className="admin-primary"
                    onClick={handleCreateSeason}
                    disabled={!canWrite || savingSeason}
                  >
                    {savingSeason ? 'Создание…' : 'Создать'}
                  </button>
                  <button
                    className="admin-secondary"
                    onClick={() => setShowCreateSeason(false)}
                    disabled={savingSeason}
                  >
                    Отмена
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="admin-primary"
                    onClick={handleSaveSeason}
                    disabled={!canWrite || savingSeason}
                  >
                    {savingSeason ? 'Сохранение…' : 'Сохранить'}
                  </button>
                  {editorSeason?.status === 'draft' && (
                    <button
                      className="admin-publish"
                      onClick={handlePublishSeason}
                      disabled={!canWrite || savingSeason}
                    >
                      Опубликовать
                    </button>
                  )}
                  {editorSeason?.status === 'published' && (
                    <button
                      className="admin-danger"
                      onClick={handleArchiveSeason}
                      disabled={!canWrite || savingSeason}
                    >
                      Архивировать
                    </button>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <p className="admin-muted">Выберите сезон или создайте новый.</p>
        )}
      </section>
    </div>
  )
}
