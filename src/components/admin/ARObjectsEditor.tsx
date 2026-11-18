import { useEffect, useState } from 'react'
import {
  createARObject,
  listARObjects,
  updateARObject,
  type AdminARObject,
  type AdminGeoZone,
  type AdminUser,
} from '../../api/adminApi'

type ARObjectsEditorProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  // Общий список AR-объектов: загружается в AdminApp и используется в миссиях.
  arObjects: AdminARObject[]
  // Обновляет общий список arObjects в AdminApp (после create/update/refresh).
  onARObjectsChange: (arObjects: AdminARObject[]) => void
  // Геозоны для выбора в форме AR-объекта (общий список загружается в AdminApp).
  geoZones: AdminGeoZone[]
}

export function ARObjectsEditor({
  admin: _admin,
  canWrite,
  onError: _onError,
  onNotice: _onNotice,
  arObjects,
  onARObjectsChange,
  geoZones,
}: ARObjectsEditorProps) {
  const [loadingARObjects, setLoadingARObjects] = useState(false)
  const [arObjectsError, setARObjectsError] = useState<string | null>(null)
  const [selectedARObjectId, setSelectedARObjectId] = useState<string | null>(null)
  const [arObjectSlug, setARObjectSlug] = useState('')
  const [arObjectTitle, setARObjectTitle] = useState('')
  const [arObjectDescription, setARObjectDescription] = useState('')
  const [arObjectGeoZoneId, setARObjectGeoZoneId] = useState('')
  const [arObjectObjectType, setARObjectObjectType] = useState('cube')
  const [arObjectAssetUri, setARObjectAssetUri] = useState('')
  const [arObjectAssetMimeType, setARObjectAssetMimeType] = useState('')
  const [arObjectScenePreset, setARObjectScenePreset] = useState('')
  const [arObjectInstructionText, setARObjectInstructionText] = useState('')
  const [arObjectScaleMeters, setARObjectScaleMeters] = useState('1.0')
  const [arObjectOrientation, setARObjectOrientation] = useState('free')
  const [arObjectSortOrder, setARObjectSortOrder] = useState('0')
  const [arObjectStatus, setARObjectStatus] = useState('draft')
  const [savingARObject, setSavingARObject] = useState(false)
  const [arObjectError, setARObjectError] = useState<string | null>(null)
  const [arObjectNotice, setARObjectNotice] = useState<string | null>(null)
  const [showCreateARObject, setShowCreateARObject] = useState(false)
  // Индикатор загрузки геозон: список приходит пропсом (загружается в AdminApp),
  // поэтому loadingGeoZones всегда false (как было в AdminApp до выноса).
  const [loadingGeoZones] = useState(false)

  // Заполнение формы при выборе AR-объекта (перенесено из AdminApp дословно).
  useEffect(() => {
    const o = selectedARObject()
    if (!o) {
      setARObjectError(null)
      setARObjectNotice(null)
      return
    }
    setARObjectSlug(o.slug)
    setARObjectTitle(o.title)
    setARObjectDescription(o.description ?? '')
    setARObjectGeoZoneId(o.geoZoneId)
    setARObjectObjectType(o.objectType)
    setARObjectAssetUri(o.assetUri)
    setARObjectAssetMimeType(o.assetMimeType ?? '')
    setARObjectScenePreset(o.scenePreset ?? '')
    setARObjectInstructionText(o.instructionText ?? '')
    setARObjectScaleMeters(String(o.scaleMeters))
    setARObjectOrientation(o.orientation)
    setARObjectSortOrder(String(o.sortOrder))
    setARObjectStatus(o.status)
    setARObjectError(null)
    setARObjectNotice(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedARObjectId, arObjects])

  // Сброс create-режима при смене выбранного AR-объекта.
  useEffect(() => {
    setShowCreateARObject(false)
    setARObjectError(null)
  }, [selectedARObjectId])

  function selectedARObject(): AdminARObject | null {
    if (selectedARObjectId === null) return null
    return arObjects.find((o) => o.id === selectedARObjectId) ?? null
  }

  function buildARObjectPayloadCommon() {
    const slug = arObjectSlug.trim() || undefined
    const title = arObjectTitle.trim()
    if (title.length < 1) throw new Error('Название обязательно.')
    const geoZoneId = arObjectGeoZoneId.trim()
    if (geoZoneId.length < 1) throw new Error('GeoZone обязателен.')
    const objectType = arObjectObjectType.trim()
    if (objectType.length < 1) throw new Error('Тип объекта обязателен.')
    const assetUri = arObjectAssetUri.trim()
    // URL ассета обязателен только для «custom» (внешняя 3D-модель).
    // Для типов, рисуемых кодом (cube/sphere/root_logo/quantum_shield), URL не нужен.
    if (objectType === 'custom' && assetUri.length < 1) {
      throw new Error('URL ассета обязателен.')
    }
    const scale = Number.parseFloat(arObjectScaleMeters)
    if (!Number.isFinite(scale) || scale <= 0 || scale > 10) {
      throw new Error('Размер (scale) — число в диапазоне (0, 10].')
    }
    const sortOrder = Number.parseInt(arObjectSortOrder, 10)
    if (!Number.isFinite(sortOrder) || sortOrder < 0) {
      throw new Error('Порядок сортировки — целое ≥ 0.')
    }
    return { slug, title, geoZoneId, objectType, assetUri, scale, sortOrder }
  }

  async function handleCreateARObject() {
    setSavingARObject(true)
    setARObjectError(null)
    setARObjectNotice(null)
    try {
      const p = buildARObjectPayloadCommon()
      const created = await createARObject({
        slug: p.slug || undefined,
        title: p.title,
        description: arObjectDescription.trim() || null,
        sort_order: p.sortOrder,
        geo_zone_id: p.geoZoneId,
        object_type: p.objectType,
        asset_uri: p.assetUri,
        asset_mime_type: arObjectAssetMimeType.trim() || null,
        scene_preset: arObjectScenePreset.trim() || null,
        instruction_text: arObjectInstructionText.trim() || null,
        scale_meters: p.scale,
        orientation: arObjectOrientation,
      })
      onARObjectsChange([...arObjects, created])
      setSelectedARObjectId(created.id)
      setShowCreateARObject(false)
      setARObjectNotice('AR-объект создан.')
    } catch (err) {
      setARObjectError((err as Error).message)
    } finally {
      setSavingARObject(false)
    }
  }

  async function handleSaveARObject() {
    const o = selectedARObject()
    if (!o) return
    setSavingARObject(true)
    setARObjectError(null)
    setARObjectNotice(null)
    try {
      const p = buildARObjectPayloadCommon()
      const updated = await updateARObject(o.id, {
        slug: p.slug || undefined,
        title: p.title,
        description: arObjectDescription.trim() || null,
        status: arObjectStatus,
        sort_order: p.sortOrder,
        geo_zone_id: p.geoZoneId,
        object_type: p.objectType,
        asset_uri: p.assetUri,
        asset_mime_type: arObjectAssetMimeType.trim() || null,
        scene_preset: arObjectScenePreset.trim() || null,
        instruction_text: arObjectInstructionText.trim() || null,
        scale_meters: p.scale,
        orientation: arObjectOrientation,
      })
      onARObjectsChange(arObjects.map((x) => (x.id === updated.id ? updated : x)))
      setARObjectNotice('Сохранено.')
    } catch (err) {
      setARObjectError((err as Error).message)
    } finally {
      setSavingARObject(false)
    }
  }

  function handleShowCreateARObject() {
    setShowCreateARObject(true)
    setARObjectSlug('')
    setARObjectTitle('')
    setARObjectDescription('')
    setARObjectGeoZoneId('')
    setARObjectObjectType('cube')
    setARObjectAssetUri('')
    setARObjectAssetMimeType('')
    setARObjectScenePreset('')
    setARObjectInstructionText('')
    setARObjectScaleMeters('1.0')
    setARObjectOrientation('free')
    setARObjectSortOrder('0')
    setARObjectStatus('draft')
    setARObjectError(null)
    setARObjectNotice(null)
    setSelectedARObjectId(null)
  }

  // Обновление списка изнутри редактора (кнопка «Обновить список»).
  function handleRefreshARObjects() {
    setLoadingARObjects(true)
    setARObjectsError(null)
    listARObjects()
      .then((data) => onARObjectsChange(data))
      .catch((err: Error) => setARObjectsError(err.message))
      .finally(() => setLoadingARObjects(false))
  }

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <>
          <button
            className="admin-primary"
            onClick={handleShowCreateARObject}
            disabled={!canWrite}
          >
            + Новый AR-объект
          </button>
          <button
            className="admin-secondary"
            onClick={handleRefreshARObjects}
          >
            ↻ Обновить список
          </button>

          {arObjectsError && (
            <p className="admin-alert admin-error">{arObjectsError}</p>
          )}

          <div className="admin-mission-list">
            {arObjects.map((o) => (
              <button
                key={o.id}
                className={selectedARObjectId === o.id ? 'is-active' : ''}
                onClick={() => setSelectedARObjectId(o.id)}
              >
                <strong>{o.title}</strong>
                <small>{o.slug} · {o.objectType}</small>
                <span className={`admin-status admin-status-${o.status}`}>
                  {o.status}
                </span>
              </button>
            ))}
            {!loadingARObjects && arObjects.length === 0 && !arObjectsError && (
              <p className="admin-muted">AR-объектов нет.</p>
            )}
          </div>
        </>
      </aside>
      <section className="admin-editor">
        <>
          <div className="admin-editor-title">
            <div>
              <p className="admin-kicker">
                {showCreateARObject
                  ? 'НОВЫЙ AR-ОБЪЕКТ'
                  : selectedARObject() ? selectedARObject()!.id : '—'}
              </p>
              <h3>
                {showCreateARObject
                  ? 'Создание AR-объекта'
                  : selectedARObject() ? 'Редактирование AR-объекта' : 'Редактор AR-объекта'}
              </h3>
            </div>
            {selectedARObject() && !showCreateARObject && (
              <span className={`admin-status admin-status-${selectedARObject()!.status}`}>
                {selectedARObject()!.status}
              </span>
            )}
          </div>

          {arObjectError && <p className="admin-alert admin-error">{arObjectError}</p>}
          {arObjectNotice && <p className="admin-alert">{arObjectNotice}</p>}

          {!showCreateARObject && selectedARObject() === null ? (
            <p className="admin-muted">Выберите AR-объект слева или создайте новый.</p>
          ) : (
            <>
              <div className="admin-grid">
                <label className="admin-span-2">
                  Название *
                  <input value={arObjectTitle} disabled={!canWrite}
                    onChange={(e) => setARObjectTitle(e.target.value)} />
                </label>

                <label>
                  Slug
                  <input value={arObjectSlug} disabled={!canWrite}
                    placeholder="сгенерируется автоматически"
                    onChange={(e) => setARObjectSlug(e.target.value)} />
                </label>

                <label>
                  Порядок сортировки
                  <input type="number" value={arObjectSortOrder} disabled={!canWrite}
                    onChange={(e) => setARObjectSortOrder(e.target.value)} />
                </label>

                <label className="admin-span-2">
                  Описание
                  <textarea value={arObjectDescription} disabled={!canWrite}
                    onChange={(e) => setARObjectDescription(e.target.value)} />
                </label>
              </div>

              <div className="admin-grid">
                <label className="admin-span-2">
                  Геозона *
                  <select
                    value={arObjectGeoZoneId}
                    disabled={!canWrite || loadingGeoZones}
                    onChange={(e) => setARObjectGeoZoneId(e.target.value)}
                  >
                    <option value="">
                      {loadingGeoZones ? 'Загрузка…' : '— выберите зону —'}
                    </option>
                    {arObjectGeoZoneId && !geoZones.some((z) => z.id === arObjectGeoZoneId) && (
                      <option value={arObjectGeoZoneId}>
                        (нет в списке: {arObjectGeoZoneId})
                      </option>
                    )}
                    {geoZones.map((z) => (
                      <option key={z.id} value={z.id}>
                        {z.title} · {z.slug} [{z.status}]
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="admin-grid">
                <label>
                  Тип объекта *
                  <select value={arObjectObjectType} disabled={!canWrite}
                    onChange={(e) => setARObjectObjectType(e.target.value)}>
                    <option value="cube">cube — куб</option>
                    <option value="sphere">sphere — сфера</option>
                    <option value="custom">custom — другая 3D-модель</option>
                    <option value="root_logo">root_logo — Золотой ROOT (логотип)</option>
                    <option value="quantum_shield">quantum_shield — Квантовый щит</option>
                  </select>
                </label>

                {arObjectObjectType === 'custom' && (
                  <label>
                    URL ассета *
                    <input value={arObjectAssetUri} disabled={!canWrite}
                      placeholder="https://cdn.example.com/models/cube.glb"
                      onChange={(e) => setARObjectAssetUri(e.target.value)} />
                  </label>
                )}

                {arObjectObjectType === 'custom' && (
                  <label>
                    MIME-тип (опционально)
                    <input value={arObjectAssetMimeType} disabled={!canWrite}
                      placeholder="model/gltf-binary"
                      onChange={(e) => setARObjectAssetMimeType(e.target.value)} />
                  </label>
                )}

                <label>
                  Scene preset (опционально)
                  <input value={arObjectScenePreset} disabled={!canWrite}
                    placeholder="archive_cube_damaged_v1"
                    onChange={(e) => setARObjectScenePreset(e.target.value)} />
                </label>
              </div>

              <div className="admin-grid">
                <label>
                  Размер (метры) *
                  <input type="number" step="0.1" value={arObjectScaleMeters} disabled={!canWrite}
                    onChange={(e) => setARObjectScaleMeters(e.target.value)} />
                  <small className="admin-muted">
                    Реальный размер объекта в мире. 1.0 = 1 метр.
                  </small>
                </label>

                <label>
                  Ориентация
                  <select value={arObjectOrientation} disabled={!canWrite}
                    onChange={(e) => setARObjectOrientation(e.target.value)}>
                    <option value="free">free — вращается</option>
                    <option value="upright">upright — стоит</option>
                    <option value="flat">flat — лежит плашмя</option>
                  </select>
                </label>
              </div>

              <label className="admin-span-2">
                Инструкция игроку (опционально)
                <textarea value={arObjectInstructionText} disabled={!canWrite}
                  onChange={(e) => setARObjectInstructionText(e.target.value)} />
              </label>

              {!showCreateARObject && (
                <div className="admin-grid">
                  <label>
                    Статус
                    <select value={arObjectStatus} disabled={!canWrite}
                      onChange={(e) => setARObjectStatus(e.target.value)}>
                      <option value="draft">draft — черновик</option>
                      <option value="published">published — активен</option>
                      <option value="archived">archived — архив</option>
                    </select>
                  </label>
                </div>
              )}

              <div className="admin-actions">
                {showCreateARObject ? (
                  <>
                    <button className="admin-primary" onClick={handleCreateARObject}
                      disabled={!canWrite || savingARObject}>
                      {savingARObject ? 'Создание…' : 'Создать'}
                    </button>
                    <button className="admin-secondary" onClick={() => setShowCreateARObject(false)}
                      disabled={savingARObject}>
                      Отмена
                    </button>
                  </>
                ) : (
                  <button className="admin-primary" onClick={handleSaveARObject}
                    disabled={!canWrite || savingARObject}>
                    {savingARObject ? 'Сохранение…' : 'Сохранить'}
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
