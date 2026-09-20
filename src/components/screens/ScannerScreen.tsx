import { useState } from 'react'
import type { EngineMission } from '../../api/engineApi'
import type { Screen } from '../../types/game'
import { activeSegment } from '../../data/activeSegment'
import { missionText, missionBlocks } from '../../utils/missionHelpers'
import { calculateDistanceInMeters, openRouteInNavigator } from '../../utils/geolocation'

interface ScannerScreenProps {
  missions: EngineMission[]
  onScreenChange: (screen: Screen) => void
  onSubmitMission: (missionId: string, payload: { sequence?: string[] }) => Promise<any>
}

export function ScannerScreen({ missions, onScreenChange, onSubmitMission }: ScannerScreenProps) {
  const [distanceToSegment, setDistanceToSegment] = useState<number | null>(null)
  const [isCheckingLocation, setIsCheckingLocation] = useState(false)
  const [locationError, setLocationError] = useState('')
  const [arSessionStarted, setArSessionStarted] = useState(false)
  const [isSegmentFaceLocked, setIsSegmentFaceLocked] = useState(false)
  const [virtualQrRevealed, setVirtualQrRevealed] = useState(false)
  const [isCodeRepairOpen, setIsCodeRepairOpen] = useState(false)
  const [repairSequence, setRepairSequence] = useState<string[]>([])
  const [repairError, setRepairError] = useState('')

  const isSegmentMissionComplete = missions.some(
    (mission) =>
      mission.id === 'mission-archive-017' && mission.status === 'completed',
  )

  const activeMission =
    missions.find(
      (mission) =>
        mission.id === 'mission-archive-017' && mission.status !== 'completed',
    ) ??
    missions.find((mission) => mission.id === 'mission-archive-017') ??
    null

  const missionA17 = missions.find(
    (mission) => mission.id === 'mission-archive-017',
  )

  const repairBlocks = missionBlocks(missionA17, [
    'packet.',
    'signature',
    'return ',
  ])

  const canStartArSearch =
    distanceToSegment !== null &&
    distanceToSegment <= activeSegment.safeScanRadiusMeters

  function checkPlayerLocation() {
    if (!navigator.geolocation) {
      setLocationError('Геолокация не поддерживается этим устройством.')
      return
    }

    setLocationError('')
    setIsCheckingLocation(true)

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const distance = calculateDistanceInMeters(
          position.coords.latitude,
          position.coords.longitude,
          activeSegment.safeScanPoint.latitude,
          activeSegment.safeScanPoint.longitude,
        )

        setDistanceToSegment(distance)
        setIsCheckingLocation(false)
      },
      (error) => {
        setIsCheckingLocation(false)

        if (error.code === error.PERMISSION_DENIED) {
          setLocationError(
            'Доступ к геолокации запрещён. Разрешите его в настройках браузера или Telegram.',
          )
          return
        }

        if (error.code === error.POSITION_UNAVAILABLE) {
          setLocationError(
            'Не удалось определить позицию. Проверьте GPS, интернет и настройки геолокации.',
          )
          return
        }

        setLocationError(
          'Не удалось получить геопозицию. Попробуйте ещё раз через несколько секунд.',
        )
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0,
      },
    )
  }

  function startArSearch() {
    setArSessionStarted(true)
    setIsSegmentFaceLocked(false)
    setVirtualQrRevealed(false)
    setIsCodeRepairOpen(false)
    setRepairSequence([])
    setRepairError('')
  }

  function addRepairBlock(block: string) {
    if (isSegmentMissionComplete) return

    setRepairError('')
    setRepairSequence((currentSequence) => {
      if (currentSequence.length >= 3) return currentSequence
      return [...currentSequence, block]
    })
  }

  async function submitCodeRepair() {
    const response = await onSubmitMission('mission-archive-017', {
      sequence: repairSequence,
    })

    if (!response) {
      setRepairError('СЕРВЕР НЕДОСТУПЕН. ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ.')
      return
    }

    if (!response.accepted) {
      setRepairError(
        response.message ??
          'СТРУКТУРА ПАКЕТА НАРУШЕНА. ОЧИСТИТЕ СТРОКУ И ВОССТАНОВИТЕ ЕЁ ЗАНОВО.',
      )
      return
    }

    setRepairError('')
  }

  return (
    <section className="segment-screen">
      <p className="eyebrow">
        {activeMission
          ? `АКТИВНАЯ МИССИЯ / ${activeMission.id.toUpperCase()}`
          : 'АРХИВНЫЙ СЕГМЕНТ / ВОССТАНОВЛЕН'}
      </p>

      <div className="segment-heading">
        <div>
          <span className="segment-type">{activeSegment.type}</span>
          <h2>{activeMission?.title ?? activeSegment.title}</h2>
          <p>{activeMission?.description ?? activeSegment.description}</p>
        </div>

        <div className="segment-code">
          <span>ИДЕНТИФИКАТОР</span>
          <strong>{activeSegment.code}</strong>
        </div>
      </div>

      <section className="segment-card">
        <div className="segment-visual">
          <div className="segment-cube">
            <span className="cube-face cube-front">▦</span>
            <span className="cube-face cube-side">01</span>
            <span className="cube-face cube-top">⌗</span>
          </div>
          <span className="signal-ring signal-ring-one" />
          <span className="signal-ring signal-ring-two" />
        </div>

        <div className="segment-details">
          <span className="file-label">ПАРАМЕТРЫ МИССИИ</span>

          <dl className="segment-stats">
            <div>
              <dt>РАДИУС ПОИСКА</dt>
              <dd>{activeSegment.searchRadiusMeters} м</dd>
            </div>
            <div>
              <dt>SAFE SCAN POINT</dt>
              <dd>{activeSegment.safeScanRadiusMeters} м</dd>
            </div>
            <div>
              <dt>НАГРАДА ЗА УСПЕХ</dt>
              <dd>+{activeSegment.reward.root} ROOT</dd>
            </div>
            <div>
              <dt>ТИП СЦЕНЫ</dt>
              <dd>{activeSegment.arScene.scenePreset}</dd>
            </div>
          </dl>

          {activeSegment.reward.itemName && (
            <p className="segment-item-reward">
              ПРЕДМЕТ: {activeSegment.reward.itemName}
            </p>
          )}
        </div>
      </section>

      <section className="location-panel">
        <div>
          <span className="file-label">НАВИГАЦИЯ И ПРОВЕРКА ПОЗИЦИИ</span>
          <h3>Найдите безопасную точку сканирования</h3>
          <p>
            Откройте маршрут в навигаторе телефона. После прибытия
            вернитесь в игру и подтвердите своё местоположение.
          </p>
        </div>

        <div className="location-actions">
          <button
            className="route-button"
            onClick={() =>
              openRouteInNavigator(
                activeSegment.safeScanPoint.latitude,
                activeSegment.safeScanPoint.longitude,
              )
            }
          >
            ОТКРЫТЬ МАРШРУТ →
          </button>

          <button
            className="location-button"
            onClick={checkPlayerLocation}
            disabled={isCheckingLocation}
          >
            {isCheckingLocation ? 'ОПРЕДЕЛЯЕМ ПОЗИЦИЮ...' : 'ПРОВЕРИТЬ ПОЗИЦИЮ'}
          </button>
        </div>
      </section>

      <section
        className={`location-status ${
          canStartArSearch ? 'location-status-success' : ''
        }`}
      >
        {locationError ? (
          <>
            <span className="location-status-icon">!</span>
            <div>
              <strong>ОШИБКА ГЕОЛОКАЦИИ</strong>
              <p>{locationError}</p>
            </div>
          </>
        ) : distanceToSegment === null ? (
          <>
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>ПОЗИЦИЯ НЕ ПРОВЕРЕНА</strong>
              <p>
                Для запуска AR-поиска подтвердите, что вы находитесь у
                безопасной точки сканирования.
              </p>
            </div>
          </>
        ) : canStartArSearch ? (
          <>
            <span className="location-status-icon">✓</span>
            <div>
              <strong>SAFE SCAN POINT ДОСТУПЕН</strong>
              <p>
                Расстояние до безопасной точки: {distanceToSegment} м. Можно
                запускать AR-поиск.
              </p>
            </div>
          </>
        ) : (
          <>
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>ТОЧКА СКАНИРОВАНИЯ СЛИШКОМ ДАЛЕКО</strong>
              <p>
                Расстояние: {distanceToSegment} м. Для запуска AR-поиска нужно
                подойти ближе чем на {activeSegment.safeScanRadiusMeters} м.
              </p>
            </div>
          </>
        )}
      </section>

      {!arSessionStarted ? (
        <button
          className="ar-start-button"
          onClick={startArSearch}
          disabled={!canStartArSearch}
        >
          {canStartArSearch ? 'ЗАПУСТИТЬ AR-ПОИСК' : 'AR-ПОИСК ЗАБЛОКИРОВАН'}
        </button>
      ) : isSegmentMissionComplete ? (
        <section className="mission-success-card">
          <span className="file-label">ПАКЕТ ВОССТАНОВЛЕН</span>
          <div className="mission-success-symbol">✓</div>
          <h3>СЕГМЕНТ СТАБИЛИЗИРОВАН</h3>
          <p>
            Кодовая структура восстановлена. Архив извлечён из нестабильного
            контура.
          </p>
          <div className="mission-reward-grid">
            <div>
              <span>ПОЛУЧЕНО</span>
              <strong>+{activeSegment.reward.root} ROOT</strong>
            </div>
            <div>
              <span>ИЗВЛЕЧЁН ОБЪЕКТ</span>
              <strong>{activeSegment.reward.itemName}</strong>
            </div>
          </div>
          <small>
            В production награда, предмет и прогресс будут подтверждаться только
            backend-сервером.
          </small>
        </section>
      ) : isCodeRepairOpen ? (
        <section className="code-repair-panel">
          <span className="file-label">
            {missionText(missionA17, 'label', 'МИНИ-ИГРА / CODE REPAIR')}
          </span>
          <h3>Восстановите повреждённую строку</h3>
          <p>
            {missionText(
              missionA17,
              'instruction',
              'Архивный пакет потерял порядок трёх блоков. Соберите корректную команду извлечения подписи.',
            )}
          </p>

          <div className="code-window">
            <span className="code-line-number">
              {missionText(missionA17, 'lineNumber', '017')}
            </span>
            <code>
              {repairSequence.length > 0 ? (
                repairSequence.map((block, index) => (
                  <span key={`${block}-${index}`}>{block}</span>
                ))
              ) : (
                <span className="code-placeholder">
                  {missionText(
                    missionA17,
                    'placeholder',
                    '// выберите блоки ниже',
                  )}
                </span>
              )}
            </code>
          </div>

          <div className="repair-blocks">
            {repairBlocks.map((block) => (
              <button key={block} onClick={() => addRepairBlock(block)}>
                {block}
              </button>
            ))}
          </div>

          {repairError && <p className="repair-error">{repairError}</p>}

          <div className="repair-actions">
            <button
              className="repair-clear-button"
              onClick={() => {
                setRepairSequence([])
                setRepairError('')
              }}
            >
              ОЧИСТИТЬ
            </button>
            <button
              className="repair-submit-button"
              onClick={submitCodeRepair}
              disabled={repairSequence.length !== 3}
            >
              ПРОВЕРИТЬ КОД →
            </button>
          </div>
        </section>
      ) : (
        <section className="ar-placeholder">
          <span className="file-label">AR-СЕССИЯ ИНИЦИАЛИЗИРОВАНА</span>
          <div
            className={`ar-placeholder-frame ${
              isSegmentFaceLocked ? 'face-locked' : ''
            }`}
          >
            <div className="ar-cube">
              {virtualQrRevealed ? <span className="virtual-qr">▦</span> : '▦'}
            </div>
            <div className="ar-reticle">+</div>
            <span className="ar-scan-line" />
            {isSegmentFaceLocked && (
              <span className="face-lock-status">ГРАНЬ ЗАФИКСИРОВАНА</span>
            )}
          </div>

          {!isSegmentFaceLocked ? (
            <>
              <h3>Наведите прицел на грань Сегмента</h3>
              <p>
                Зафиксируйте одну из граней виртуального куба, чтобы начать
                извлечение архивного маркера.
              </p>
              <button
                className="ar-action-button"
                onClick={() => setIsSegmentFaceLocked(true)}
              >
                ЗАФИКСИРОВАТЬ ГРАНЬ
              </button>
            </>
          ) : !virtualQrRevealed ? (
            <>
              <h3>Грань синхронизирована</h3>
              <p>
                На поверхности объекта обнаружена повреждённая QR-структура.
                Запустите её визуальное извлечение.
              </p>
              <button
                className="ar-action-button"
                onClick={() => setVirtualQrRevealed(true)}
              >
                ПРОЯВИТЬ QR-МАРКЕР
              </button>
            </>
          ) : (
            <>
              <h3>Виртуальный QR-маркер извлечён</h3>
              <p>
                Серверная сессия сканирования в будущем будет создана на этом
                шаге. Сейчас откроется тестовая головоломка.
              </p>
              <button
                className="ar-action-button"
                onClick={() => setIsCodeRepairOpen(true)}
              >
                ИЗВЛЕЧЬ ДАННЫЕ →
              </button>
            </>
          )}
        </section>
      )}

      <button className="back-button" onClick={() => onScreenChange('terminal')}>
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}
