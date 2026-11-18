import { useEffect, useRef, useState } from 'react'
import {
  createGeoZone,
  listGeoZones,
  updateGeoZone,
  type AdminGeoZone,
  type AdminUser,
} from '../../api/adminApi'

// --- Черновик формы геозоны -------------------------------------------------
// Хранится в localStorage по ключу `draft_geozone_<id|'new'>`. Компонент
// сохраняет изменённую форму, восстанавливает её при повторном открытии и
// удаляет после успешного создания/сохранения (аналог MissionsSection).
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

function clearDraft(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {
    // localStorage недоступен — чистить нечего.
  }
}

/** Снимок полей формы геозоны (единый порядок ключей для стабильного JSON). */
function geoZoneSnapshot(v: {
  slug: string
  title: string
  description: string
  sortOrder: string
  radiusMeters: string
  searchRadiusMeters: string
  maxAccuracy: string
  minPresence: string
  status: string
  avoidBuildings: boolean
  avoidWater: boolean
  avoidRoads: boolean
  avoidPrivate: boolean
}) {
  return {
    slug: v.slug,
    title: v.title,
    description: v.description,
    sortOrder: v.sortOrder,
    radiusMeters: v.radiusMeters,
    searchRadiusMeters: v.searchRadiusMeters,
    maxAccuracy: v.maxAccuracy,
    minPresence: v.minPresence,
    status: v.status,
    avoidBuildings: v.avoidBuildings,
    avoidWater: v.avoidWater,
    avoidRoads: v.avoidRoads,
    avoidPrivate: v.avoidPrivate,
  }
}

type GeoZonesEditorProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  // Общий список геозон: загружается в AdminApp и используется в миссиях.
  geoZones: AdminGeoZone[]
  // Обновляет общий список geoZones в AdminApp (после create/update/refresh).
  onGeoZonesChange: (updater: (prev: AdminGeoZone[]) => AdminGeoZone[]) => void
}

export function GeoZonesEditor({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
  geoZones,
  onGeoZonesChange,
}: GeoZonesEditorProps) {
  const [selectedGeoZoneId, setSelectedGeoZoneId] = useState<string | null>(null)
  const [geoZoneSlug, setGeoZoneSlug] = useState('')
  const [geoZoneTitle, setGeoZoneTitle] = useState('')
  const [geoZoneDescription, setGeoZoneDescription] = useState('')
  const [geoZoneSortOrder, setGeoZoneSortOrder] = useState('0')
  const [geoZoneRadiusMeters, setGeoZoneRadiusMeters] = useState('')
  const [geoZoneSearchRadiusMeters, setGeoZoneSearchRadiusMeters] = useState('')
  const [geoZoneMaxAccuracy, setGeoZoneMaxAccuracy] = useState('')
  const [geoZoneMinPresence, setGeoZoneMinPresence] = useState('0')
  const [geoZoneStatus, setGeoZoneStatus] = useState('draft')
  const [geoZoneAvoidBuildings, setGeoZoneAvoidBuildings] = useState(true)
  const [geoZoneAvoidWater, setGeoZoneAvoidWater] = useState(true)
  const [geoZoneAvoidRoads, setGeoZoneAvoidRoads] = useState(true)
  const [geoZoneAvoidPrivate, setGeoZoneAvoidPrivate] = useState(true)
  const [savingGeoZone, setSavingGeoZone] = useState(false)
  const [geoZoneError, setGeoZoneError] = useState<string | null>(null)
  const [geoZoneNotice, setGeoZoneNotice] = useState<string | null>(null)
  const [showCreateGeoZone, setShowCreateGeoZone] = useState(false)
  // Локальные состояния списка («Обновить список»; сама загрузка — в AdminApp).
  const [refreshing, setRefreshing] = useState(false)
  const [listError, setListError] = useState<string | null>(null)

  // Черновик: последний сохранённый/загруженный снимок формы (JSON). Нужен,
  // чтобы программное заполнение из БД не создавало и не перезаписывало
  // черновик — сохраняем только реальные правки пользователя.
  const lastSavedDraftRef = useRef('')
  const skipNextDraftSaveRef = useRef(false)
  const draftKey = `draft_geozone_${selectedGeoZoneId ?? 'new'}`
  // Форма «активна», когда открыта геозона на редактирование или создание.
  // В пустом редакторе черновик не трогаем.
  const formActive = selectedGeoZoneId !== null || showCreateGeoZone

  // Заполнение формы при выборе геозоны (перенесено из AdminApp дословно).
  useEffect(() => {
    const z = selectedGeoZone()
    if (!z) {
      setGeoZoneError(null)
      setGeoZoneNotice(null)
      return
    }
    setGeoZoneSlug(z.slug)
    setGeoZoneTitle(z.title)
    setGeoZoneDescription(z.description ?? '')
    setGeoZoneSortOrder(String(z.sortOrder))
    setGeoZoneRadiusMeters(z.radiusMeters === null ? '' : String(z.radiusMeters))
    setGeoZoneSearchRadiusMeters(z.searchRadiusMeters === null ? '' : String(z.searchRadiusMeters))
    setGeoZoneMaxAccuracy(z.maxLocationAccuracyMeters === null ? '' : String(z.maxLocationAccuracyMeters))
    setGeoZoneMinPresence(String(z.minimumPresenceSeconds))
    setGeoZoneStatus(z.status)
    const lc = z.locationConstraints ?? {}
    setGeoZoneAvoidBuildings(lc.avoid_buildings ?? false)
    setGeoZoneAvoidWater(lc.avoid_water ?? false)
    setGeoZoneAvoidRoads(lc.avoid_roads ?? false)
    setGeoZoneAvoidPrivate(lc.avoid_private ?? false)
    // Заполнение из БД помечаем как «уже сохранённое» — черновик не пишем.
    lastSavedDraftRef.current = JSON.stringify(
      geoZoneSnapshot({
        slug: z.slug,
        title: z.title,
        description: z.description ?? '',
        sortOrder: String(z.sortOrder),
        radiusMeters: z.radiusMeters === null ? '' : String(z.radiusMeters),
        searchRadiusMeters:
          z.searchRadiusMeters === null ? '' : String(z.searchRadiusMeters),
        maxAccuracy:
          z.maxLocationAccuracyMeters === null
            ? ''
            : String(z.maxLocationAccuracyMeters),
        minPresence: String(z.minimumPresenceSeconds),
        status: z.status,
        avoidBuildings: lc.avoid_buildings ?? false,
        avoidWater: lc.avoid_water ?? false,
        avoidRoads: lc.avoid_roads ?? false,
        avoidPrivate: lc.avoid_private ?? false,
      }),
    )
    setGeoZoneError(null)
    setGeoZoneNotice(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedGeoZoneId, geoZones])

  // Сброс create-режима при смене выбранной геозоны.
  useEffect(() => {
    setShowCreateGeoZone(false)
    setGeoZoneError(null)
  }, [selectedGeoZoneId])

  // Восстановление черновика при открытии геозоны/создании. Ставим флаг
  // до эффекта автосохранения ниже, чтобы заполнение из БД не перезаписало draft.
  useEffect(() => {
    if (!formActive) return
    skipNextDraftSaveRef.current = true
    const restored = loadDraft<ReturnType<typeof geoZoneSnapshot>>(draftKey)
    if (restored === null) return
    setGeoZoneSlug(restored.slug)
    setGeoZoneTitle(restored.title)
    setGeoZoneDescription(restored.description)
    setGeoZoneSortOrder(restored.sortOrder)
    setGeoZoneRadiusMeters(restored.radiusMeters)
    setGeoZoneSearchRadiusMeters(restored.searchRadiusMeters)
    setGeoZoneMaxAccuracy(restored.maxAccuracy)
    setGeoZoneMinPresence(restored.minPresence)
    setGeoZoneStatus(restored.status)
    setGeoZoneAvoidBuildings(restored.avoidBuildings)
    setGeoZoneAvoidWater(restored.avoidWater)
    setGeoZoneAvoidRoads(restored.avoidRoads)
    setGeoZoneAvoidPrivate(restored.avoidPrivate)
    lastSavedDraftRef.current = JSON.stringify(restored)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey, formActive])

  // Автосохранение черновика при реальных правках формы.
  useEffect(() => {
    if (skipNextDraftSaveRef.current) {
      skipNextDraftSaveRef.current = false
      return
    }
    if (!formActive) return
    const snapshot = geoZoneSnapshot({
      slug: geoZoneSlug,
      title: geoZoneTitle,
      description: geoZoneDescription,
      sortOrder: geoZoneSortOrder,
      radiusMeters: geoZoneRadiusMeters,
      searchRadiusMeters: geoZoneSearchRadiusMeters,
      maxAccuracy: geoZoneMaxAccuracy,
      minPresence: geoZoneMinPresence,
      status: geoZoneStatus,
      avoidBuildings: geoZoneAvoidBuildings,
      avoidWater: geoZoneAvoidWater,
      avoidRoads: geoZoneAvoidRoads,
      avoidPrivate: geoZoneAvoidPrivate,
    })
    const serialized = JSON.stringify(snapshot)
    if (serialized === lastSavedDraftRef.current) return
    lastSavedDraftRef.current = serialized
    saveDraft(draftKey, snapshot)
  }, [
    formActive,
    draftKey,
    geoZoneSlug,
    geoZoneTitle,
    geoZoneDescription,
    geoZoneSortOrder,
    geoZoneRadiusMeters,
    geoZoneSearchRadiusMeters,
    geoZoneMaxAccuracy,
    geoZoneMinPresence,
    geoZoneStatus,
    geoZoneAvoidBuildings,
    geoZoneAvoidWater,
    geoZoneAvoidRoads,
    geoZoneAvoidPrivate,
  ])

  function selectedGeoZone(): AdminGeoZone | null {
    if (selectedGeoZoneId === null) return null
    return geoZones.find((z) => z.id === selectedGeoZoneId) ?? null
  }

  function buildGeoZonePayloadCommon() {
    const slug = geoZoneSlug.trim() || undefined
    const title = geoZoneTitle.trim()
    if (title.length < 1) throw new Error('Название обязательно.')

    const sortOrder = Number.parseInt(geoZoneSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) {
      throw new Error('Порядок сортировки — целое ≥ 0.')
    }

    const radius = Number.parseInt(geoZoneRadiusMeters, 10)
    if (!Number.isFinite(radius) || radius <= 0) {
      throw new Error('Размер зоны (radius) — целое > 0.')
    }

    const searchRadius = Number.parseInt(geoZoneSearchRadiusMeters, 10)
    if (!Number.isFinite(searchRadius) || searchRadius <= 0) {
      throw new Error('Радиус поиска — целое > 0.')
    }

    const minPresence = Number.parseInt(geoZoneMinPresence, 10)
    if (!Number.isFinite(minPresence) || minPresence < 0) {
      throw new Error('Минимальное время присутствия — целое ≥ 0.')
    }

    const maxAccRaw = geoZoneMaxAccuracy.trim()
    const maxAcc = maxAccRaw === '' ? null : Number.parseInt(maxAccRaw, 10)
    if (maxAcc !== null && (!Number.isFinite(maxAcc) || maxAcc < 0)) {
      throw new Error('Точность GPS — целое ≥ 0 или пусто.')
    }

    const locationConstraints: Record<string, boolean> = {}
    if (geoZoneAvoidBuildings) locationConstraints.avoid_buildings = true
    if (geoZoneAvoidWater) locationConstraints.avoid_water = true
    if (geoZoneAvoidRoads) locationConstraints.avoid_roads = true
    if (geoZoneAvoidPrivate) locationConstraints.avoid_private = true

    return { slug, title, sortOrder, radius, searchRadius, minPresence, maxAcc, locationConstraints }
  }

  async function handleCreateGeoZone() {
    setSavingGeoZone(true); setGeoZoneError(null); setGeoZoneNotice(null)
    try {
      const p = buildGeoZonePayloadCommon()
      const created = await createGeoZone({
        slug: p.slug || undefined,
        title: p.title,
        description: geoZoneDescription.trim() || null,
        zone_type: 'radius',
        sort_order: p.sortOrder,
        radius_meters: p.radius,
        search_radius_meters: p.searchRadius,
        minimum_presence_seconds: p.minPresence,
        max_location_accuracy_meters: p.maxAcc,
        location_constraints: p.locationConstraints,
      })
      onGeoZonesChange((prev) => [...prev, created])
      // Черновик «новой» геозоны больше не нужен.
      clearDraft('draft_geozone_new')
      setSelectedGeoZoneId(created.id)
      setShowCreateGeoZone(false)
      setGeoZoneNotice('Шаблон создан.')
    } catch (err) { setGeoZoneError((err as Error).message) }
    finally { setSavingGeoZone(false) }
  }

  async function handleSaveGeoZone() {
    const z = selectedGeoZone()
    if (!z) return
    setSavingGeoZone(true); setGeoZoneError(null); setGeoZoneNotice(null)
    try {
      const p = buildGeoZonePayloadCommon()
      const updated = await updateGeoZone(z.id, {
        slug: p.slug || undefined,
        title: p.title,
        description: geoZoneDescription.trim() || null,
        zone_type: 'radius',
        status: geoZoneStatus,
        sort_order: p.sortOrder,
        radius_meters: p.radius,
        search_radius_meters: p.searchRadius,
        minimum_presence_seconds: p.minPresence,
        max_location_accuracy_meters: p.maxAcc,
        location_constraints: p.locationConstraints,
      })
      onGeoZonesChange((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
      // Черновик сохранённой геозоны очищаем — данные уже в базе.
      clearDraft(`draft_geozone_${z.id}`)
      setGeoZoneNotice('Сохранено.')
    } catch (err) { setGeoZoneError((err as Error).message) }
    finally { setSavingGeoZone(false) }
  }

  function handleShowCreateGeoZone() {
    setShowCreateGeoZone(true)
    setGeoZoneSlug('')
    setGeoZoneTitle('')
    setGeoZoneDescription('')
    setGeoZoneSortOrder('0')
    setGeoZoneRadiusMeters('')
    setGeoZoneSearchRadiusMeters('')
    setGeoZoneMaxAccuracy('')
    setGeoZoneMinPresence('0')
    setGeoZoneStatus('draft')
    setGeoZoneAvoidBuildings(true)
    setGeoZoneAvoidWater(true)
    setGeoZoneAvoidRoads(true)
    setGeoZoneAvoidPrivate(true)
    setGeoZoneError(null)
    setGeoZoneNotice(null)
    setSelectedGeoZoneId(null)
  }

  function handleRefreshList() {
    setRefreshing(true)
    setListError(null)
    listGeoZones()
      .then((data) => onGeoZonesChange(() => data))
      .catch((err: Error) => setListError(err.message))
      .finally(() => setRefreshing(false))
  }

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <>
          <button
            className="admin-primary"
            onClick={handleShowCreateGeoZone}
            disabled={!canWrite}
          >
            + Новая геозона
          </button>
          <button
            className="admin-secondary"
            onClick={handleRefreshList}
          >
            ↻ Обновить список
          </button>

          {listError && (
            <p className="admin-alert admin-error">{listError}</p>
          )}

          <div className="admin-mission-list">
            {geoZones.map((zone) => (
              <button
                key={zone.id}
                className={selectedGeoZoneId === zone.id ? 'is-active' : ''}
                onClick={() => setSelectedGeoZoneId(zone.id)}
              >
                <strong>{zone.title}</strong>
                <small>{zone.slug} · {zone.zoneType}</small>
                <span className={`admin-status admin-status-${zone.status}`}>
                  {zone.status}
                </span>
              </button>
            ))}
            {!refreshing && geoZones.length === 0 && !listError && (
              <p className="admin-muted">Геозон нет.</p>
            )}
          </div>
        </>
      </aside>

      <section className="admin-editor">
        <>
          <div className="admin-editor-title">
            <div>
              <p className="admin-kicker">
                {showCreateGeoZone
                  ? 'НОВЫЙ ШАБЛОН'
                  : selectedGeoZone() ? selectedGeoZone()!.id : '—'}
              </p>
              <h3>
                {showCreateGeoZone
                  ? 'Создание шаблона зоны'
                  : selectedGeoZone() ? 'Редактирование шаблона' : 'Редактор шаблона зоны'}
              </h3>
            </div>
            {selectedGeoZone() && !showCreateGeoZone && (
              <span className={`admin-status admin-status-${selectedGeoZone()!.status}`}>
                {selectedGeoZone()!.status}
              </span>
            )}
          </div>

          {geoZoneError && <p className="admin-alert admin-error">{geoZoneError}</p>}
          {geoZoneNotice && <p className="admin-alert">{geoZoneNotice}</p>}

          {!showCreateGeoZone && selectedGeoZone() === null ? (
            <p className="admin-muted">
              Выберите шаблон слева или создайте новый.
              Координаты генерирует сервер в момент взятия миссии.
            </p>
          ) : (
            <>
              <p className="admin-muted">
                Координаты места генерирует сервер при взятии миссии игроком:
                в радиусе поиска от фактической точки игрока появляется зона
                заданного размера.
              </p>

              <div className="admin-grid">
                <label className="admin-span-2">
                  Название *
                  <input
                    value={geoZoneTitle}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneTitle(e.target.value)}
                  />
                </label>

                <label>
                  Slug
                  <input
                    value={geoZoneSlug}
                    disabled={!canWrite}
                    placeholder="сгенерируется автоматически"
                    onChange={(e) => setGeoZoneSlug(e.target.value)}
                  />
                </label>

                <label>
                  Порядок сортировки
                  <input
                    type="number"
                    value={geoZoneSortOrder}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneSortOrder(e.target.value)}
                  />
                </label>

                <label className="admin-span-2">
                  Описание
                  <textarea
                    value={geoZoneDescription}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneDescription(e.target.value)}
                  />
                </label>
              </div>
              <div className="admin-grid">
                <label>
                  Радиус поиска * (метры)
                  <input
                    type="number"
                    value={geoZoneSearchRadiusMeters}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneSearchRadiusMeters(e.target.value)}
                  />
                  <small className="admin-muted">
                    Игрок видит этот радиус как область на карте
                  </small>
                </label>

                <label>
                  Размер зоны * (метры)
                  <input
                    type="number"
                    value={geoZoneRadiusMeters}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneRadiusMeters(e.target.value)}
                  />
                  <small className="admin-muted">
                    Игрок не видит размер до момента поиска
                  </small>
                </label>

                <label>
                  Точность GPS (метры)
                  <input
                    type="number"
                    value={geoZoneMaxAccuracy}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneMaxAccuracy(e.target.value)}
                  />
                  <small className="admin-muted">
                    Пусто — без ограничений
                  </small>
                </label>

                <label>
                  Время присутствия (секунды)
                  <input
                    type="number"
                    value={geoZoneMinPresence}
                    disabled={!canWrite}
                    onChange={(e) => setGeoZoneMinPresence(e.target.value)}
                  />
                </label>
              </div>

              <div className="admin-grid">
                <fieldset className="admin-span-2">
                  <legend>Ограничения размещения</legend>
                  <small className="admin-muted">
                    Сервер учтёт при генерации места зоны (реализация — Спринт 8.2)
                  </small>
                  <label>
                    <input
                      type="checkbox"
                      checked={geoZoneAvoidBuildings}
                      disabled={!canWrite}
                      onChange={(e) => setGeoZoneAvoidBuildings(e.target.checked)}
                    />
                    Избегать зданий
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={geoZoneAvoidWater}
                      disabled={!canWrite}
                      onChange={(e) => setGeoZoneAvoidWater(e.target.checked)}
                    />
                    Избегать водоёмов
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={geoZoneAvoidRoads}
                      disabled={!canWrite}
                      onChange={(e) => setGeoZoneAvoidRoads(e.target.checked)}
                    />
                    Избегать дорог
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={geoZoneAvoidPrivate}
                      disabled={!canWrite}
                      onChange={(e) => setGeoZoneAvoidPrivate(e.target.checked)}
                    />
                    Избегать частных территорий
                  </label>
                </fieldset>
              </div>

              {!showCreateGeoZone && (
                <div className="admin-grid">
                  <label>
                    Статус
                    <select
                      value={geoZoneStatus}
                      disabled={!canWrite}
                      onChange={(e) => setGeoZoneStatus(e.target.value)}
                    >
                      <option value="draft">draft — черновик</option>
                      <option value="published">published — активен</option>
                      <option value="archived">archived — архив</option>
                    </select>
                  </label>
                </div>
              )}

              <div className="admin-actions">
                {showCreateGeoZone ? (
                  <>
                    <button
                      className="admin-primary"
                      onClick={handleCreateGeoZone}
                      disabled={!canWrite || savingGeoZone}
                    >
                      {savingGeoZone ? 'Создание…' : 'Создать'}
                    </button>
                    <button
                      className="admin-secondary"
                      onClick={() => setShowCreateGeoZone(false)}
                      disabled={savingGeoZone}
                    >
                      Отмена
                    </button>
                  </>
                ) : (
                  <button
                    className="admin-primary"
                    onClick={handleSaveGeoZone}
                    disabled={!canWrite || savingGeoZone}
                  >
                    {savingGeoZone ? 'Сохранение…' : 'Сохранить'}
                  </button>
                )}
              </div>
            </>
          )}
        </>
      </section>
    </div>
  )
}