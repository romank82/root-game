import { useEffect, useMemo, useState } from 'react'
import { ChaptersSection } from './ChaptersSection'
import { MissionsSection } from './MissionsSection'
import { SeasonsSection } from './SeasonsSection'
import { SegmentsEditor } from './SegmentsEditor'
import { StoryNodesSection } from './StoryNodesSection'
import {
  listAdminMissions,
  listChapters,
  listSeasons,
  listSegments,
  listStoryNodes,
  type AdminARObject,
  type AdminChapter,
  type AdminGeoZone,
  type AdminMinigameProfile,
  type AdminMission,
  type AdminSeason,
  type AdminSegment,
  type AdminStoryNode,
  type AdminUser,
  type KeyItem,
} from '../../api/adminApi'

// Типы выбранного элемента и ключи localStorage для задела под черновики.
type SelectedType = 'season' | 'chapter' | 'storyNode' | 'segment' | 'mission'
type SelectedItem = { type: SelectedType; id: string }

// Контекст создания сущности из дерева структуры: тип + родительский узел.
// Родитель зависит от типа: глава -> season.id; сегмент/storyNode -> chapter.id;
// миссия -> segment.id (сюжетная) либо chapter.id/season.id (командная и
// индивидуальная, создаются на уровне главы/сезона без привязки к сегменту).
// parentKind уточняет, из какого уровня создаётся миссия (для springboard).
type CreateContext = {
  type: SelectedType
  parentId: string
  parentKind?: 'season' | 'chapter' | 'segment'
} | null

const SELECTED_STORAGE_KEY = 'admin_tree_selected'
const EXPANDED_STORAGE_KEY = 'admin_tree_expanded'

const SELECTED_TYPES: readonly SelectedType[] = [
  'season',
  'chapter',
  'storyNode',
  'segment',
  'mission',
]

function isSelectedType(value: unknown): value is SelectedType {
  return (
    typeof value === 'string' &&
    (SELECTED_TYPES as readonly string[]).includes(value)
  )
}

// Задел под черновики форм: универсальная утилита сохранения/загрузки по ключу.
function saveDraft<T>(key: string, value: T) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // localStorage недоступен (приватный режим/SSR) — черновик просто не сохранится.
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

// Шаг 1 конструĸтора «Структура игры»: дерево иерархии (только просмотр).
//   Сезон → Глава → (Story Node | Сегмент → Миссия)
// Загружает пять списков параллельно (Promise.all). Редактирование — следующие шаги.
// Пропсы прокидываются из AdminApp (там же лежат общие списки и сессия админа).
type AdminTreeProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  keyItems: KeyItem[]
  loadingKeyItems: boolean
  geoZones: AdminGeoZone[]
  arObjects: AdminARObject[]
  minigameProfiles: AdminMinigameProfile[]
}

export function AdminTree({
  admin,
  canWrite,
  onError,
  onNotice,
  keyItems,
  loadingKeyItems,
  geoZones,
  arObjects,
  minigameProfiles,
}: AdminTreeProps) {
  const [seasons, setSeasons] = useState<AdminSeason[]>([])
  const [chapters, setChapters] = useState<AdminChapter[]>([])
  const [storyNodes, setStoryNodes] = useState<AdminStoryNode[]>([])
  const [segments, setSegments] = useState<AdminSegment[]>([])
  const [missions, setMissions] = useState<AdminMission[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Развёрнутые узлы. Префикс типа — чтобы id разных таблиц не пересекались.
  // Инициализация из localStorage — задел под черновики: после перезагрузки
  // страницы дерево и выбор открываются на том же месте.
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const saved = loadDraft<unknown>(EXPANDED_STORAGE_KEY)
    if (Array.isArray(saved)) {
      return new Set(
        saved.filter((key): key is string => typeof key === 'string'),
      )
    }
    return new Set()
  })
  const [selectedItem, setSelectedItem] = useState<SelectedItem | null>(() => {
    const saved = loadDraft<SelectedItem | null>(SELECTED_STORAGE_KEY)
    if (
      saved !== null &&
      isSelectedType(saved.type) &&
      typeof saved.id === 'string' &&
      saved.id.length > 0
    ) {
      return { type: saved.type, id: saved.id }
    }
    return null
  })
  // Режим создания сущности (кнопки «+» в узлах дерева). Когда задан,
  // правая панель рендерит секцию создания вместо формы выбранного элемента.
  const [createContext, setCreateContext] = useState<CreateContext>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      listSeasons(),
      listChapters(),
      listStoryNodes(),
      listSegments(),
      listAdminMissions(),
    ])
      .then(([seasonsData, chaptersData, nodesData, segmentsData, missionsData]) => {
        if (cancelled) return
        setSeasons(seasonsData)
        setChapters(chaptersData)
        setStoryNodes(nodesData)
        setSegments(segmentsData)
        setMissions(missionsData)
      })
      .catch((err: Error) => {
        if (cancelled) return
        setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Сохранение развёрнутых узлов при каждом изменении (задел под черновики).
  useEffect(() => {
    saveDraft(EXPANDED_STORAGE_KEY, Array.from(expanded))
  }, [expanded])

  function selectItem(type: SelectedType, id: string) {
    const next: SelectedItem = { type, id }
    // Клик по узлу закрывает режим создания: панель снова показывает форму
    // выбранного элемента.
    setCreateContext(null)
    setSelectedItem(next)
    saveDraft(SELECTED_STORAGE_KEY, next)
  }

  // Переход в режим создания сущности внутри выбранного родителя.
  function startCreate(
    type: SelectedType,
    parentId: string,
    parentKind?: 'season' | 'chapter' | 'segment',
  ) {
    setCreateContext({ type, parentId, parentKind })
  }

  // Обязательная очистка черновика формы миссии после успешного
  // сохранения/публикации (страховка поверх внутренней очистки компонента).
  function handleMissionDraftClear(id: string) {
    removeDraft(`draft_mission_${id}`)
  }

  const toggle = (key: string) => {
    const next = new Set(expanded)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
    }
    setExpanded(next)
  }

  const bySort = <T extends { sortOrder: number; title: string }>(
    items: T[],
  ): T[] =>
    [...items].sort((a, b) =>
      a.sortOrder !== b.sortOrder
        ? a.sortOrder - b.sortOrder
        : a.title.localeCompare(b.title),
    )

  const chaptersOf = (season: AdminSeason) =>
    bySort(chapters).filter((chapter) => chapter.seasonId === season.id)
  const nodesOf = (chapter: AdminChapter) =>
    bySort(storyNodes).filter((node) => node.chapterId === chapter.id)
  const segmentsOf = (chapter: AdminChapter) =>
    bySort(segments).filter((segment) => segment.chapterId === chapter.id)
  const missionsById = new Map<string, AdminMission>()
  for (const mission of missions) missionsById.set(mission.id, mission)
  const linkedMissionsOf = (segment: AdminSegment): AdminMission[] =>
    [...segment.linkedMissions]
      .sort((a, b) =>
        a.sortOrder !== b.sortOrder
          ? a.sortOrder - b.sortOrder
          : a.missionId.localeCompare(b.missionId),
      )
      .map((link) => missionsById.get(link.missionId))
      .filter((mission): mission is AdminMission => mission !== undefined)

  const selectedEntity = useMemo(() => {
    if (selectedItem === null) return null
    switch (selectedItem.type) {
      case 'season':
        return seasons.find((s) => s.id === selectedItem.id) ?? null
      case 'chapter':
        return chapters.find((c) => c.id === selectedItem.id) ?? null
      case 'storyNode':
        return storyNodes.find((n) => n.id === selectedItem.id) ?? null
      case 'segment':
        return segments.find((s) => s.id === selectedItem.id) ?? null
      case 'mission':
        return missions.find((m) => m.id === selectedItem.id) ?? null
      default:
        return null
    }
  }, [selectedItem, seasons, chapters, storyNodes, segments, missions])

  const selectedTypeLabel: Record<SelectedType, string> = {
    season: 'Сезон',
    chapter: 'Глава',
    storyNode: 'Story Node',
    segment: 'Сегмент',
    mission: 'Миссия',
  }

  // Правая панель. Режим создания (кнопки «+» в узлах дерева) имеет
  // приоритет: показываем форму создания с предзаполненной привязкой
  // к родителю, а поверх — кнопку «Отмена».
  function renderCreatePanel() {
    if (createContext === null) return null
    const cancelButton = (
      <button
        type="button"
        className="admin-secondary"
        style={{ marginBottom: '0.75rem' }}
        onClick={() => setCreateContext(null)}
      >
        ← Отмена
      </button>
    )

    if (createContext.type === 'chapter') {
      return (
        <div>
          {cancelButton}
          <ChaptersSection
            admin={admin}
            canWrite={canWrite}
            onError={onError}
            onNotice={onNotice}
            editingId={null}
            initialSeasonId={createContext.parentId}
          />
        </div>
      )
    }
    if (createContext.type === 'segment') {
      return (
        <div>
          {cancelButton}
          <SegmentsEditor
            admin={admin}
            canWrite={canWrite}
            onError={onError}
            onNotice={onNotice}
            editingId={null}
            initialChapterId={createContext.parentId}
          />
        </div>
      )
    }
    if (createContext.type === 'storyNode') {
      return (
        <div>
          {cancelButton}
          <StoryNodesSection
            admin={admin}
            canWrite={canWrite}
            onError={onError}
            onNotice={onNotice}
            editingId={null}
            initialChapterId={createContext.parentId}
          />
        </div>
      )
    }
    if (createContext.type === 'mission') {
      // Миссия может создаваться на трёх уровнях дерева:
      // - из сегмента (сюжетная): предзаполняем chapterId главы сегмента;
      // - из главы (командная/индивидуальная): предзаполняем chapterId главы;
      // - из сезона: предзаполняем seasonId, глава остаётся пустой — её
      //   выбирает администратор в форме (model требует chapter_id).
      if (createContext.parentKind === 'chapter') {
        return (
          <div>
            {cancelButton}
            <MissionsSection
              admin={admin}
              canWrite={canWrite}
              onError={onError}
              onNotice={onNotice}
              keyItems={keyItems}
              loadingKeyItems={loadingKeyItems}
              geoZones={geoZones}
              arObjects={arObjects}
              minigameProfiles={minigameProfiles}
              editingId={null}
              initialChapterId={createContext.parentId}
              onDraftClear={handleMissionDraftClear}
            />
          </div>
        )
      }
      if (createContext.parentKind === 'season') {
        return (
          <div>
            {cancelButton}
            <MissionsSection
              admin={admin}
              canWrite={canWrite}
              onError={onError}
              onNotice={onNotice}
              keyItems={keyItems}
              loadingKeyItems={loadingKeyItems}
              geoZones={geoZones}
              arObjects={arObjects}
              minigameProfiles={minigameProfiles}
              editingId={null}
              initialSeasonId={createContext.parentId}
              onDraftClear={handleMissionDraftClear}
            />
          </div>
        )
      }
      // default: создание из сегмента (сюжетная миссия).
      const segment = segments.find((s) => s.id === createContext.parentId) ?? null
      return (
        <div>
          {cancelButton}
          <MissionsSection
            admin={admin}
            canWrite={canWrite}
            onError={onError}
            onNotice={onNotice}
            keyItems={keyItems}
            loadingKeyItems={loadingKeyItems}
            geoZones={geoZones}
            arObjects={arObjects}
            minigameProfiles={minigameProfiles}
            editingId={null}
            initialChapterId={segment?.chapterId ?? null}
            onDraftClear={handleMissionDraftClear}
          />
        </div>
      )
    }
    // season: корневой уровень, просто открываем секцию сезонов.
    return (
      <div>
        {cancelButton}
        <SeasonsSection
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          editingId={null}
        />
      </div>
    )
  }

  // Правая панель. Существующие секции (SeasonsSection, ChaptersSection и т.д.)
  // пока не умеют принимать editingId/selectedId пропсом, поэтому здесь
  // заглушка-карточка. Настоящие формы подключим следующим шагом.
  function renderDetailPanel() {
    if (createContext !== null) {
      return renderCreatePanel()
    }
    if (selectedItem === null) {
      return (
        <div>
          <h3>Панель элемента</h3>
          <p className="admin-muted">
            Выберите элемент слева, чтобы открыть панель редактирования.
          </p>
        </div>
      )
    }
    // Миссия: полноценная форма редактирования.
    if (selectedItem.type === 'mission') {
      return (
        <MissionsSection
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          keyItems={keyItems}
          loadingKeyItems={loadingKeyItems}
          geoZones={geoZones}
          arObjects={arObjects}
          minigameProfiles={minigameProfiles}
          editingId={selectedItem.id}
          onDraftClear={handleMissionDraftClear}
        />
      )
    }
    // Глава: полноценная форма редактирования.
    if (selectedItem.type === 'chapter') {
      return (
        <ChaptersSection
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          editingId={selectedItem.id}
        />
      )
    }
    // Сезон: полноценная форма редактирования.
    if (selectedItem.type === 'season') {
      return (
        <SeasonsSection
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          editingId={selectedItem.id}
        />
      )
    }
    // Story Node: полноценная форма редактирования.
    if (selectedItem.type === 'storyNode') {
      return (
        <StoryNodesSection
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          editingId={selectedItem.id}
        />
      )
    }
    // Сегмент: полноценная форма редактирования.
    if (selectedItem.type === 'segment') {
      return (
        <SegmentsEditor
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          editingId={selectedItem.id}
        />
      )
    }
    // Недостижимый fallback: все типы дерева имеют свою форму выше.
    return (
      <div>
        <h3>{selectedTypeLabel[selectedItem.type]}</h3>
        <div className="admin-mission-row">
          {selectedEntity?.status && (
            <span
              className={`admin-status admin-status-${selectedEntity.status}`}
            >
              {selectedEntity.status}
            </span>
          )}
          <strong>{selectedEntity?.title ?? selectedItem.id}</strong>
          <small>{selectedItem.id}</small>
        </div>
        <p className="admin-muted">
          Редактирование (форма будет здесь). Черновик:{' '}
          <code>{`draft_${selectedItem.type}_${selectedItem.id}`}</code>
        </p>
      </div>
    )
  }

  return (
    <div className="admin-layout">
      <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
        <div style={{ flex: '0 0 320px', minWidth: 0, overflow: 'auto' }}>
          {error && <p className="admin-alert admin-error">{error}</p>}
          {loading && seasons.length === 0 && (
            <p className="admin-muted">Загрузка структуры…</p>
          )}
          {!loading && seasons.length === 0 && !error && (
            <p className="admin-muted">Сезонов пока нет.</p>
          )}

        <ul className="admin-mission-list">
          {canWrite && (
            <li>
              <button
                type="button"
                className="admin-primary"
                style={{ width: '100%' }}
                onClick={() => startCreate('season', '')}
              >
                + Создать сезон
              </button>
            </li>
          )}
          {bySort(seasons).map((season) => {
            const seasonKey = `season:${season.id}`
            const seasonOpen = expanded.has(seasonKey)
            const seasonChapters = chaptersOf(season)
            return (
              <li key={seasonKey}>
                <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'flex-start' }}>
                  <button
                    className={`admin-mission-row ${
                      selectedItem?.type === 'season' &&
                      selectedItem.id === season.id
                        ? 'is-active'
                        : ''
                    }`}
                    style={{ flex: 1, minWidth: 0 }}
                    onClick={() => {
                      selectItem('season', season.id)
                      toggle(seasonKey)
                    }}
                  >
                    <span className={`admin-status admin-status-${season.status}`}>
                      {season.status}
                    </span>
                    <strong>{seasonOpen ? '▾ ' : '▸ '}{season.title}</strong>
                    <small>{season.slug} · sortOrder {season.sortOrder}</small>
                  </button>
                  {canWrite && (
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.25rem',
                        flexShrink: 0,
                      }}
                    >
                      <button
                        type="button"
                        className="admin-secondary"
                        title="Создать главу в сезоне"
                        onClick={() => startCreate('chapter', season.id)}
                      >
                        + Глава
                      </button>
                      <button
                        type="button"
                        className="admin-secondary"
                        title="Создать миссию на уровне сезона (без сегмента, главу выбрать в форме)"
                        onClick={() =>
                          startCreate('mission', season.id, 'season')
                        }
                      >
                        + Миссия
                      </button>
                    </div>
                  )}
                </div>

                {seasonOpen && (
                  <ul className="admin-mission-list">
                    {seasonChapters.length === 0 && (
                      <li>
                        <p className="admin-muted">В сезоне нет глав.</p>
                      </li>
                    )}
                    {seasonChapters.map((chapter) => {
                      const chapterKey = `chapter:${chapter.id}`
                      const chapterOpen = expanded.has(chapterKey)
                      const chapterNodes = nodesOf(chapter)
                      const chapterSegments = segmentsOf(chapter)
                      return (
                        <li key={chapterKey}>
                          <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'flex-start' }}>
                          <button
                            className={`admin-mission-row ${
                              selectedItem?.type === 'chapter' &&
                              selectedItem.id === chapter.id
                                ? 'is-active'
                                : ''
                            }`}
                            style={{ flex: 1, minWidth: 0 }}
                            onClick={() => {
                              selectItem('chapter', chapter.id)
                              toggle(chapterKey)
                            }}
                          >
                            <span
                              className={`admin-status admin-status-${chapter.status}`}
                            >
                              {chapter.status}
                            </span>
                            <strong>
                              {chapterOpen ? '▾ ' : '▸ '}
                              {chapter.title}
                            </strong>
                            <small>
                              {chapter.slug} · sortOrder {chapter.sortOrder}
                            </small>
                          </button>
                          {canWrite && (
                            <div
                              style={{
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '0.25rem',
                                flexShrink: 0,
                              }}
                            >
                              <button
                                type="button"
                                className="admin-secondary"
                                title="Создать сегмент в главе"
                                onClick={() =>
                                  startCreate('segment', chapter.id)
                                }
                              >
                                + Сегм
                              </button>
                              <button
                                type="button"
                                className="admin-secondary"
                                title="Создать Story Node в главе"
                                onClick={() =>
                                  startCreate('storyNode', chapter.id)
                                }
                              >
                                + Узел
                              </button>
                              <button
                                type="button"
                                className="admin-secondary"
                                title="Создать миссию на уровне главы (без сегмента)"
                                onClick={() =>
                                  startCreate('mission', chapter.id, 'chapter')
                                }
                              >
                                + Миссия
                              </button>
                            </div>
                          )}
                          </div>

                          {chapterOpen && (
                            <ul className="admin-mission-list">
                              <li>
                                <p className="admin-muted">Story Nodes</p>
                              </li>
                              {chapterNodes.length === 0 && (
                                <li>
                                  <p className="admin-muted">
                                    Story Nodes в главе нет.
                                  </p>
                                </li>
                              )}
                              {chapterNodes.map((node) => (
                                <li key={`node:${node.id}`}>
                                  <div
                                    className={`admin-mission-row ${
                                      selectedItem?.type === 'storyNode' &&
                                      selectedItem.id === node.id
                                        ? 'is-active'
                                        : ''
                                    }`}
                                    style={{ cursor: 'pointer' }}
                                    onClick={() =>
                                      selectItem('storyNode', node.id)
                                    }
                                  >
                                    <span
                                      className={`admin-status admin-status-${node.status}`}
                                    >
                                      {node.status}
                                    </span>
                                    <strong>{node.title}</strong>
                                    <small>
                                      {node.slug} · Story Node · sortOrder{' '}
                                      {node.sortOrder}
                                    </small>
                                  </div>
                                </li>
                              ))}

                              <li>
                                <p className="admin-muted">Сегменты</p>
                              </li>
                              {chapterSegments.length === 0 && (
                                <li>
                                  <p className="admin-muted">
                                    Сегментов в главе нет.
                                  </p>
                                </li>
                              )}
                              {chapterSegments.map((segment) => {
                                const segmentKey = `segment:${segment.id}`
                                const segmentOpen = expanded.has(segmentKey)
                                const segmentMissions = linkedMissionsOf(segment)
                                return (
                                  <li key={segmentKey}>
                                    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'flex-start' }}>
                                    <button
                                      className={`admin-mission-row ${
                                        selectedItem?.type === 'segment' &&
                                        selectedItem.id === segment.id
                                          ? 'is-active'
                                          : ''
                                      }`}
                                      style={{ flex: 1, minWidth: 0 }}
                                      onClick={() => {
                                        selectItem('segment', segment.id)
                                        toggle(segmentKey)
                                      }}
                                    >
                                      <span
                                        className={`admin-status admin-status-${segment.status}`}
                                      >
                                        {segment.status}
                                      </span>
                                      <strong>
                                        {segmentOpen ? '▾ ' : '▸ '}
                                        {segment.title}
                                      </strong>
                                      <small>
                                        {segment.slug} · sortOrder{' '}
                                        {segment.sortOrder}
                                      </small>
                                    </button>
                                    {canWrite && (
                                      <button
                                        type="button"
                                        className="admin-secondary"
                                        style={{ flexShrink: 0 }}
                                        title="Создать миссию в сегменте"
                                        onClick={() =>
                                          startCreate('mission', segment.id)
                                        }
                                      >
                                        + Миссия
                                      </button>
                                    )}
                                    </div>

                                    {segmentOpen && (
                                      <ul className="admin-mission-list">
                                        {segmentMissions.length === 0 && (
                                          <li>
                                            <p className="admin-muted">
                                              В сегменте нет миссий.
                                            </p>
                                          </li>
                                        )}
                                        {segmentMissions.map((mission) => (
                                          <li key={`mission:${mission.id}`}>
                                            <div
                                              className={`admin-mission-row ${
                                                selectedItem?.type === 'mission' &&
                                                selectedItem.id === mission.id
                                                  ? 'is-active'
                                                  : ''
                                              }`}
                                              style={{ cursor: 'pointer' }}
                                              onClick={() =>
                                                selectItem(
                                                  'mission',
                                                  mission.id,
                                                )
                                              }
                                            >
                                              <span
                                                className={`admin-status admin-status-${mission.status}`}
                                              >
                                                {mission.status}
                                              </span>
                                              <strong>{mission.title}</strong>
                                              <small>
                                                {mission.slug} ·{' '}
                                                {mission.missionType}
                                              </small>
                                            </div>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                  </li>
                                )
                              })}
                            </ul>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {renderDetailPanel()}
        </div>
      </div>
    </div>
  )
}