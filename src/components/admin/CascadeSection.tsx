import { useEffect, useState, type CSSProperties } from 'react'
import {
  listChapters,
  listSeasons,
  listSegments,
  type AdminChapter,
  type AdminSeason,
  type AdminSegment,
  type AdminUser,
} from '../../api/adminApi'

type CascadeSectionProps = {
  admin: AdminUser | null
  canWrite: boolean
  onError: (message: string) => void
  onNotice: (message: string) => void
}

const columnStyle: CSSProperties = { flex: 1, minWidth: 0 }

export function CascadeSection({
  admin: _admin,
  canWrite: _canWrite,
  onError: _onError,
  onNotice: _onNotice,
}: CascadeSectionProps) {
  const [seasons, setSeasons] = useState<AdminSeason[]>([])
  const [loadingSeasons, setLoadingSeasons] = useState(false)
  const [seasonsError, setSeasonsError] = useState<string | null>(null)
  const [selectedSeasonId, setSelectedSeasonId] = useState<string | null>(null)

  const [chapters, setChapters] = useState<AdminChapter[]>([])
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [chaptersError, setChaptersError] = useState<string | null>(null)
  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null)

  const [segments, setSegments] = useState<AdminSegment[]>([])
  const [loadingSegments, setLoadingSegments] = useState(false)
  const [segmentsError, setSegmentsError] = useState<string | null>(null)
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null)

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

  useEffect(() => {
    if (selectedSeasonId === null) {
      setChapters([])
      setSelectedChapterId(null)
      setSegments([])
      setSelectedSegmentId(null)
      return
    }
    let cancelled = false
    setLoadingChapters(true)
    setChaptersError(null)
    listChapters(undefined, selectedSeasonId)
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
    return () => {
      cancelled = true
    }
  }, [selectedSeasonId])

  useEffect(() => {
    if (selectedChapterId === null) {
      setSegments([])
      setSelectedSegmentId(null)
      return
    }
    let cancelled = false
    setLoadingSegments(true)
    setSegmentsError(null)
    listSegments(selectedChapterId)
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
  }, [selectedChapterId])

  const selectedSegment =
    segments.find((item) => item.id === selectedSegmentId) ?? null

  return (
    <div className="admin-layout">
      <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
        <div style={columnStyle}>
          <h3>Сезоны</h3>
          {seasonsError && <p className="admin-alert admin-error">{seasonsError}</p>}
          <div className="admin-mission-list">
            {loadingSeasons && seasons.length === 0 && (
              <p className="admin-muted">Загрузка…</p>
            )}
            {seasons.map((season) => (
              <button
                className={`admin-mission-row ${selectedSeasonId === season.id ? 'is-active' : ''}`}
                key={season.id}
                onClick={() => {
                  setSelectedSeasonId(season.id)
                  setSelectedChapterId(null)
                  setSelectedSegmentId(null)
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
        </div>

        <div style={columnStyle}>
          <h3>Главы</h3>
          {selectedSeasonId === null ? (
            <p className="admin-muted">Выберите сезон</p>
          ) : (
            <>
              {chaptersError && (
                <p className="admin-alert admin-error">{chaptersError}</p>
              )}
              <div className="admin-mission-list">
                {loadingChapters && chapters.length === 0 && (
                  <p className="admin-muted">Загрузка…</p>
                )}
                {chapters.map((chapter) => (
                  <button
                    className={`admin-mission-row ${selectedChapterId === chapter.id ? 'is-active' : ''}`}
                    key={chapter.id}
                    onClick={() => {
                      setSelectedChapterId(chapter.id)
                      setSelectedSegmentId(null)
                    }}
                  >
                    <span className={`admin-status admin-status-${chapter.status}`}>
                      {chapter.status}
                    </span>
                    <strong>{chapter.title}</strong>
                    <small>
                      {chapter.slug} · sortOrder {chapter.sortOrder}
                    </small>
                  </button>
                ))}
                {!loadingChapters &&
                  chapters.length === 0 &&
                  !chaptersError && (
                    <p className="admin-muted">В этом сезоне глав нет.</p>
                  )}
              </div>
            </>
          )}
        </div>

        <div style={columnStyle}>
          <h3>Части</h3>
          {selectedChapterId === null ? (
            <p className="admin-muted">Выберите главу</p>
          ) : (
            <>
              {segmentsError && (
                <p className="admin-alert admin-error">{segmentsError}</p>
              )}
              <div className="admin-mission-list">
                {loadingSegments && segments.length === 0 && (
                  <p className="admin-muted">Загрузка…</p>
                )}
                {segments.map((segment) => (
                  <button
                    className={`admin-mission-row ${selectedSegmentId === segment.id ? 'is-active' : ''}`}
                    key={segment.id}
                    onClick={() => {
                      setSelectedSegmentId(segment.id)
                    }}
                  >
                    <span className={`admin-status admin-status-${segment.status}`}>
                      {segment.status}
                    </span>
                    <strong>{segment.title}</strong>
                    <small>
                      {segment.slug} · sortOrder {segment.sortOrder}
                    </small>
                  </button>
                ))}
                {!loadingSegments &&
                  segments.length === 0 &&
                  !segmentsError && (
                    <p className="admin-muted">В этой главе частей нет.</p>
                  )}
              </div>
            </>
          )}
        </div>

        <div style={columnStyle}>
          <h3>Миссии части</h3>
          {selectedSegment === null ? (
            <p className="admin-muted">Выберите часть</p>
          ) : selectedSegment.linkedMissions.length === 0 ? (
            <p className="admin-muted">В части нет миссий</p>
          ) : (
            <div className="admin-mission-list">
              {selectedSegment.linkedMissions.map((link) => {
                const linkTitle = (link as { title?: string }).title
                return (
                  <div className="admin-mission-row" key={link.id}>
                    {linkTitle ? (
                      <>
                        <strong>{linkTitle}</strong>
                        <small>
                          {link.missionId} · sortOrder {link.sortOrder}
                        </small>
                      </>
                    ) : (
                      <>
                        <strong>{link.missionId}</strong>
                        <small>sortOrder {link.sortOrder}</small>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

