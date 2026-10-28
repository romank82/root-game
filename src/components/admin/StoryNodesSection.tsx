import { useEffect, useRef, useState } from 'react'
import {
  archiveStoryNode,
  createStoryNode,
  listChapters,
  listStoryNodes,
  publishStoryNode,
  updateStoryNode,
  type AdminChapter,
  type AdminStoryNode,
  type AdminUser,
} from '../../api/adminApi'

type StoryNodesSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  // Внешний выбор узла (например, из дерева структуры в AdminTree).
  editingId?: string | null
  // Режим создания узла из дерева структуры: предвыбранная глава (chapterId).
  // Если задан и editingId не передан — открываем форму нового узла
  // с предзаполненным chapterId.
  initialChapterId?: string | null
}

// --- Черновик формы сюжетного узла -------------------------------------------
// Хранится в localStorage по ключу `draft_story_node_<id>`. Компонент
// сохраняет изменённые поля формы, восстанавливает их при повторном открытии
// узла и удаляет после успешного сохранения.
type StoryNodeDraftForm = {
  chapterId: string
  title: string
  body: string
  presentationType: string
  content: string
  sortOrder: string
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
  return `draft_story_node_${id}`
}

export function StoryNodesSection({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
  editingId,
  initialChapterId,
}: StoryNodesSectionProps) {
  const [storyNodes, setStoryNodes] = useState<AdminStoryNode[]>([])
  const [selectedStoryNodeId, setSelectedStoryNodeId] = useState<string | null>(
    null,
  )
  const [loadingStoryNodes, setLoadingStoryNodes] = useState(false)
  const [storyNodesError, setStoryNodesError] = useState<string | null>(null)
  const [showCreateStoryNode, setShowCreateStoryNode] = useState(false)
  const [storyNodeChapterId, setStoryNodeChapterId] = useState('')
  const [storyNodeSlug, setStoryNodeSlug] = useState('')
  const [storyNodeTitle, setStoryNodeTitle] = useState('')
  const [storyNodeBody, setStoryNodeBody] = useState('')
  const [storyNodePresentationType, setStoryNodePresentationType] =
    useState('')
  const [storyNodeContent, setStoryNodeContent] = useState('{}')
  const [storyNodeSortOrder, setStoryNodeSortOrder] = useState('0')
  const [savingStoryNode, setSavingStoryNode] = useState(false)
  const [savingStoryNodeError, setSavingStoryNodeError] = useState<
    string | null
  >(null)
  const [savingStoryNodeNotice, setSavingStoryNodeNotice] = useState<
    string | null
  >(null)
  const [chapters, setChapters] = useState<AdminChapter[]>([])

  // Черновик: изменённые поля помечаем «грязными» и храним в localStorage.
  const [isDirty, setIsDirty] = useState(false)
  const isDraftRestoredRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    setLoadingStoryNodes(true)
    setStoryNodesError(null)
    listStoryNodes()
      .then((data) => {
        if (cancelled) return
        setStoryNodes(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setStoryNodesError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoadingStoryNodes(false)
      })
    listChapters()
      .then((data) => {
        if (cancelled) return
        setChapters(data)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setStoryNodesError((prev) => prev ?? err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function selectedStoryNode(): AdminStoryNode | null {
    if (selectedStoryNodeId === null) return null
    return storyNodes.find((item) => item.id === selectedStoryNodeId) ?? null
  }

  useEffect(() => {
    const node = storyNodes.find((item) => item.id === selectedStoryNodeId)
    if (!node) return
    // Заполняем форму из базы. Сбрасываем флаг «черновик уже применён»: тогда
    // restore-эффект ниже сработает повторно (поля изменились) и наложит
    // черновик поверх свежих данных базы, а не даст базе затереть его.
    isDraftRestoredRef.current = false
    setStoryNodeChapterId(node.chapterId)
    setStoryNodeSlug(node.slug)
    setStoryNodeTitle(node.title)
    setStoryNodeBody(node.body)
    setStoryNodePresentationType(node.presentationType)
    setStoryNodeContent(
      node.content && Object.keys(node.content).length > 0
        ? JSON.stringify(node.content, null, 2)
        : '{}',
    )
    setStoryNodeSortOrder(String(node.sortOrder))
  }, [selectedStoryNodeId, storyNodes])

  // Восстановление черновика при открытии узла: данные из localStorage
  // накладываются поверх формы из базы. Применяется один раз на выбранный
  // узел (isDraftRestoredRef); флаг сбрасывается при выборе другого узла и
  // в fill-эффекте, чтобы повторная пересборка формы из базы не затирала
  // восстановленный черновик.
  useEffect(() => {
    if (selectedStoryNodeId === null || isDraftRestoredRef.current) return
    // Черновик восстанавливаем только для узла, выбранного в дереве.
    // При рассинхроне (selectedStoryNodeId !== editingId) восстановление
    // пропускаем, чтобы черновик не попал под чужой ключ.
    if (
      editingId !== null &&
      editingId !== undefined &&
      selectedStoryNodeId !== editingId
    )
      return
    const restored = loadDraft<StoryNodeDraftForm>(
      draftKeyFor(selectedStoryNodeId),
    )
    if (restored === null) return
    setStoryNodeChapterId(restored.chapterId)
    setStoryNodeTitle(restored.title)
    setStoryNodeBody(restored.body)
    setStoryNodePresentationType(restored.presentationType)
    setStoryNodeContent(restored.content)
    setStoryNodeSortOrder(restored.sortOrder)
    setIsDirty(true)
    isDraftRestoredRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedStoryNodeId,
    storyNodeChapterId,
    storyNodeTitle,
    storyNodeBody,
    storyNodePresentationType,
    storyNodeContent,
    storyNodeSortOrder,
  ])

  // Сохранение черновика: только после реальных правок (isDirty). Чистая
  // пересборка формы из базы черновик НЕ перезаписывает.
  useEffect(() => {
    if (selectedStoryNodeId === null || !isDirty) return
    saveDraft(draftKeyFor(selectedStoryNodeId), {
      chapterId: storyNodeChapterId,
      title: storyNodeTitle,
      body: storyNodeBody,
      presentationType: storyNodePresentationType,
      content: storyNodeContent,
      sortOrder: storyNodeSortOrder,
    })
  }, [
    selectedStoryNodeId,
    storyNodeChapterId,
    storyNodeTitle,
    storyNodeBody,
    storyNodePresentationType,
    storyNodeContent,
    storyNodeSortOrder,
    isDirty,
  ])

  // Внешний выбор узла (editingId из дерева структуры). Внутренний эффект
  // выше заполнит поля формы из найденного узла.
  useEffect(() => {
    if (editingId === null || editingId === undefined) return
    const node = storyNodes.find((item) => item.id === editingId)
    if (node) {
      setShowCreateStoryNode(false)
      setSelectedStoryNodeId(node.id)
      setIsDirty(false)
      isDraftRestoredRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, storyNodes])

  // Режим создания из дерева структуры: editingId не задан, а initialChapterId
  // предвыбирает главу для нового узла. Открываем форму создания.
  useEffect(() => {
    if (editingId !== null && editingId !== undefined) return
    if (initialChapterId === null || initialChapterId === undefined) return
    handleShowCreateStoryNode()
    setStoryNodeChapterId(initialChapterId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingId, initialChapterId])

  function handleShowCreateStoryNode() {
    setShowCreateStoryNode(true)
    setSelectedStoryNodeId(null)
    setIsDirty(false)
    isDraftRestoredRef.current = false
    setStoryNodeChapterId('')
    setStoryNodeSlug('')
    setStoryNodeTitle('')
    setStoryNodeBody('')
    setStoryNodePresentationType('archive')
    setStoryNodeContent('{}')
    setStoryNodeSortOrder('0')
    setSavingStoryNodeError(null)
    setSavingStoryNodeNotice(null)
  }

  function parseSortOrder(): number | null {
    const raw = storyNodeSortOrder.trim()
    if (raw === '') return 0
    const parsed = Number.parseInt(raw, 10)
    if (!Number.isFinite(parsed) || parsed < 0) {
      setSavingStoryNodeError(
        'Порядок отображения — неотрицательное целое число.',
      )
      return null
    }
    return parsed
  }

  function parseContent(): Record<string, unknown> | null {
    const raw = storyNodeContent.trim()
    if (raw === '') return {}
    try {
      const parsed: unknown = JSON.parse(raw)
      if (
        parsed === null ||
        typeof parsed !== 'object' ||
        Array.isArray(parsed)
      ) {
        setSavingStoryNodeError(
          'Content должен быть JSON-объектом (например, {}).',
        )
        return null
      }
      return parsed as Record<string, unknown>
    } catch {
      setSavingStoryNodeError('Content — некорректный JSON.')
      return null
    }
  }

  async function handleCreateStoryNode() {
    const title = storyNodeTitle.trim()
    if (title.length === 0) {
      setSavingStoryNodeError('Укажите название сюжетного узла.')
      return
    }
    const body = storyNodeBody.trim()
    if (body.length === 0) {
      setSavingStoryNodeError('Укажите текст (body) сюжетного узла.')
      return
    }
    const chapterId = storyNodeChapterId.trim()
    if (chapterId.length === 0) {
      setSavingStoryNodeError('Выберите главу.')
      return
    }
    const sortOrder = parseSortOrder()
    if (sortOrder === null) return
    const content = parseContent()
    if (content === null) return
    const presentationType = storyNodePresentationType.trim()
    if (presentationType.length === 0) {
      setSavingStoryNodeError('Укажите presentation type.')
      return
    }

    setSavingStoryNode(true)
    setSavingStoryNodeError(null)
    setSavingStoryNodeNotice(null)
    try {
      const created = await createStoryNode({
        chapter_id: chapterId,
        title,
        body,
        presentation_type: presentationType,
        content,
        sort_order: sortOrder,
      })
      setStoryNodes((prev) => [...prev, created])
      setShowCreateStoryNode(false)
      setSelectedStoryNodeId(created.id)
      setIsDirty(false)
      setSavingStoryNodeNotice('Сюжетный узел создан.')
    } catch (err) {
      setSavingStoryNodeError((err as Error).message)
    } finally {
      setSavingStoryNode(false)
    }
  }

  async function handleSaveStoryNode() {
    const node = selectedStoryNode()
    if (!node) return

    const title = storyNodeTitle.trim()
    if (title.length === 0) {
      setSavingStoryNodeError('Название сюжетного узла не может быть пустым.')
      return
    }
    const body = storyNodeBody.trim()
    if (body.length === 0) {
      setSavingStoryNodeError('Body не может быть пустым.')
      return
    }
    const chapterId = storyNodeChapterId.trim()
    if (chapterId.length === 0) {
      setSavingStoryNodeError('Выберите главу.')
      return
    }
    const sortOrder = parseSortOrder()
    if (sortOrder === null) return
    const content = parseContent()
    if (content === null) return
    const presentationType = storyNodePresentationType.trim()
    if (presentationType.length === 0) {
      setSavingStoryNodeError('Укажите presentation type.')
      return
    }

    setSavingStoryNode(true)
    setSavingStoryNodeError(null)
    setSavingStoryNodeNotice(null)
    try {
      const updated = await updateStoryNode(node.id, {
        chapter_id: chapterId,
        title,
        body,
        presentation_type: presentationType,
        content,
        sort_order: sortOrder,
      })
      setStoryNodes((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      removeDraft(draftKeyFor(node.id))
      setIsDirty(false)
      setSavingStoryNodeNotice('Сюжетный узел сохранён.')
    } catch (err) {
      setSavingStoryNodeError((err as Error).message)
    } finally {
      setSavingStoryNode(false)
    }
  }

async function handlePublishStoryNode() {
    const node = selectedStoryNode()
    if (!node) return

    setSavingStoryNode(true)
    setSavingStoryNodeError(null)
    setSavingStoryNodeNotice(null)
    try {
      const updated = await publishStoryNode(node.id)
      setStoryNodes((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      removeDraft(draftKeyFor(node.id))
      setIsDirty(false)
      setSavingStoryNodeNotice('Сюжетный узел опубликован.')
    } catch (err) {
      setSavingStoryNodeError((err as Error).message)
    } finally {
      setSavingStoryNode(false)
    }
  }

  async function handleArchiveStoryNode() {
    const node = selectedStoryNode()
    if (!node) return

    setSavingStoryNode(true)
    setSavingStoryNodeError(null)
    setSavingStoryNodeNotice(null)
    try {
      const updated = await archiveStoryNode(node.id)
      setStoryNodes((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      )
      removeDraft(draftKeyFor(node.id))
      setIsDirty(false)
      setSavingStoryNodeNotice('Сюжетный узел архивирован.')
    } catch (err) {
      setSavingStoryNodeError((err as Error).message)
    } finally {
      setSavingStoryNode(false)
    }
  }

  const editorStoryNode = selectedStoryNode()
  const selectableChapters = chapters.filter(
    (chapter) => chapter.status !== 'archived',
  )

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <button
          className="admin-primary"
          onClick={handleShowCreateStoryNode}
          disabled={!canWrite}
        >
          + Новый узел
        </button>
        <button
          className="admin-refresh"
          onClick={() => {
            setSelectedStoryNodeId(null)
            setShowCreateStoryNode(false)
            setStoryNodesError(null)
            setLoadingStoryNodes(true)
            listStoryNodes()
              .then(setStoryNodes)
              .catch((err: Error) => setStoryNodesError(err.message))
              .finally(() => setLoadingStoryNodes(false))
          }}
          disabled={loadingStoryNodes}
        >
          {loadingStoryNodes ? 'Обновление…' : '↻ Обновить список'}
        </button>

        {storyNodesError && (
          <p className="admin-alert admin-error">{storyNodesError}</p>
        )}

        <div className="admin-mission-list">
          {storyNodes.map((node) => (
            <button
              className={`admin-mission-row ${selectedStoryNodeId === node.id ? 'is-active' : ''}`}
              key={node.id}
              onClick={() => {
                setSelectedStoryNodeId(node.id)
                setShowCreateStoryNode(false)
                setIsDirty(false)
                isDraftRestoredRef.current = false
              }}
            >
              <span className={`admin-status admin-status-${node.status}`}>
                {node.status}
              </span>
              <strong>{node.title}</strong>
              <small>
                {node.slug} · {node.chapterId}
              </small>
            </button>
          ))}
          {!loadingStoryNodes && storyNodes.length === 0 && !storyNodesError && (
            <p className="admin-muted">Сюжетных узлов пока нет.</p>
          )}
        </div>
      </aside>

      <section className="admin-editor">
        {showCreateStoryNode || editorStoryNode ? (
          <>
            <div className="admin-editor-title">
              <h2>
                {showCreateStoryNode
                  ? 'Новый сюжетный узел'
                  : 'Редактирование сюжетного узла'}
              </h2>
              {editorStoryNode && <code>{editorStoryNode.id}</code>}
              {editorStoryNode && (
                <span
                  className={`admin-status admin-status-${editorStoryNode.status}`}
                >
                  {editorStoryNode.status}
                </span>
              )}
            </div>

            {savingStoryNodeError && (
              <p className="admin-alert admin-error">{savingStoryNodeError}</p>
            )}
            {savingStoryNodeNotice && (
              <p className="admin-alert admin-notice">
                {savingStoryNodeNotice}
              </p>
            )}

            <div className="admin-grid">
              <label className="admin-span-2">
                Глава *
                <select
                  value={storyNodeChapterId}
                  onChange={(e) => {
                    setStoryNodeChapterId(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingStoryNode}
                >
                  <option value="">— выберите главу —</option>
                  {selectableChapters.map((chapter) => (
                    <option key={chapter.id} value={chapter.id}>
                      {chapter.title} ({chapter.status})
                    </option>
                  ))}
                </select>
              </label>

              <label className="admin-span-2">
                Название *
                <input
                  type="text"
                  value={storyNodeTitle}
                  onChange={(e) => {
                    setStoryNodeTitle(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingStoryNode}
                  maxLength={255}
                />
              </label>

              <label className="admin-span-2">
                Slug (генерируется из названия)
                <input
                  type="text"
                  value={storyNodeSlug}
                  onChange={(e) => setStoryNodeSlug(e.target.value)}
                  disabled={!canWrite || savingStoryNode}
                  readOnly
                  placeholder="сгенерируется автоматически"
                  maxLength={128}
                />
              </label>

              <label className="admin-span-2">
                Текст (body) *
                <textarea
                  value={storyNodeBody}
                  onChange={(e) => {
                    setStoryNodeBody(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingStoryNode}
                  rows={6}
                />
              </label>

              <label>
                Presentation type
                <input
                  type="text"
                  value={storyNodePresentationType}
                  onChange={(e) => {
                    setStoryNodePresentationType(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingStoryNode}
                  maxLength={32}
                />
              </label>

              <label>
                Порядок отображения (меньше — выше)
                <input
                  type="number"
                  min={0}
                  value={storyNodeSortOrder}
                  onChange={(e) => {
                    setStoryNodeSortOrder(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingStoryNode}
                />
              </label>

              <label className="admin-span-2">
                Content (JSON)
                <textarea
                  value={storyNodeContent}
                  onChange={(e) => {
                    setStoryNodeContent(e.target.value)
                    setIsDirty(true)
                  }}
                  disabled={!canWrite || savingStoryNode}
                  rows={5}
                  placeholder="{}"
                />
              </label>
            </div>

            <div className="admin-actions">
              {showCreateStoryNode ? (
                <>
                  <button
                    className="admin-primary"
                    onClick={handleCreateStoryNode}
                    disabled={!canWrite || savingStoryNode}
                  >
                    {savingStoryNode ? 'Создание…' : 'Создать'}
                  </button>
                  <button
                    className="admin-secondary"
                    onClick={() => setShowCreateStoryNode(false)}
                    disabled={savingStoryNode}
                  >
                    Отмена
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="admin-primary"
                    onClick={handleSaveStoryNode}
                    disabled={!canWrite || savingStoryNode}
                  >
                    {savingStoryNode ? 'Сохранение…' : 'Сохранить'}
                  </button>
                  {editorStoryNode?.status === 'draft' && (
                    <button
                      className="admin-publish"
                      onClick={handlePublishStoryNode}
                      disabled={!canWrite || savingStoryNode}
                    >
                      Опубликовать
                    </button>
                  )}
                  {editorStoryNode?.status === 'published' && (
                    <button
                      className="admin-danger"
                      onClick={handleArchiveStoryNode}
                      disabled={!canWrite || savingStoryNode}
                    >
                      Архивировать
                    </button>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <p className="admin-muted">
            Выберите сюжетный узел или создайте новый.
          </p>
        )}
      </section>
    </div>
  )
}
