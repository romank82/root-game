import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type {
  EngineMission,
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
import QuantumShield from '../game/QuantumShield'

type MissionContent = {
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

function parseMissionContent(
  mission: EngineMission,
): MissionContent | null {
  const content = asRecord(mission.content)
  if (!content) {
    return null
  }
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

function formatAwarded(response: MissionSubmission, t: TFunction): string {
  const parts: string[] = []

  if (response.awarded.root > 0) {
    parts.push(`${response.awarded.root} ROOT`)
  }

  for (const item of response.awarded.items) {
    parts.push(`${item.title} ×${item.quantity}`)
  }

  return parts.length > 0
    ? parts.join(' · ')
    : t('scanner:ar.noAwards')
}

export function ScannerScreen({
  missions,
  onScreenChange,
  onSubmitMission,
  geoPosition,
  geoError,
  onExpireMission,
}: ScannerScreenProps) {
  const { t } = useTranslation(['scanner', 'common'])
  const [distanceToScanPoint, setDistanceToScanPoint] = useState<number | null>(null)
  const [isCheckingLocation, setIsCheckingLocation] = useState(false)
  const [locationError, setLocationError] = useState('')
  const [arSessionStarted, setArSessionStarted] = useState(false)
  const [isScanFaceLocked, setIsScanFaceLocked] = useState(false)
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
      parseCodeRepairContent(mission) !== null,
  ) ?? null

  const missionContent = activeMission
    ? parseMissionContent(activeMission)
    : null

  const codeRepairContent = activeMission
    ? parseCodeRepairContent(activeMission)
    : null

  if (spawnMission) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">{t('scanner:header.activeMissionEyebrow')}</p>

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
              <strong>{geoError ? t('common:gps.unavailableTitle') : t('common:gps.locatingTitle')}</strong>
              <p>{geoError ?? t('scanner:gps.permissionHint')}</p>
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
                  {layer === 'solo' ? t('scanner:header.layers.solo') : layer === 'team' ? t('scanner:header.layers.team') : t('scanner:header.layers.story')}
                </button>
              ))}
            </div>

            {spawnMission.deadlineAt && (
              <MissionTimer
                deadlineAt={spawnMission.deadlineAt}
                label={t('scanner:header.timerLabel')}
                onClick={() => void onExpireMission(spawnMission.id)}
              />
            )}

            <EchoRadar
              playerLat={geoPosition.lat}
              playerLng={geoPosition.lng}
              playerAccuracy={geoPosition.accuracy}
              targetLat={spawnMission.spawn!.latitude}
              targetLng={spawnMission.spawn!.longitude}
              hint={t('scanner:navigation.radarHint')}
              color={MISSION_LAYER_COLORS[selectedLayer]}
            />
            <button
              className="ar-start-button"
              onClick={() => onScreenChange('camera-test')}
            >
              {t('scanner:navigation.openCamera')}
            </button>
          </>
        )}

        <button
          className="back-button"
          onClick={() => onScreenChange('terminal')}
        >
          {t('common:backToContour')}
        </button>
      </section>
    )
  }

  if (!activeMission || !missionContent || !codeRepairContent) {
    return (
      <section className="segment-screen">
        <p className="eyebrow">{t('scanner:errors.cmsUnavailableEyebrow')}</p>
        <section className="location-status">
          <span className="location-status-icon">⌖</span>
          <div>
            <strong>{t('scanner:errors.noScanPointTitle')}</strong>
            <p>{t('scanner:errors.noScanPointBody')}</p>
          </div>
        </section>
        <button className="back-button" onClick={() => onScreenChange('terminal')}>
          {t('common:backToContour')}
        </button>
      </section>
    )
  }

  // The safe empty-state return above guarantees these CMS values exist here.
  // Local constants preserve that narrowing inside browser/API callbacks.
  const mission = activeMission
  const content = missionContent
  const repair = codeRepairContent

  const canStartArSearch =
    distanceToScanPoint !== null &&
    distanceToScanPoint <= content.safeScanRadiusMeters

  function checkPlayerLocation() {
    if (!navigator.geolocation) {
      setLocationError(t('common:gps.notSupported'))
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
        setDistanceToScanPoint(distance)
        setIsCheckingLocation(false)
      },
      (error) => {
        setIsCheckingLocation(false)
        if (error.code === error.PERMISSION_DENIED) {
          setLocationError(
            t('common:gps.permissionDenied'),
          )
        } else if (error.code === error.POSITION_UNAVAILABLE) {
          setLocationError(
            t('common:gps.positionUnavailable'),
          )
        } else {
          setLocationError(
            t('common:gps.positionError'),
          )
        }
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    )
  }

  function startArSearch() {
    setArSessionStarted(true)
    setIsScanFaceLocked(false)
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
      setRepairError(t('scanner:repair.serverUnavailable'))
      return
    }

    if (!response.accepted) {
      setRepairError(
        response.message ??
          repair.wrongAnswerText ??
          t('scanner:repair.structureBroken'),
      )
      return
    }

    setRepairError('')
    setConfirmedAward(formatAwarded(response, t))
  }

  return (
    <section className="segment-screen">
      <p className="eyebrow">
        {t('scanner:header.activeMissionEyebrow')}
      </p>

      <div className="segment-heading">
        <div>
          <h2>{mission.title}</h2>
          <p>{mission.description}</p>
        </div>
        <div className="segment-code">
          <span>{t('scanner:params.codeLabel')}</span>
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
          <span className="file-label">{t('scanner:params.title')}</span>
          <dl className="segment-stats">
            <div>
              <dt>{t('scanner:params.searchRadius')}</dt>
              <dd>{t('scanner:params.unitMeters', { value: content.searchRadiusMeters })}</dd>
            </div>
            <div>
              <dt>{t('scanner:params.safeScanPoint')}</dt>
              <dd>{t('scanner:params.unitMeters', { value: content.safeScanRadiusMeters })}</dd>
            </div>
          </dl>
          {repair.rewardPreviewText && (
            <p className="segment-item-reward">
              {t('scanner:params.rewardPreview')} {repair.rewardPreviewText}
            </p>
          )}
        </div>
      </section>

      <section className="location-panel">
        <div>
          <span className="file-label">{t('scanner:navigation.title')}</span>
          <h3>{t('scanner:navigation.findPoint')}</h3>
          <p>{t('scanner:navigation.checkHint')}</p>
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
            {t('scanner:navigation.openRoute')}
          </button>
          <button
            className="location-button"
            onClick={checkPlayerLocation}
            disabled={isCheckingLocation}
          >
            {isCheckingLocation
              ? t('scanner:navigation.locating')
              : t('scanner:navigation.checkPosition')}
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
              <strong>{t('common:gps.errorTitle')}</strong>
              <p>{locationError}</p>
            </div>
          </>
        ) : distanceToScanPoint === null ? (
          <>
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>{t('scanner:navigation.notCheckedTitle')}</strong>
              <p>{t('scanner:navigation.notCheckedBody')}</p>
            </div>
          </>
        ) : canStartArSearch ? (
          <>
            <span className="location-status-icon">✓</span>
            <div>
              <strong>{t('scanner:navigation.pointAvailableTitle')}</strong>
              <p>{t('scanner:navigation.pointAvailableBody', { distance: distanceToScanPoint })}</p>
            </div>
          </>
        ) : (
          <>
            <span className="location-status-icon">⌖</span>
            <div>
              <strong>{t('scanner:navigation.tooFarTitle')}</strong>
              <p>
                {t('scanner:navigation.tooFarBody', {
                  distance: distanceToScanPoint,
                  radius: content.safeScanRadiusMeters,
                })}
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
          {canStartArSearch ? t('scanner:ar.start') : t('scanner:ar.blocked')}
        </button>
      ) : confirmedAward ? (
        <section className="mission-success-card">
          <span className="file-label">{t('scanner:ar.successLabel')}</span>
          <div className="mission-success-symbol">✓</div>
          <h3>{t('scanner:ar.successTitle')}</h3>
          <p>{t('scanner:ar.successBody')}</p>
          <div className="mission-reward-grid">
            <div>
              <span>{t('scanner:ar.receivedLabel')}</span>
              <strong>{confirmedAward}</strong>
            </div>
          </div>
        </section>
      ) : isCodeRepairOpen ? (
        <section className="code-repair-panel">
          <span className="file-label">
            {repair.label ?? t('scanner:repair.defaultLabel')}
          </span>
          <h3>{t('scanner:repair.title')}</h3>
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
                  {repair.placeholder ?? t('scanner:repair.placeholderFallback')}
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
              {t('scanner:repair.clear')}
            </button>
            <button
              className="repair-submit-button"
              onClick={submitCodeRepair}
              disabled={
                repairSequence.length !== repair.maxBlocks
              }
            >
              {t('scanner:repair.submit')}
            </button>
          </div>
        </section>
      ) : (
        <section className="ar-placeholder">
          <span className="file-label">{t('scanner:ar.sessionInitialized')}</span>
          <div
            className={`ar-placeholder-frame ${
              isScanFaceLocked ? 'face-locked' : ''
            }`}
          >
            {content.objectType && (
              <div
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  background: 'red',
                  color: 'white',
                  padding: 4,
                  zIndex: 9999,
                  fontSize: 10,
                }}
              >
                objectType: {content.objectType}
              </div>
            )}
            <div className="ar-cube">
              {content.objectType === 'root_logo' ? (
                <div className="ar-3d-scene">
                  <Game3DScene />
                </div>
              ) : content.objectType === 'quantum_shield' ? (
                <div className="ar-3d-scene">
                  <QuantumShield />
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
            {isScanFaceLocked && (
              <span className="face-lock-status">{t('scanner:ar.faceLocked')}</span>
            )}
          </div>
          {!isScanFaceLocked ? (
            <>
              <h3>{t('scanner:ar.aimTitle')}</h3>
              <p>{t('scanner:ar.aimBody')}</p>
              <button
                className="ar-action-button"
                onClick={() => setIsScanFaceLocked(true)}
              >
                {t('scanner:ar.lockFace')}
              </button>
            </>
          ) : !virtualQrRevealed ? (
            <>
              <h3>{t('scanner:ar.syncedTitle')}</h3>
              <p>{t('scanner:ar.syncedBody')}</p>
              <button
                className="ar-action-button"
                onClick={() => setVirtualQrRevealed(true)}
              >
                {t('scanner:ar.revealQr')}
              </button>
            </>
          ) : (
            <>
              <h3>{t('scanner:ar.qrRevealedTitle')}</h3>
              <p>{t('scanner:ar.qrRevealedBody')}</p>
              <button
                className="ar-action-button"
                onClick={() => setIsCodeRepairOpen(true)}
              >
                {t('scanner:ar.extractData')}
              </button>
            </>
          )}
        </section>
      )}

      <button
        className="back-button"
        onClick={() => onScreenChange('terminal')}
      >
        {t('common:backToContour')}
      </button>
    </section>
  )
}
