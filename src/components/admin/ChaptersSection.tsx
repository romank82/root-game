import { useEffect, useRef, useState } from 'react'
import {
  archiveChapter,
  createChapter,
  listChapters,
  listSeasons,
  publishChapter,
  updateChapter,
  type AdminChapter,
  type AdminSeason,
  type AdminUser,
} from '../../api/adminApi'

type ChaptersSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  // Внешний выбор главы (например, из дерева структуры в AdminTree).
  editingId?: string | null
  // Режим создания главы из дерева структуры: предвыбранный сезон (seasonId).
  // Если задан и editingId не передан — открываем форму новой главы
  // с предзаполненным seasonId.
  initialSeasonId?: string | null
}

// --- Черновик формы главы ------------------------------------------------------
// Хранится в localStorage по ключу `draft_chapter_<id>`. Компонент сохраняет
// изменённые поля формы, восстанавливает их при повторном открытии главы
// и удаляет после успешного сохранения.
type ChapterDraftForm = {
  chapterSeasonId: string
  chapterTitle: string
  chapterDescription: string
  chapterSortOrder: string
}

function saveDraft<T>(key: string, value: T) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage недоступен (приватный режим/SSR) — черновик не сохранится.
  }
}

function loadDraft<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? null : (JSON.parse(raw) as T)
  } catch {
    return null
  }
}

function removeDraft(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // localStorage недоступен — чистить нечего.
  }
}

function draftKeyFor(id: string): string {
  return `draft_chapter_${id}`
}

export function ChaptersSection({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
  editingId,
  initialSeasonId,
}: ChaptersSectionProps) {
  const [chapters, setChapters] = useState<AdminChapter[]>([])
  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null)
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [chaptersError, setChaptersError] = useState<string | null>(null)
  const [showCreateChapter, setShowCreateChapter] = useState(false)
  const [chapterSeasonId, setChapterSeasonId] = useState('')
  const [chapterSlug, setChapterSlug] = useState('')
  const [chapterTitle, setChapterTitle] = useState('')
  const [chapterDescription, setChapterDescription] = useState('')
  const [chapterSortOrder, setChapterSortOrder] = useState('0')
  const [savingChapter, setSavingChapter] = useState(false)
  const [savingChapterError, setSavingChapterError] = useState<string | null>(null)
  const [savingChapterNotice, setSavingChapterNotice] = useState<string | null>(null)
  const [seasons, setSeasons] = useState<AdminSeason[]>([])
  // Черновик: изменённые поля помечаем «грязными» и храним в localStorage.
  const [isDirty, setIsDirty] = useState(false)
  const isDraftRestoredRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    setLoadingChapters(true)
    setChaptersError(null)
    listChapters()
      .then((data) => {
        if (cancelled) return
        setChapters(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setChaptersError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingChapters(false)
      })
    listSeasons()
      .then((data) => {
        if (cancelled) return
        setSeasons(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setChaptersError((prev) => prev ?? err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function selectedChapter(): AdminChapter | null {
    if (selectedChapterId === null) return null
    return chapters.find((item) => item.id === selectedChapterId) ?? null
  }

  useEffect(() => {
    const chapter =
      chapters.find((item) => item.id === selectedChapterId) ?? null
    if (!chapter) return
    // Заполняем форму из базы. Сбрасываем флаг «черновик уже применён»: тогда
    // restore-эффект ниже сработает повторно (поля изменились) и наложит
    // черновик поверх свежих данных базы, а не даст базе затереть его.
    isDraftRestoredRef.current = false
    setChapterSeasonId(chapter.seasonId)
    setChapterSlug(chapter.slug)
    setChapterTitle(chapter.title)
    setChapterDescription(chapter.description ?? '')
    setChapterSortOrder(String(chapter.sortOrder))
  }, [selectedChapterId, chapters])

  // Восстановление черновика при открытии главы: данные из localStorage
  // накладываются поверх формы из базы. Применяется один раз на выбранную
  // главу (isDraftRestoredRef); флаг сбрасывается при выборе другой главы.
  useEffect(() => {
    if (selectedChapterId === null || isDraftRestoredRef.current) return
    // Черновик восстанавливаем только для главы, выбранной в дереве.
    // При рассинхроне (selectedChapterId !== editingId) восстановление
    // пропускаем, чтобы черновик не попал под чужой ключ.
    if (
      editingId !== null &&
      editingId !== undefined &&
      selectedChapterId !== editingId
    )
      return
    const restored = loadDraft<ChapterDraftForm>(draftKeyFor(selectedChapterId))
    if (restored === null) return
    setChapterSeasonId(restored.chapterSeasonId)
    setChapterTitle(restored.chapterTitle)
    setChapterDescription(restored.chapterDescription)
    setChapterSortOrder(restored.chapterSortOrder)
    setIsDirty(true)
    isDraftRestoredRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChapterId, chapterSeasonId, chapterTitle, chapterDescription, chapterSortOrder])

  // Сохранение черновика: только после реальных правок (isDirty). Чистая
  // пересборка формы из базы черновик НЕ перезаписывает.
  useEffect(() => {
    if (selectedChapterId === null || !isDirty) return
    saveDraft(draftKeyFor(selectedChapterId), {
      chapterSeasonId,
      chapterTitle,
      chapterDescription,
      chapterSortOrder,
    })
  }, [
    selectedChapterId,
    chapterSeasonId,
    chapterTitle,
    chapterDescription,
    chapterSortOrder,
    isDirty,
  ])

  // Внешний выбор главы (editingId из дерева структуры). Внутренний эффект
  // выше заполнит поля формы из найденной главы.
  useEffect(() => {
    if (editingId === null || editingId === undefined) return
    const chapter = chapters.find((c) => c.id === editingId)
    if (chapter) {
      setShowCreateChapter(false)
      setSelectedChapterId(chapter.id)
      isDraftRestoredRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, chapters])

  // Режим создания из дерева структуры: editingId не задан, а initialSeasonId
  // предвыбирает сезон для новой главы. Открываем форму создания.
  useEffect(() => {
    if (editingId !== null && editingId !== undefined) return
    if (initialSeasonId === null || initialSeasonId === undefined) return
    handleShowCreateChapter()
    setChapterSeasonId(initialSeasonId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, initialSeasonId])

  function handleShowCreateChapter() {
    setShowCreateChapter(true)
    setSelectedChapterId(null)
    setChapterSeasonId('')
    setChapterSlug('')
    setChapterTitle('')
    setChapterDescription('')
    setChapterSortOrder('0')
    isDraftRestoredRef.current = false
    setSavingChapterError(null)
    setSavingChapterNotice(null)
  }

  function parseSortOrder(): number | null {
    const raw = chapterSortOrder.trim()
    if (raw === '') return 0
    const parsed = Number.parseInt(raw, 10)
    if (!Number.isFinite(parsed) || parsed < 0) {
      setSavingChapterError('Порядок отображения — неотрицательное целое число.')
      return null
    }
    return parsed
  }

  async function handleCreateChapter() {
    const title = chapterTitle.trim()
    if (title.length === 0) {
      setSavingChapterError('Укажите название главы.')
      return
    }
    const seasonId = chapterSeasonId.trim()
    if (seasonId.length === 0) {
      setSavingChapterError('Выберите сезон.')
      return
    }
    const sortOrder = parseSortOrder()
    if (sortOrder === null) return

    setSavingChapter(true)
    setSavingChapterError(null)
    setSavingChapterNotice(null)
    try {
      const created = await createChapter({
        season_id: seasonId,
        title,
        description:
          chapterDescription.trim() === '' ? undefined : chapterDescription.trim(),
        sort_order: sortOrder,
      })
      setChapters((prev) => [...prev, created])
      setShowCreateChapter(false)
      setSelectedChapterId(created.id)
      setIsDirty(false)
      setSavingChapterNotice('Глава создана.')
    } catch (err) {
      setSavingChapterError((err as Error).message)
    } finally {
      setSavingChapter(false)
    }
  }

  async function handleSaveChapter() {
    const chapter = selectedChapter()
    if (!chapter) return

    const title = chapterTitle.trim()
    if (title.length === 0) {
      setSavingChapterError('Название главы не может быть пустым.')
      return
    }
    const seasonId = chapterSeasonId.trim()
    if (seasonId.length === 0) {
      setSavingChapterError('Выберите сезон.')
      return
    }
    const sortOrder = parseSortOrder()
    if (sortOrder === null) return

    setSavingChapter(true)
    setSavingChapterError(null)
    setSavingChapterNotice(null)
    try {
      const updated = await updateChapter(chapter.id, {
        season_id: seasonId,
        title,
        description:
          chapterDescription.trim() === '' ? null : chapterDescription.trim(),
        sort_order: sortOrder,
      })
      setChapters((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      removeDraft(draftKeyFor(chapter.id))
      setIsDirty(false)
      setSavingChapterNotice('Глава сохранена.')
    } catch (err) {
      setSavingChapterError((err as Error).message)
    } finally {
      setSavingChapter(false)
    }
  }

  async function handlePublishChapter() {
    const chapter = selectedChapter()
    if (!chapter) return

    setSavingChapter(true)
    setSavingChapterError(null)
    setSavingChapterNotice(null)
    try {
      const updated = await publishChapter(chapter.id)
      setChapters((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      setSavingChapterNotice('Глава опубликована.')
    } catch (err) {
      setSavingChapterError((err as Error).message)
    } finally {
      setSavingChapter(false)
    }
  }

  async function handleArchiveChapter() {
    const chapter = selectedChapter()
    if (!chapter) return

    setSavingChapter(true)
    setSavingChapterError(null)
    setSavingChapterNotice(null)
    try {
      const updated = await archiveChapter(chapter.id)
      setChapters((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      setSavingChapterNotice('Глава архивирована.')
    } catch (err) {
      setSavingChapterError((err as Error).message)
    } finally {
      setSavingChapter(false)
    }
  }

  const editorChapter = selectedChapter()
  const selectableSeasons = seasons.filter(
    (season) => season.status !== 'archived',
  )

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <button
          className="admin-primary"
          onClick={handleShowCreateChapter}
          disabled={!canWrite}
        >
          + Новая глава
        </button>
        <button
          className="admin-refresh"
          onClick={() => {
            setSelectedChapterId(null)
            setShowCreateChapter(false)
            setChaptersError(null)
            setLoadingChapters(true)
            listChapters()
              .then(setChapters)
              .catch((err: Error) => setChaptersError(err.message))
              .finally(() => setLoadingChapters(false))
          }}
          disabled={loadingChapters}
        >
          {loadingChapters ? 'Обновление…' : '↻ Обновить список'}
        </button>

        {chaptersError && (
          <p className="admin-alert admin-error">{chaptersError}</p>
        )}

        <div className="admin-mission-list">
          {chapters.map((chapter) => (
            <button
              className={`admin-mission-row ${selectedChapterId === chapter.id ? 'is-active' : ''}`}
              key={chapter.id}
              onClick={() => {
                setSelectedChapterId(chapter.id)
                setShowCreateChapter(false)
                isDraftRestoredRef.current = false
              }}
            >
              <span className={`admin-status admin-status-${chapter.status}`}>
                {chapter.status}
              </span>
              <strong>{chapter.title}</strong>
              <small>
                {chapter.slug} · {chapter.seasonId}
              </small>
            </button>
          ))}
          {!loadingChapters && chapters.length === 0 && !chaptersError && (
            <p className="admin-muted">Глав пока нет.</p>
          )}
        </div>
      </aside>

      <section className="admin-editor">
        {showCreateChapter || editorChapter ? (
          <>
            <div className="admin-editor-title">
              <h2>
                {showCreateChapter ? 'Новая глава' : 'Редактирование главы'}
              </h2>
              {editorChapter && <code>{editorChapter.id}</code>}
              {editorChapter && (
                <span
                  className={`admin-status admin-status-${editorChapter.status}`}
                >
                  {editorChapter.status}
                </span>
              )}
            </div>

            {savingChapterError && (
              <p className="admin-alert admin-error">{savingChapterError}</p>
            )}
            {savingChapterNotice && (
              <p className="admin-alert admin-notice">{savingChapterNotice}</p>
            )}

            <div className="admin-grid">
              <label className="admin-span-2">
                Сезон *
                <select
                  value={chapterSeasonId}
                  onChange={(e) => {
                    setChapterSeasonId(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingChapter}
                >
                  <option value="">— выберите сезон —</option>
                  {selectableSeasons.map((season) => (
                    <option key={season.id} value={season.id}>
                      {season.title} ({season.status})
                    </option>
                  ))}
                </select>
              </label>

              <label className="admin-span-2">
                Название *
                <input
                  type="text"
                  value={chapterTitle}
                  onChange={(e) => {
                    setChapterTitle(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingChapter}
                  maxLength={255}
                />
              </label>

              <label className="admin-span-2">
                Slug (генерируется из названия)
                <input
                  type="text"
                  value={chapterSlug}
                  onChange={(e) => setChapterSlug(e.target.value)}
                  disabled={!canWrite || savingChapter}
                  readOnly
                  placeholder="сгенерируется автоматически"
                  maxLength={128}
                />
              </label>

              <label className="admin-span-2">
                Описание
                <textarea
                  value={chapterDescription}
                  onChange={(e) => {
                    setChapterDescription(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingChapter}
                  rows={4}
                />
              </label>

              <label>
                Порядок отображения (меньше — выше)
                <input
                  type="number"
                  min={0}
                  value={chapterSortOrder}
                  onChange={(e) => {
                    setChapterSortOrder(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingChapter}
                />
              </label>
            </div>

            <div className="admin-actions">
              {showCreateChapter ? (
                <>
                  <button
                    className="admin-primary"
                    onClick={handleCreateChapter}
                    disabled={!canWrite || savingChapter}
                  >
                    {savingChapter ? 'Создание…' : 'Создать'}
                  </button>
                  <button
                    className="admin-secondary"
                    onClick={() => setShowCreateChapter(false)}
                    disabled={savingChapter}
                  >
                    Отмена
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="admin-primary"
                    onClick={handleSaveChapter}
                    disabled={!canWrite || savingChapter}
                  >
                    {savingChapter ? 'Сохранение…' : 'Сохранить'}
                  </button>
                  {editorChapter?.status === 'draft' && (
                    <button
                      className="admin-publish"
                      onClick={handlePublishChapter}
                      disabled={!canWrite || savingChapter}
                    >
                      Опубликовать
                    </button>
                  )}
                  {editorChapter?.status === 'published' && (
                    <button
                      className="admin-danger"
                      onClick={handleArchiveChapter}
                      disabled={!canWrite || savingChapter}
                    >
                      Архивировать
                    </button>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <p className="admin-muted">Выберите главу или создайте новую.</p>
        )}
      </section>
    </div>
  )
}
