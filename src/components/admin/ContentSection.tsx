import { useState } from 'react'
import type { AdminARObject, AdminGeoZone, AdminUser } from '../../api/adminApi'
import { SegmentsEditor } from './SegmentsEditor'
import { GeoZonesEditor } from './GeoZonesEditor'
import { ARObjectsEditor } from './ARObjectsEditor'

type ContentSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
  // geoZones и arObjects — общие списки (миссии + редакторы в ContentSection).
  geoZones: AdminGeoZone[]
  arObjects: AdminARObject[]
  // Обновляет общий список geoZones в AdminApp (после create/update/refresh в редакторе).
  onGeoZonesChange: (updater: (prev: AdminGeoZone[]) => AdminGeoZone[]) => void
  // Обновляет общий список arObjects в AdminApp (после create/update/refresh в редакторе).
  onARObjectsChange: (arObjects: AdminARObject[]) => void
}

export function ContentSection({
  admin,
  canWrite,
  onError,
  onNotice,
  geoZones,
  arObjects,
  onGeoZonesChange,
  onARObjectsChange,
}: ContentSectionProps) {
  const [contentTab, setContentTab] = useState<'segments' | 'geozones' | 'arobjects'>('segments')

  return (
    <>
      <div className="admin-editor-title">
        <div>
          <p className="admin-kicker">КОНТЕНТ</p>
          <h2>Управление контентом</h2>
        </div>
      </div>

      <nav className="admin-nav" style={{ marginBottom: '1rem' }}>
        <button
          className={contentTab === 'segments' ? 'is-active' : ''}
          onClick={() => setContentTab('segments')}
        >
          Сегменты
        </button>
        <button
          className={contentTab === 'geozones' ? 'is-active' : ''}
          onClick={() => setContentTab('geozones')}
        >
          Геозоны
        </button>
        <button
          className={contentTab === 'arobjects' ? 'is-active' : ''}
          onClick={() => setContentTab('arobjects')}
        >
          AR-объекты
        </button>
      </nav>

      {contentTab === 'segments' && (
        <SegmentsEditor admin={admin} canWrite={canWrite} onError={onError} onNotice={onNotice} />
      )}

      {contentTab === 'geozones' && (
        <GeoZonesEditor
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          geoZones={geoZones}
          onGeoZonesChange={onGeoZonesChange}
        />
      )}

      {contentTab === 'arobjects' && (
        <ARObjectsEditor
          admin={admin}
          canWrite={canWrite}
          onError={onError}
          onNotice={onNotice}
          arObjects={arObjects}
          onARObjectsChange={onARObjectsChange}
          geoZones={geoZones}
        />
      )}
    </>
  )
}
