import { useEffect, useRef, useState } from 'react'
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
  // Внешний выбор сегмента (например, из дерева структуры в AdminTree).
  editingId?: string | null
  // Режим создания сегмента из дерева структуры: предвыбранная глава
  // (chapterId). Если задан и editingId не передан — открываем форму нового
  // сегмента с предзаполненным chapterId.
  initialChapterId?: string | null
}

// --- Черновик формы сегмента --------------------------------------------------
// Хранится в localStorage по ключу `draft_segment_<id>`. Компонент сохраняет
// изменённые поля формы, восстанавливает их при повторном открытии сегмента
// и удаляет после успешного сохранения.
type SegmentDraftForm = {
  chapterId: string
  title: string
  description: string
  contentJson: string
  sortOrder: string
  missions: Array<{ missionId: string; sortOrder: string }>
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
  return `draft_segment_${id}`
}

export function SegmentsEditor({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
  editingId,
  initialChapterId,
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

  // Черновик: изменённые поля помечаем «грязными» и храним в localStorage.
  const [isDirty, setIsDirty] = useState(false)
  const isDraftRestoredRef = useRef(false)

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
    // Заполняем форму из базы. Сбрасываем флаг «черновик уже применён»: тогда
    // restore-эффект ниже сработает повторно (поля изменились) и наложит
    // черновик поверх свежих данных базы, а не даст базе затереть его.
    isDraftRestoredRef.current = false
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

  // Восстановление черновика при открытии сегмента: данные из localStorage
  // накладываются поверх формы из базы. Применяется один раз на выбранный
  // сегмент (isDraftRestoredRef); флаг сбрасывается при выборе другого
  // сегмента и в fill-эффекте, чтобы повторная пересборка формы из базы
  // не затирала восстановленный черновик.
  useEffect(() => {
    if (selectedSegmentId === null || isDraftRestoredRef.current) return
    // Черновик восстанавливаем только для сегмента, выбранного в дереве.
    // При рассинхроне (selectedSegmentId !== editingId) восстановление
    // пропускаем, чтобы черновик не попал под чужой ключ.
    if (
      editingId !== null &&
      editingId !== undefined &&
      selectedSegmentId !== editingId
    )
      return
    const restored = loadDraft<SegmentDraftForm>(draftKeyFor(selectedSegmentId))
    if (restored === null) return
    setSegmentChapterId(restored.chapterId)
    setSegmentTitle(restored.title)
    setSegmentDescription(restored.description)
    setSegmentContentJson(restored.contentJson)
    setSegmentSortOrder(restored.sortOrder)
    setSegmentMissions(restored.missions)
    setIsDirty(true)
    isDraftRestoredRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedSegmentId,
    segmentChapterId,
    segmentTitle,
    segmentDescription,
    segmentContentJson,
    segmentSortOrder,
    segmentMissions,
  ])

  // Сохранение черновика: только после реальных правок (isDirty). Чистая
  // пересборка формы из базы черновик НЕ перезаписывает.
  useEffect(() => {
    if (selectedSegmentId === null || !isDirty) return
    saveDraft(draftKeyFor(selectedSegmentId), {
      chapterId: segmentChapterId,
      title: segmentTitle,
      description: segmentDescription,
      contentJson: segmentContentJson,
      sortOrder: segmentSortOrder,
      missions: segmentMissions,
    })
  }, [
    selectedSegmentId,
    segmentChapterId,
    segmentTitle,
    segmentDescription,
    segmentContentJson,
    segmentSortOrder,
    segmentMissions,
    isDirty,
  ])

  useEffect(() => {
    setShowCreateSegment(false)
    setSegmentError(null)
  }, [selectedSegmentId])

  // Внешний выбор сегмента (editingId из дерева структуры). Эффект выше
  // заполнит поля формы (и скроет create-режим) из найденного сегмента.
  useEffect(() => {
    if (editingId === null || editingId === undefined) return
    const segment = segments.find((item) => item.id === editingId)
    if (segment) {
      setSelectedSegmentId(segment.id)
      setIsDirty(false)
      isDraftRestoredRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, segments])

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
    const chapterId = segmentChapterId.trim()
    if (title.length < 1) { setSegmentError('Название части обязательно.'); return }
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
      setIsDirty(false)
      setSegmentNotice('Часть создана.')
      await reloadSegments()
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setSavingSegment(false) }
  }

  async function handleSaveSegment() {
    const s = selectedSegment()
    if (!s) return
    const title = segmentTitle.trim()
    const chapterId = segmentChapterId.trim()
    if (title.length < 1) { setSegmentError('Название части обязательно.'); return }
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
        title,
        description: segmentDescription.trim() || null,
        content,
        sort_order: sortOrder,
        linked_missions: segmentMissions
          .filter((m) => m.missionId.trim().length > 0)
          .map((m) => ({ mission_id: m.missionId.trim(), sort_order: Number(m.sortOrder || 0) })),
      })
      setSegments((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      removeDraft(draftKeyFor(s.id))
      setIsDirty(false)
      setSegmentNotice('Сохранено.')
      await reloadSegments()
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
      removeDraft(draftKeyFor(s.id))
      setIsDirty(false)
      setSegmentNotice('Часть опубликована.')
      await reloadSegments()
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
      removeDraft(draftKeyFor(s.id))
      setIsDirty(false)
      setSegmentNotice('Часть снята с публикации.')
      await reloadSegments()
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
      removeDraft(draftKeyFor(s.id))
      setIsDirty(false)
      setSegmentNotice('Часть архивирована.')
      await reloadSegments()
    } catch (err) { setSegmentError((err as Error).message) }
    finally { setPublishingSegment(false) }
  }

  async function reloadSegments() {
    try {
      const data = await listSegments()
      setSegments(data)
    } catch (err) {
      setSegmentsError((err as Error).message)
    }
  }

  function addSegmentMissionLink() {
    setIsDirty(true)
    setSegmentMissions((prev) => [...prev, { missionId: '', sortOrder: '0' }])
  }

  function changeSegmentMissionLink(index: number, missionId: string) {
    setIsDirty(true)
    if (!missionId.trim()) {
      setSegmentMissions((prev) =>
        prev.map((m, i) => (i === index ? { ...m, missionId } : m)),
      )
      return
    }
    const duplicate = segmentMissions.some(
      (m, i) => i !== index && m.missionId === missionId,
    )
    if (duplicate) {
      setSegmentError('Эта миссия уже добавлена в текущую часть.')
      return
    }
    setSegmentError(null)
    setSegmentMissions((prev) =>
      prev.map((m, i) => (i === index ? { ...m, missionId } : m)),
    )
  }

  function changeSegmentMissionSort(index: number, sortOrder: string) {
    setIsDirty(true)
    setSegmentMissions((prev) =>
      prev.map((m, i) => (i === index ? { ...m, sortOrder } : m)),
    )
  }

  function removeSegmentMissionLink(index: number) {
    setIsDirty(true)
    setSegmentMissions((prev) => prev.filter((_, i) => i !== index))
  }

  // Режим создания из дерева структуры: editingId не задан, а initialChapterId
  // предвыбирает главу для нового сегмента. Открываем форму создания.
  useEffect(() => {
    if (editingId !== null && editingId !== undefined) return
    if (initialChapterId === null || initialChapterId === undefined) return
    handleShowCreateSegment()
    setSegmentChapterId(initialChapterId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, initialChapterId])

  function handleShowCreateSegment() {
    setShowCreateSegment(true)
    setIsDirty(false)
    isDraftRestoredRef.current = false
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

  // Карта занятости: missionId -> названия сегментов (кроме текущего),
  // где миссия уже привязана. linkedMissions содержит только active
  // связи (backend _active_links), поэтому archived здесь нет.
  const missionUsage = segments.reduce((acc, seg) => {
    if (seg.id === selectedSegmentId) return acc
    for (const link of seg.linkedMissions) {
      const list = acc.get(link.missionId) ?? []
      list.push(seg.title)
      acc.set(link.missionId, list)
    }
    return acc
  }, new Map<string, string[]>())

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <>
          <button
            className="admin-primary"
            onClick={handleShowCreateSegment}
            disabled={!canWrite}
          >
            + Новая часть
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
                onClick={() => {
                  setSelectedSegmentId(segment.id)
                  setIsDirty(false)
                  isDraftRestoredRef.current = false
                }}
              >
                <strong>{segment.title}</strong>
                <small>{segment.slug}</small>
                <span className={`admin-status admin-status-${segment.status}`}>
                  {segment.status}
                </span>
              </button>
            ))}
            {!loadingSegments && segments.length === 0 && !segmentsError && (
              <p className="admin-muted">Частей нет.</p>
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
                  ? 'НОВАЯ ЧАСТЬ'
                  : selectedSegment() ? selectedSegment()!.id : '—'}
              </p>
              <h2>
                {showCreateSegment
                  ? 'Создание части'
                  : selectedSegment() ? 'Редактирование части' : 'Редактор части'}
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
              Выберите часть слева или создайте новую.
            </p>
          ) : (
            <>
              <label className="admin-field">
                <span>Название части</span>
                <input
                  type="text"
                  value={segmentTitle}
                  onChange={(e) => {
                    setSegmentTitle(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Slug (генерируется из названия)</span>
                <input
                  type="text"
                  value={segmentSlug}
                  onChange={(e) => setSegmentSlug(e.target.value)}
                  disabled={!canWrite}
                  readOnly
                  placeholder="сгенерируется автоматически"
                />
              </label>
              <label className="admin-field">
                <span>Chapter ID</span>
                <select
                  value={segmentChapterId}
                  onChange={(e) => {
                    setSegmentChapterId(e.target.value)
                    setSegmentMissions([])
                    setIsDirty(true)
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
                  onChange={(e) => {
                    setSegmentDescription(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Порядок сортировки (меньше = выше)</span>
                <input
                  type="number"
                  min={0}
                  value={segmentSortOrder}
                  onChange={(e) => {
                    setSegmentSortOrder(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite}
                />
              </label>
              <label className="admin-field">
                <span>Content (JSON)</span>
                <textarea
                  rows={8}
                  className="admin-code"
                  value={segmentContentJson}
                  onChange={(e) => {
                    setSegmentContentJson(e.target.value)
                    setIsDirty(true)
                  }}
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
                          {missionsForLink.map((m) => {
                            const usedIn = missionUsage.get(m.id) ?? []
                            return (
                              <option key={m.id} value={m.id}>
                                {m.title} · {m.slug} [{m.status}]
                                {usedIn.length > 0
                                  ? ` — уже в: ${usedIn.join(', ')}`
                                  : ''}
                              </option>
                            )
                          })}
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
