import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent } from 'react'
import { MissionsSection } from './MissionsSection'
import { SeasonsSection } from './SeasonsSection'
import {
  listAdminMissions,
  listSeasons,
  type AdminARObject,
  type AdminGeoZone,
  type AdminMinigameProfile,
  type AdminMission,
  type AdminSeason,
  type AdminUser,
  type KeyItem,
} from '../../api/adminApi'

// Типы выбранного элемента и ключи localStorage для задела под черновики.
// Sprint Structure-Simplify: иерархия упрощена до Season → Mission.
type SelectedType = 'season' | 'mission'
type SelectedItem = { type: SelectedType; id: string }

// Контекст создания сущности из дерева структуры: тип + родительский узел.
// Миссия создаётся на уровне сезона (parentKind='season', parentId=season.id);
// сезон — корневой уровень (parentId='').
type CreateContext = {
  type: SelectedType
  parentId: string
  parentKind?: 'season'
} | null

const SELECTED_STORAGE_KEY = 'admin_tree_selected'
const EXPANDED_STORAGE_KEY = 'admin_tree_expanded'
const CREATE_CONTEXT_STORAGE_KEY = 'admin_tree_create_context'

const SELECTED_TYPES: readonly SelectedType[] = ['season', 'mission']

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

// Дерево «Структура игры»: Сезон → Миссия.
// Загружает два списка параллельно (Promise.all). Пропсы прокидываются из
// AdminApp (там же лежат общие списки и сессия админа).
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
  // Восстанавливается из localStorage, чтобы переключение вкладок и F5
  // не теряли режим создания (черновик новой миссии — в draft_mission_new).
  const [createContext, setCreateContext] = useState<CreateContext>(() => {
    const saved = loadDraft<unknown>(CREATE_CONTEXT_STORAGE_KEY)
    if (saved === null || typeof saved !== 'object') return null
    const candidate = saved as {
      type?: unknown
      parentId?: unknown
      parentKind?: unknown
    }
    if (
      !isSelectedType(candidate.type) ||
      typeof candidate.parentId !== 'string'
    ) {
      return null
    }
    if (candidate.type === 'mission' && candidate.parentId.length === 0) {
      return null
    }
    return {
      type: candidate.type,
      parentId: candidate.parentId,
      parentKind: candidate.parentKind === 'season' ? 'season' : undefined,
    }
  })

  // Sprint Admin-CSS-Fix-2: split-pane для дерева структуры. Ширина колонки
  // дерева в px, инициализация из localStorage, перетаскивание разделителя,
  // clamp 240..600 (значения вне диапазона при инициализации игнорируются).
  const [treeWidth, setTreeWidth] = useState<number>(() => {
    try {
      const stored = Number(localStorage.getItem('adminTreeWidth'))
      return Number.isFinite(stored) && stored >= 240 && stored <= 600
        ? stored
        : 320
    } catch {
      return 320
    }
  })
  const treeDragRef = useRef<{ startX: number; startWidth: number } | null>(
    null,
  )

  const handleTreeResizeStart = (event: ReactMouseEvent<HTMLDivElement>) => {
    event.preventDefault()
    treeDragRef.current = { startX: event.clientX, startWidth: treeWidth }
    let latest = treeWidth
    const onMove = (moveEvent: MouseEvent) => {
      if (treeDragRef.current === null) return
      const delta = moveEvent.clientX - treeDragRef.current.startX
      latest = Math.min(
        600,
        Math.max(240, treeDragRef.current.startWidth + delta),
      )
      setTreeWidth(latest)
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      treeDragRef.current = null
      try {
        localStorage.setItem('adminTreeWidth', String(latest))
      } catch {
        // localStorage недоступен — ширина не сохранится, но drag работает.
      }
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([listSeasons(), listAdminMissions()])
      .then(([seasonsData, missionsData]) => {
        if (cancelled) return
        setSeasons(seasonsData)
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

  // Сохранение режима создания: возврат на вкладку «Структура» или перезагрузка
  // страницы заново откроют панель создания (черновик формы — в MissionsSection).
  useEffect(() => {
    if (createContext === null) {
      removeDraft(CREATE_CONTEXT_STORAGE_KEY)
      return
    }
    saveDraft(CREATE_CONTEXT_STORAGE_KEY, createContext)
  }, [createContext])

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
    parentKind?: 'season',
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

  const missionsOf = (season: AdminSeason) =>
    bySort(missions).filter((mission) => mission.seasonId === season.id)

  const selectedEntity = useMemo(() => {
    if (selectedItem === null) return null
    switch (selectedItem.type) {
      case 'season':
        return seasons.find((s) => s.id === selectedItem.id) ?? null
      case 'mission':
        return missions.find((m) => m.id === selectedItem.id) ?? null
      default:
        return null
    }
  }, [selectedItem, seasons, missions])

  const selectedTypeLabel: Record<SelectedType, string> = {
    season: 'Сезон',
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

    if (createContext.type === 'mission') {
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

  // Правая панель редактирования выбранного элемента.
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
    // Недостижимый fallback.
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
      </div>
    )
  }
return (
    <div className="admin-layout">
      <div style={{ display: 'flex', gap: 0, alignItems: 'flex-start' }}>
        <div
          className="admin-tree"
          style={{
            width: treeWidth,
            flex: '0 0 auto',
            minWidth: 240,
            maxWidth: 600,
            overflow: 'auto',
          }}
        >
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
              const seasonMissions = missionsOf(season)
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
                      <strong><span className="admin-tree-caret">{seasonOpen ? '▾' : '▸'}</span>{season.title}</strong>
                      <small>{season.slug} · sortOrder {season.sortOrder}</small>
                    </button>
                    {canWrite && (
                      <button
                        type="button"
                        className="admin-secondary"
                        style={{ flexShrink: 0 }}
                        title="Создать миссию в сезоне"
                        onClick={() =>
                          startCreate('mission', season.id, 'season')
                        }
                      >
                        + Миссия
                      </button>
                    )}
                  </div>

                  {seasonOpen && (
                    <ul className="admin-mission-list">
                      {seasonMissions.length === 0 && (
                        <li>
                          <p className="admin-muted">В сезоне нет миссий.</p>
                        </li>
                      )}
                      {seasonMissions.map((mission) => (
                        <li key={`mission:${mission.id}`}>
                          <div
                            className={`admin-mission-row ${
                              selectedItem?.type === 'mission' &&
                              selectedItem.id === mission.id
                                ? 'is-active'
                                : ''
                            }`}
                            style={{ cursor: 'pointer' }}
                            onClick={() => selectItem('mission', mission.id)}
                          >
                            <span
                              className={`admin-status admin-status-${mission.status}`}
                            >
                              {mission.status}
                            </span>
                            <strong>{mission.title}</strong>
                            <small>
                              {mission.slug} · {mission.missionType}
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
        </div>
        <div
          className="admin-resize-handle"
          role="separator"
          aria-orientation="vertical"
          title="Перетащите, чтобы изменить ширину дерева"
          onMouseDown={handleTreeResizeStart}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          {renderDetailPanel()}
        </div>
      </div>
    </div>
  )
}
