import { useState } from 'react'
import type {
  EngineMission,
  EngineSegment,
  MissionSubmission,
} from '../../api/engineApi'
import type { Screen } from '../../types/game'
import {
  calculateDistanceInMeters,
  openRouteInNavigator,
} from '../../utils/geolocation'
import { EchoRadar } from '../EchoRadar'
import { MissionTimer } from '../MissionTimer'
import { useActiveMission, type MissionLayer } from '../../hooks/useActiveMission'
import { MISSION_LAYER_COLORS } from '../../constants/missionLayerColors'
import Game3DScene from '../Game3DScene'

type SegmentContent = {
  code: string
  type: string
  searchRadiusMeters: number
  safeScanRadiusMeters: number
  latitude: number
  longitude: number
  scenePreset: string
  objectType: string | null
}

type CodeRepairContent = {
  label: string | null
  instruction: string | null
  blocks: string[]
  maxBlocks: number
  lineNumber: string | null
  placeholder: string | null
  wrongAnswerText: string | null
  rewardPreviewText: string | null
}

interface ScannerScreenProps {
  missions: EngineMission[]
  segments: EngineSegment[]
  onScreenChange: (screen: Screen) => void
  onSubmitMission: (
    missionId: string,
    payload: { sequence?: string[] },
  ) => Promise<MissionSubmission | null>
  geoPosition: { lat: number; lng: number; accuracy: number } | null
  geoError: string | null
  onExpireMission: (
    missionId: string,
  ) => Promise<{ ok: boolean; error?: string }>
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function asNumber(
  value: unknown,
  minimum: number,
  maximum: number,
): number | null {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum
  ) {
    return null
  }
  return value
}

function parseSegmentContent(
  content: Record<string, unknown>,
): SegmentContent | null {
  const presentation = asRecord(content.presentation)
  const location = asRecord(content.location)
  const point = asRecord(location?.safeScanPoint)
  const arScene = asRecord(content.arScene)

  const code = asText(presentation?.code)
  const type = asText(presentation?.type)
  const searchRadiusMeters = asNumber(location?.searchRadiusMeters, 1, 100_000)
  const safeScanRadiusMeters = asNumber(
    location?.safeScanRadiusMeters,
    1,
    100_000,
  )
  const latitude = asNumber(point?.latitude, -90, 90)
  const longitude = asNumber(point?.longitude, -180, 180)
  const scenePreset = asText(arScene?.scenePreset)
  // Тип AR-объекта из админки (ARObjectsEditor). null — не задан:
  // для обратной совместимости такой сегмент показывает старую заглушку.
  const objectType = asText(arScene?.object_type)

  if (
    !code ||
    !type ||
    searchRadiusMeters === null ||
    safeScanRadiusMeters === null ||
    searchRadiusMeters < safeScanRadiusMeters ||
    latitude === null ||
    longitude === null ||
    !scenePreset
  ) {
    return null
  }

  return {
    code,
    type,
    searchRadiusMeters,
    safeScanRadiusMeters,
    latitude,
    longitude,
    scenePreset,
    objectType,
  }
}

function parseCodeRepairContent(
  mission: EngineMission,
): CodeRepairContent | null {
  const root = asRecord(mission.content)
  const ui = asRecord(root?.ui)

  if (!ui) {
    return null
  }

  const blocks = Array.isArray(ui.blocks) &&
    ui.blocks.length > 0 &&
    ui.blocks.every(
      (block) => typeof block === 'string' && block.trim(),
    )
    ? ui.blocks as string[]
    : null

  const maxBlocks = asNumber(ui.maxBlocks, 1, 100)

  if (!blocks || maxBlocks === null) {
    return null
  }

  const rewardPreview = asRecord(ui.rewardPreview)

  return {
    label: asText(ui.label),
    instruction: asText(ui.instruction),
    blocks,
    maxBlocks,
    lineNumber: asText(ui.lineNumber),
    placeholder: asText(ui.placeholder),
    wrongAnswerText: asText(ui.wrongAnswerText),
    rewardPreviewText: asText(rewardPreview?.text),
  }
}

function formatAwarded(response: MissionSubmission): string {
  const parts: string[] = []

  if (response.awarded.root > 0) {
    parts.push(`${response.awarded.root} ROOT`)
  }

  for (const item of response.awarded.items) {
    parts.push(`${item.title} ×${item.quantity}`)
  }

  return parts.length > 0
    ? parts.join(' · ')
    : 'Прогресс подтверждён сервером.'
}

export function ScannerScreen({
  missions,
  segments,
  onScreenChange,
  onSubmitMission,
  geoPosition,
  geoError,
  onExpireMission,
}: ScannerScreenProps) {
  const [distanceToSegment, setDistanceToSegment] = useState<number | null>(null)
  const [isCheckingLocation, setIsCheckingLocation] = useState(false)
  const [locationError, setLocationError] = useState('')
  const [arSessionStarted, setArSessionStarted] = useState(false)
  const [isSegmentFaceLocked, setIsSegmentFaceLocked] = useState(false)
  const [virtualQrRevealed, setVirtualQrRevealed] = useState(false)
  const [isCodeRepairOpen, setIsCodeRepairOpen] = useState(false)
  const [repairSequence, setRepairSequence] = useState<string[]>([])
  const [repairError, setRepairError] = useState('')
  const [confirmedAward, setConfirmedAward] = useState<string | null>(null)
  const [selectedLayer, setSelectedLayer] = useState<MissionLayer>('solo')

  const spawnMission = useActiveMission(missions, geoPosition, selectedLayer)

  const activeMission = missions.find(
    (mission) =>
      (mission.status === 'available' || mission.status === 'in_progress') &&
      parseCodeRepairContent(mission) !== null &&
      segments.some((segment) =>
        segment.linkedMissions.some((link) => link.id === mission.id),
      ),
  ) ?? null

  const activeSegment = activeMission
    ? segments.find((segment) =>
      segment.linkedMissions.some((link) => link.id === activeMission.id),
    ) ?? null
    : null

  const segmentContent = activeSegment
    ? parseSegmentContent(activeSegment.content)
    : null

  const codeRepairContent = activeMission
    ? parseCodeRepairContent(activeMission)
    : null

  if (spawnMission) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">АКТИВНАЯ МИССИЯ / {spawnMission.id.toUpperCase()}</p>

        <div className="segment-heading">
          <div>
            <h2>{spawnMission.title}</h2>
            <p>{spawnMission.description}</p>
          </div>
        </div>

        {!geoPosition ? (
          <section className="location-status">
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>{geoError ? 'ГЕОЛОКАЦИЯ НЕДОСТУПНА' : 'ОПРЕДЕЛЯЕМ ПОЗИЦИЮ…'}</strong>
              <p>{geoError ?? 'Разрешите геолокацию, чтобы увидеть радар.'}</p>
            </div>
          </section>
        ) : (
          <>
            <div className="layer-switch">
              {(['solo', 'team', 'story'] as const).map((layer) => (
                <button
                  key={layer}
                  className={`layer-switch-btn layer-switch-${layer}${selectedLayer === layer ? ' is-active' : ''}`}
                  onClick={() => setSelectedLayer(layer)}
                >
                  {layer === 'solo' ? 'СОЛО' : layer === 'team' ? 'КОМАНДА' : 'СЮЖЕТ'}
                </button>
              ))}
            </div>

            {spawnMission.deadlineAt && (
              <MissionTimer
                deadlineAt={spawnMission.deadlineAt}
                label="до конца задания"
                onClick={() => void onExpireMission(spawnMission.id)}
              />
            )}

            <EchoRadar
              playerLat={geoPosition.lat}
              playerLng={geoPosition.lng}
              playerAccuracy={geoPosition.accuracy}
              targetLat={spawnMission.spawn!.latitude}
              targetLng={spawnMission.spawn!.longitude}
              hint="Идите по радару. Когда приблизитесь — откройте камеру."
              color={MISSION_LAYER_COLORS[selectedLayer]}
            />
            <button
              className="ar-start-button"
              onClick={() => onScreenChange('camera-test')}
            >
              ОТКРЫТЬ КАМЕРУ →
            </button>
          </>
        )}

        <button
          className="back-button"
          onClick={() => onScreenChange('terminal')}
        >
          ← ВЕРНУТЬСЯ В КОНТУР
        </button>
      </section>
    )
  }

  if (!activeMission || !activeSegment || !segmentContent || !codeRepairContent) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">СКАНЕР / CMS-СЕГМЕНТ НЕДОСТУПЕН</p>
        <section className="location-status">
          <span className="location-status-icon">⌖</span>
          <div>
            <strong>НЕТ ДОСТУПНОЙ ТОЧКИ СКАНИРОВАНИЯ</strong>
            <p>
              Опубликованный Segment с доступной scanner-миссией ещё не получен
              из игрового bootstrap либо содержит некорректный public content.
            </p>
          </div>
        </section>
        <button className="back-button" onClick={() => onScreenChange('terminal')}>
          ← ВЕРНУТЬСЯ В КОНТУР
        </button>
      </section>
    )
  }

  // The safe empty-state return above guarantees these CMS values exist here.
  // Local constants preserve that narrowing inside browser/API callbacks.
  const mission = activeMission
  const content = segmentContent
  const repair = codeRepairContent

  const canStartArSearch =
    distanceToSegment !== null &&
    distanceToSegment <= content.safeScanRadiusMeters

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
          content.latitude,
          content.longitude,
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
        } else if (error.code === error.POSITION_UNAVAILABLE) {
          setLocationError(
            'Не удалось определить позицию. Проверьте GPS, интернет и настройки геолокации.',
          )
        } else {
          setLocationError(
            'Не удалось получить геопозицию. Попробуйте ещё раз через несколько секунд.',
          )
        }
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  }

  function startArSearch() {
    setArSessionStarted(true)
    setIsSegmentFaceLocked(false)
    setVirtualQrRevealed(false)
    setIsCodeRepairOpen(false)
    setRepairSequence([])
    setRepairError('')
    setConfirmedAward(null)
  }

  function addRepairBlock(block: string) {
    setRepairError('')
    setRepairSequence((current) =>
      current.length >= repair.maxBlocks
        ? current
        : [...current, block],
    )
  }

  async function submitCodeRepair() {
    const response = await onSubmitMission(mission.id, {
      sequence: repairSequence,
    })

    if (!response) {
      setRepairError('СЕРВЕР НЕДОСТУПЕН. ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ.')
      return
    }

    if (!response.accepted) {
      setRepairError(
        response.message ??
          repair.wrongAnswerText ??
          'СТРУКТУРА ПАКЕТА НАРУШЕНА. ОЧИСТИТЕ СТРОКУ И ВОССТАНОВИТЕ ЕЁ ЗАНОВО.',
      )
      return
    }

    setRepairError('')
    setConfirmedAward(formatAwarded(response))
  }

  return (
    <section className="segment-screen">
      <p className="eyebrow">
        АКТИВНАЯ МИССИЯ / {mission.id.toUpperCase()}
      </p>

      <div className="segment-heading">
        <div>
          <span className="segment-type">{content.type}</span>
          <h2>{mission.title}</h2>
          <p>{mission.description}</p>
        </div>
        <div className="segment-code">
          <span>ИДЕНТИФИКАТОР</span>
          <strong>{content.code}</strong>
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
              <dd>{content.searchRadiusMeters} м</dd>
            </div>
            <div>
              <dt>SAFE SCAN POINT</dt>
              <dd>{content.safeScanRadiusMeters} м</dd>
            </div>
            <div>
              <dt>ТИП СЦЕНЫ</dt>
              <dd>{content.scenePreset}</dd>
            </div>
          </dl>
          {repair.rewardPreviewText && (
            <p className="segment-item-reward">
              ПРЕДПРОСМОТР НАГРАДЫ: {repair.rewardPreviewText}
            </p>
          )}
        </div>
      </section>

      <section className="location-panel">
        <div>
          <span className="file-label">НАВИГАЦИЯ И ПРОВЕРКА ПОЗИЦИИ</span>
          <h3>Найдите безопасную точку сканирования</h3>
          <p>Проверьте расстояние на устройстве. Эта навигационная проверка не подтверждает действие на сервере.</p>
        </div>
        <div className="location-actions">
          <button
            className="route-button"
            onClick={() =>
              openRouteInNavigator(
                content.latitude,
                content.longitude,
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
            {isCheckingLocation
              ? 'ОПРЕДЕЛЯЕМ ПОЗИЦИЮ...'
              : 'ПРОВЕРИТЬ ПОЗИЦИЮ'}
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
              <strong>НАВИГАЦИОННАЯ ПРОВЕРКА НЕ ВЫПОЛНЕНА</strong>
              <p>Проверьте расстояние до точки на устройстве. Серверная geo-проверка появится в отдельном runtime API.</p>
            </div>
          </>
        ) : canStartArSearch ? (
          <>
            <span className="location-status-icon">✓</span>
            <div>
              <strong>ТОЧКА ДОСТУПНА ДЛЯ ЛОКАЛЬНОЙ НАВИГАЦИИ</strong>
              <p>Расстояние на устройстве: {distanceToSegment} м. Оно не является серверным LocationProof.</p>
            </div>
          </>
        ) : (
          <>
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>ТОЧКА СКАНИРОВАНИЯ СЛИШКОМ ДАЛЕКО</strong>
              <p>
                Расстояние: {distanceToSegment} м. Подойдите ближе чем на{' '}
                {content.safeScanRadiusMeters} м.
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
      ) : confirmedAward ? (
        <section className="mission-success-card">
          <span className="file-label">ПАКЕТ ВОССТАНОВЛЕН</span>
          <div className="mission-success-symbol">✓</div>
          <h3>СЕГМЕНТ СТАБИЛИЗИРОВАН</h3>
          <p>Прогресс и награды подтверждены сервером.</p>
          <div className="mission-reward-grid">
            <div>
              <span>ПОЛУЧЕНО</span>
              <strong>{confirmedAward}</strong>
            </div>
          </div>
        </section>
      ) : isCodeRepairOpen ? (
        <section className="code-repair-panel">
          <span className="file-label">
            {repair.label ?? 'CODE REPAIR'}
          </span>
          <h3>Восстановите повреждённую строку</h3>
          {repair.instruction && (
            <p>{repair.instruction}</p>
          )}
          <div className="code-window">
            <span className="code-line-number">
              {repair.lineNumber ?? '—'}
            </span>
            <code>
              {repairSequence.length > 0 ? (
                repairSequence.map((block, index) => (
                  <span key={`${block}-${index}`}>{block}</span>
                ))
              ) : (
                <span className="code-placeholder">
                  {repair.placeholder ?? 'Выберите блоки ниже'}
                </span>
              )}
            </code>
          </div>
          <div className="repair-blocks">
            {repair.blocks.map((block) => (
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
              disabled={
                repairSequence.length !== repair.maxBlocks
              }
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
              {content.objectType === 'root_logo' ? (
                <div
                  style={{
                    width: '100%',
                    height: '220px',
                    overflow: 'visible',
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                  }}
                >
                  <Game3DScene />
                </div>
              ) : (
                <>
                  {virtualQrRevealed ? (
                    <span className="virtual-qr">▦</span>
                  ) : (
                    '▦'
                  )}
                </>
              )}
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
              <p>Зафиксируйте грань виртуального куба.</p>
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
              <p>Запустите визуальное извлечение QR-маркера.</p>
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
              <p>Откройте проверку кодовой структуры. Результат и награды подтверждает сервер.</p>
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

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        ← ВЕРНУТЬСЯ В КОНТУР
      </button>
    </section>
  )
}
