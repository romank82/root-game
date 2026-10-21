import { useEffect, useState } from 'react'
import {
  archiveSegment,
  createSegment,
  listAdminMissions,
  listChapters,
  listSegments,
  publishSegment,
  unpublishSegment,
  updateSegment,
  type AdminChapter,
  type AdminSegment,
  type AdminUser,
} from '../../api/adminApi'

type SegmentsEditorProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

export function SegmentsEditor({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
}: SegmentsEditorProps) {
  const [segments, setSegments] = useState<AdminSegment[]>([])
  const [loadingSegments, setLoadingSegments] = useState(false)
  const [segmentsError, setSegmentsError] = useState<string | null>(null)
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)

  const [segmentTitle, setSegmentTitle] = useState('')
  const [segmentSlug, setSegmentSlug] = useState('')
  const [segmentDescription, setSegmentDescription] = useState('')
  const [segmentChapterId, setSegmentChapterId] = useState('')
  const [segmentSortOrder, setSegmentSortOrder] = useState('0')
  const [segmentContentJson, setSegmentContentJson] = useState('{}')
  const [segmentMissions, setSegmentMissions] = useState<
    Array<{ missionId: string; sortOrder: string }>
  >([])
  const [savingSegment, setSavingSegment] = useState(false)
  const [segmentError, setSegmentError] = useState<string | null>(null)
  const [segmentNotice, setSegmentNotice] = useState<string | null>(null)
  const [publishingSegment, setPublishingSegment] = useState(false)
  const [showCreateSegment, setShowCreateSegment] = useState(false)

  const [missionsForLink, setMissionsForLink] = useState<
    Array<{ id: string; slug: string; title: string; chapterId: string; status: string }>
  >([])
  const [loadingMissionsForLink, setLoadingMissionsForLink] = useState(false)
  const [missionsForLinkError, setMissionsForLinkError] = useState<string | null>(null)
  const [chapters, setChapters] = useState<AdminChapter[]>([])

  // Загрузка сегментов (в AdminApp: эффект при section === 'content').
  useEffect(() => {
    let cancelled = false
    setLoadingSegments(true)
    setSegmentsError(null)
    listSegments()
      .then((data) => {
        if (cancelled) return
        setSegments(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setSegmentsError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingSegments(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Загрузка глав для dropdown Chapter ID.
  useEffect(() => {
    let cancelled = false
    listChapters()
      .then((data) => {
        if (cancelled) return
        setChapters(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setSegmentsError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const s = selectedSegment()
    if (!s) {
      setSegmentError(null)
      setSegmentNotice(null)
      return
    }
    setSegmentTitle(s.title)
    setSegmentSlug(s.slug)
    setSegmentDescription(s.description ?? '')
    setSegmentChapterId(s.chapterId)
    setSegmentSortOrder(String(s.sortOrder))
    setSegmentContentJson(JSON.stringify(s.content ?? {}, null, 2))
    setSegmentMissions(
      s.linkedMissions.map((link) => ({
        missionId: link.missionId,
        sortOrder: String(link.sortOrder),
      })),
    )
    setSegmentError(null)
    setSegmentNotice(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSegmentId, segments])

  useEffect(() => {
    setShowCreateSegment(false)
    setSegmentError(null)
  }, [selectedSegmentId])

  // Загрузка миссий для привязки (в AdminApp: эффект при section === 'content').

  useEffect(() => {
    if (!segmentChapterId) {
      setMissionsForLink([])
      setMissionsForLinkError(null)
      setLoadingMissionsForLink(false)
      return
    }

    let cancelled = false
    setLoadingMissionsForLink(true)
    setMissionsForLinkError(null)
    listAdminMissions(segmentChapterId)
      .then((data) => {
        if (cancelled) return
        setMissionsForLink(
          data.map((m) => ({
            id: m.id,
            slug: m.slug,
            title: m.title,
            chapterId: m.chapterId,
            status: m.status,
          })),
        )
      })
      .catch((err: Error) => {
        if (cancelled) return
        setMissionsForLinkError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingMissionsForLink(false)
      })
    return () => {
      cancelled = true
    }
  }, [segmentChapterId])

  function selectedSegment(): AdminSegment | null {
    if (selectedSegmentId === null) return null
    return segments.find((s) => s.id === selectedSegmentId) ?? null
  }

  function parseSegmentContentJson(): Record<string, unknown> {
    try {
      const parsed = JSON.parse(segmentContentJson)
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        throw new Error('Content: ожидается JSON-объект.')
      }
      return parsed as Record<string, unknown>
    } catch (err) {
      throw new Error(
        err instanceof Error ? `Content: ${err.message}` : 'Content: некорректный JSON.',
      )
    }
  }

  async function handleCreateSegment() {
    const title = segmentTitle.trim()
    const slug = segmentSlug.trim()
    const chapterId = segmentChapterId.trim()
    if (title.length < 1) { setSegmentError('Название сегмента обязательно.'); return }
    if (slug.length < 3) { setSegmentError('Slug минимум 3 символа.'); return }
    if (chapterId.length < 1) { setSegmentError('Chapter ID обязателен.'); return }
    let content: Record<string, unknown>
    try { content = parseSegmentContentJson() }
    catch (err) { setSegmentError((err as Error).message); return }
    const sortOrder = Number.parseInt(segmentSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) { setSegmentError('Порядок сортировки — целое ≥ 0.'); return }

    setSavingSegment(true); setSegmentError(null)
    try {
      const created = await createSegment({
        chapter_id: chapterId,
        slug,
        title,
        description: segmentDescription.trim() || null,
        content,
        sort_order: sortOrder,
        linked_missions: segmentMissions
          .filter((m) => m.missionId.trim().length > 0)
          .map((m) => ({ mission_id: m.missionId.trim(), sort_order: Number(m.sortOrder || 0) })),
      })
      setSegments((prev) => [...prev, created])
      setSelectedSegmentId(created.id)
      setShowCreateSegment(false)
      setSegmentNotice('Сегмент создан.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setSavingSegment(false) }
  }

  async function handleSaveSegment() {
    const s = selectedSegment()
    if (!s) return
    const title = segmentTitle.trim()
    const slug = segmentSlug.trim()
    const chapterId = segmentChapterId.trim()
    if (title.length < 1) { setSegmentError('Название сегмента обязательно.'); return }
    if (slug.length < 3) { setSegmentError('Slug минимум 3 символа.'); return }
    if (chapterId.length < 1) { setSegmentError('Chapter ID обязателен.'); return }
    let content: Record<string, unknown>
    try { content = parseSegmentContentJson() }
    catch (err) { setSegmentError((err as Error).message); return }
    const sortOrder = Number.parseInt(segmentSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) { setSegmentError('Порядок сортировки — целое ≥ 0.'); return }

    setSavingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await updateSegment(s.id, {
        chapter_id: chapterId,
        slug,
        title,
        description: segmentDescription.trim() || null,
        content,
        sort_order: sortOrder,
        linked_missions: segmentMissions
          .filter((m) => m.missionId.trim().length > 0)
          .map((m) => ({ mission_id: m.missionId.trim(), sort_order: Number(m.sortOrder || 0) })),
      })
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сохранено.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setSavingSegment(false) }
  }

  async function handlePublishSegment() {
    const s = selectedSegment()
    if (!s) return
    setPublishingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await publishSegment(s.id)
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сегмент опубликован.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  async function handleUnpublishSegment() {
    const s = selectedSegment()
    if (!s) return
    setPublishingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await unpublishSegment(s.id)
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сегмент снят с публикации.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  async function handleArchiveSegment() {
    const s = selectedSegment()
    if (!s) return
    setPublishingSegment(true); setSegmentError(null); setSegmentNotice(null)
    try {
      const updated = await archiveSegment(s.id)
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      setSegmentNotice('Сегмент архивирован.')
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  function addSegmentMissionLink() {
    setSegmentMissions((prev) => [...prev, { missionId: '', sortOrder: '0' }])
  }

  function changeSegmentMissionLink(index: number, missionId: string) {
    setSegmentMissions((prev) =>
      prev.map((m, i) => (i === index ? { ...m, missionId } : m)),
    )
  }

  function changeSegmentMissionSort(index: number, sortOrder: string) {
    setSegmentMissions((prev) =>
      prev.map((m, i) => (i === index ? { ...m, sortOrder } : m)),
    )
  }

  function removeSegmentMissionLink(index: number) {
    setSegmentMissions((prev) => prev.filter((_, i) => i !== index))
  }

  function handleShowCreateSegment() {
    setShowCreateSegment(true)
    setSegmentTitle('')
    setSegmentSlug('')
    setSegmentDescription('')
    setSegmentChapterId('')
    setSegmentSortOrder('0')
    setSegmentContentJson('{}')
    setSegmentMissions([])
    setSegmentError(null)
    setSegmentNotice(null)
  }

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <>
          <button
            className="admin-primary"
            onClick={handleShowCreateSegment}
            disabled={!canWrite}
          >
            + Новый сегмент
          </button>
          <button
            className="admin-secondary"
            onClick={() => {
              setLoadingSegments(true)
              setSegmentsError(null)
              listSegments()
                .then((data) => setSegments(data))
                .catch((err: Error) => setSegmentsError(err.message))
                .finally(() => setLoadingSegments(false))
            }}
          >
            ↻ Обновить список
          </button>

          {segmentsError && (
            <p className="admin-alert admin-error">{segmentsError}</p>
          )}

          <div className="admin-mission-list">
            {segments.map((segment) => (
              <button
                key={segment.id}
                className={selectedSegmentId === segment.id ? 'is-active' : ''}
                onClick={() => setSelectedSegmentId(segment.id)}
              >
                <strong>{segment.title}</strong>
                <small>{segment.slug}</small>
                <span className={`admin-status admin-status-${segment.status}`}>
                  {segment.status}
                </span>
              </button>
            ))}
            {!loadingSegments && segments.length === 0 && !segmentsError && (
              <p className="admin-muted">Сегментов нет.</p>
            )}
          </div>
        </>
      </aside>

      <section className="admin-editor">
        <>
          <div className="admin-editor-title">
            <div>
              <p className="admin-kicker">
                {showCreateSegment
                  ? 'НОВЫЙ СЕГМЕНТ'
                  : selectedSegment() ? selectedSegment()!.id : '—'}
              </p>
              <h2>
                {showCreateSegment
                  ? 'Создание сегмента'
                  : selectedSegment() ? 'Редактирование сегмента' : 'Редактор сегмента'}
              </h2>
              {selectedSegment() && !showCreateSegment && (
                <span
                  className={`admin-status admin-status-${selectedSegment()!.status}`}
                >
                  {selectedSegment()!.status}
                </span>
              )}
            </div>
          </div>

          {segmentError && (
            <p className="admin-alert admin-error">{segmentError}</p>
          )}
          {segmentNotice && (
            <p className="admin-alert admin-notice">{segmentNotice}</p>
          )}

          {(!showCreateSegment && selectedSegment() === null) ? (
            <p className="admin-muted">
              Выберите сегмент слева или создайте новый.
            </p>
          ) : (
            <>
              <label className="admin-field">
                <span>Название сегмента</span>
                <input
                  type="text"
                  value={segmentTitle}
                  onChange={(e) => setSegmentTitle(e.target.value)}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Slug</span>
                <input
                  type="text"
                  value={segmentSlug}
                  onChange={(e) => setSegmentSlug(e.target.value)}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Chapter ID</span>
                <select
                  value={segmentChapterId}
                  onChange={(e) => {
                    setSegmentChapterId(e.target.value)
                    setSegmentMissions([])
                  }}
                  disabled={!canWrite}
                >
                  <option value="">— Выберите главу —</option>
                  {chapters
                    .filter((c) => c.status !== 'archived')
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title} ({c.slug})
                      </option>
                    ))}
                </select>
              </label>
              <label className="admin-field">
                <span>Описание</span>
                <textarea
                  rows={3}
                  value={segmentDescription}
                  onChange={(e) => setSegmentDescription(e.target.value)}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Порядок сортировки (меньше = выше)</span>
                <input
                  type="number"
                  min={0}
                  value={segmentSortOrder}
                  onChange={(e) => setSegmentSortOrder(e.target.value)}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Content (JSON)</span>
                <textarea
                  rows={8}
                  className="admin-code"
                  value={segmentContentJson}
                  onChange={(e) => setSegmentContentJson(e.target.value)}
                  disabled={!canWrite}
                  spellCheck={false}
                />
              </label>


              <section>
                <h3 style={{ marginTop: 24 }}>Привязанные миссии</h3>

                {!segmentChapterId && (
                  <p className="admin-muted">
                    Выберите главу, чтобы увидеть миссии.
                  </p>
                )}

                {segmentChapterId && (
                  <>
                    {loadingMissionsForLink && (
                      <p className="admin-muted">Загрузка миссий…</p>
                    )}
                    {missionsForLinkError && (
                      <p className="admin-alert admin-error">
                        {missionsForLinkError}
                      </p>
                    )}
                    {!loadingMissionsForLink &&
                      !missionsForLinkError &&
                      missionsForLink.length === 0 && (
                        <p className="admin-muted">
                          В этой главе нет опубликованных миссий.
                        </p>
                      )}

                    <button
                      className="admin-secondary"
                      onClick={addSegmentMissionLink}
                      disabled={!canWrite}
                    >
                      + Добавить миссию
                    </button>

                    {segmentMissions.map((link, index) => (
                      <div key={index} className="admin-link-row">
                        <select
                          value={link.missionId}
                          disabled={!canWrite}
                          onChange={(e) =>
                            changeSegmentMissionLink(index, e.target.value)
                          }
                        >
                          {link.missionId === '' && (
                            <option value="" disabled>
                              Выберите миссию…
                            </option>
                          )}
                          {missionsForLink.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.title} · {m.slug} [{m.status}]
                            </option>
                          ))}
                        </select>
                        <input
                          type="number"
                          value={link.sortOrder}
                          disabled={!canWrite}
                          onChange={(e) =>
                            changeSegmentMissionSort(index, e.target.value)
                          }
                        />
                        <button
                          className="admin-danger"
                          onClick={() => removeSegmentMissionLink(index)}
                          disabled={!canWrite}
                        >
                          Удалить
                        </button>
                      </div>
                    ))}

                    {segmentMissions.length === 0 &&
                      loadingMissionsForLink === false &&
                      missionsForLink.length > 0 && (
                        <p className="admin-muted">
                          Миссии не привязаны. Публикация требует ≥1
                          published миссии той же главы.
                        </p>
                      )}
                  </>
                )}
              </section>

              <div className="admin-actions">
                {showCreateSegment ? (
                  <>
                    <button
                      className="admin-primary"
                      onClick={handleCreateSegment}
                      disabled={!canWrite || savingSegment}
                    >
                      {savingSegment ? 'Создание…' : 'Создать'}
                    </button>
                    <button
                      className="admin-secondary"
                      onClick={() => setShowCreateSegment(false)}
                      disabled={savingSegment}
                    >
                      Отмена
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="admin-primary"
                      onClick={handleSaveSegment}
                      disabled={!canWrite || savingSegment}
                    >
                      {savingSegment ? 'Сохранение…' : 'Сохранить'}
                    </button>

                    {selectedSegment()?.status === 'draft' && (
                      <button
                        className="admin-publish"
                        onClick={handlePublishSegment}
                        disabled={!canWrite || publishingSegment}
                      >
                        {publishingSegment ? 'Публикация…' : 'Опубликовать'}
                      </button>
                    )}

                    {selectedSegment()?.status === 'published' && (
                      <button
                        className="admin-secondary"
                        onClick={handleUnpublishSegment}
                        disabled={!canWrite || publishingSegment}
                      >
                        Снять с публикации
                      </button>
                    )}

                    {selectedSegment()?.status === 'published' && (
                      <button
                        className="admin-danger"
                        onClick={handleArchiveSegment}
                        disabled={!canWrite || publishingSegment}
                      >
                        Архивировать
                      </button>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </>
      </section>
    </div>
  )
}
