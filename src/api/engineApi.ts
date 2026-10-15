export type EngineMissionStatus =
  | 'locked'
  | 'available'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
  | 'expired'

export type EngineMissionSpawn = {
  latitude: number
  longitude: number
  searchRadiusMeters: number
  zoneRadiusMeters: number | null
  arObjectId: string | null
  generatedFromLat: number | null
  generatedFromLng: number | null
  generatedAt: string
}

export type EngineMission = {
  id: string
  slug: string
  missionType: 'text_answer' | 'code_repair' | string
  missionLayer: string
  title: string
  description: string
  content: Record<string, unknown>
  geoZoneId: string | null
  arObjectId: string | null
  spawn: EngineMissionSpawn | null
  status: EngineMissionStatus
  attemptCount: number
  startedAt: string | null
  completedAt: string | null
  executionTimeLimitSeconds: number | null
  deadlineAt: string | null
  availableAgainAt: string | null
}

export type EngineAcceptMissionResponse = {
  accepted: boolean
  mission: {
    id: string
    slug: string
    title: string
    missionType: string
  }
  spawn: EngineMissionSpawn
  status: string
  startedAt: string | null
}
export type EngineMissionQrPayload = {
  missionId: string
  payload: string
  hmac: string
  expiresAt: string
  ttlSeconds: number
}

export type EngineMissionScanResult = {
  accepted: boolean
  missionId: string
  scannedAt: string
  miniGame: {
    missionType: string
    content: Record<string, unknown>
  }
}

export type EngineInventoryItem = {
  id: string
  slug: string
  code: string
  title: string
  description: string
  symbol: string
  category: string
  rarity: string
  quantity: number
}

export type EngineStoryNode = {
  id: string
  slug: string
  title: string
  body: string
  presentationType: string
  content: Record<string, unknown>
}

export type EngineSegmentLink = {
  id: string
  slug: string
  title: string
}

export type EngineSegment = {
  id: string
  slug: string
  title: string
  description: string
  content: Record<string, unknown>
  status: string
  sortOrder: number
  linkedMissions: EngineSegmentLink[]
}

export type EngineBootstrap = {
  player: {
    id: string
    displayName: string
    rootBalance: number
  }
  wallet: {
    currency: string
    availableBalance: number
    lockedBalance: number
  }
  missions: EngineMission[]
  segments: EngineSegment[]
  inventory: EngineInventoryItem[]
  storyNodes: EngineStoryNode[]
}

export type MissionSubmission = {
  accepted: boolean
  alreadyCompleted: boolean
  missionId: string
  missionStatus: EngineMissionStatus
  message?: string
  awarded: {
    root: number
    items: Array<{
      id: string
      code: string
      title: string
      quantity: number
    }>
    storyNodeIds: string[]
  }
  bootstrap: EngineBootstrap
}

export type TelegramAuthResult = {
  authenticated: true
  player: {
    id: string
    displayName: string | null
    telegramUsername: string | null
  }
}

export type FallbackOfferItem = {
  id: string
  slug: string
  code: string
  title: string
  symbol: string | null
  category: string
  rarity: string
}

export type FallbackOffer = {
  missionId: string
  entitlementId: string
  missionSlug: string
  missionTitle: string
  offerId: string
  priceRoot: number
  quotaLimit: number
  consumedCount: number
  remainingQuota: number
  status: 'available' | 'disabled' | 'exhausted'
  item: FallbackOfferItem | null
}

export type FallbackPurchaseResult = {
  purchased: boolean
  entitlementId: string
  consumedCount: number
  remainingQuota: number
  status: string
  priceRoot: number
  rootBalance: number
  item: FallbackOfferItem | null
}

type SubmitPayload = {
  answer?: string
  sequence?: string[]
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail ?? `HTTP ${response.status}`
  } catch {
    return `HTTP ${response.status}`
  }
}

async function apiFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  return fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: 'same-origin',
  })
}

export async function authenticateTelegram(
  initData: string,
): Promise<TelegramAuthResult> {
  const response = await apiFetch('/api/v1/auth/telegram', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ init_data: initData }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<TelegramAuthResult>
}

export async function getEngineBootstrap(): Promise<EngineBootstrap> {
  const response = await apiFetch('/api/v1/engine/bootstrap')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineBootstrap>
}

export async function submitEngineMission(
  missionId: string,
  payload: SubmitPayload,
): Promise<MissionSubmission> {
  const response = await apiFetch(
    `/api/v1/engine/missions/${missionId}/submit`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<MissionSubmission>
}

export type AcceptMissionPayload = {
  latitude: number
  longitude: number
  accuracy?: number | null
}

export async function acceptEngineMission(
  missionId: string,
  payload: AcceptMissionPayload,
): Promise<EngineAcceptMissionResponse> {
  const response = await apiFetch(
    `/api/v1/engine/missions/${missionId}/accept`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineAcceptMissionResponse>
}

export type EngineExpireMissionResponse = {
  expired: boolean
  status: string
  availableAgainAt: string | null
}

export async function expireEngineMission(
  missionId: string,
): Promise<EngineExpireMissionResponse> {
  const response = await apiFetch(
    `/api/v1/engine/missions/${missionId}/expire`,
    { method: 'POST' },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineExpireMissionResponse>
}

/**
 * @deprecated Sprint 8.13: не используется в solo-flow.
 * Контент мини-игры берётся из mission.content (bootstrap).
 * Оставлено для team-flow / будущего применения.
 */
export async function getMissionQrPayload(
  missionId: string,
): Promise<EngineMissionQrPayload> {
  const response = await apiFetch(
    `/api/v1/engine/missions/${missionId}/qr-payload`,
    { method: 'GET' },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineMissionQrPayload>
}

/**
 * @deprecated Sprint 8.13: не используется в solo-flow.
 * Контент мини-игры берётся из mission.content (bootstrap).
 * Оставлено для team-flow / будущего применения.
 */
export async function scanMissionQr(
  missionId: string,
  payloadAndHmac: string,
): Promise<EngineMissionScanResult> {
  const response = await apiFetch(
    `/api/v1/engine/missions/${missionId}/scan-qr`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ payload_and_hmac: payloadAndHmac }),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineMissionScanResult>
}

export async function listFallbackOffers(): Promise<FallbackOffer[]> {
  const response = await apiFetch('/api/v1/engine/fallback-offers')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { offers: FallbackOffer[] }
  return body.offers
}

export async function purchaseFallbackOffer(
  entitlementId: string,
): Promise<FallbackPurchaseResult> {
  const response = await apiFetch(
    `/api/v1/engine/fallback-offers/${encodeURIComponent(
      entitlementId,
    )}/purchases`,
    {
      method: 'POST',
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<FallbackPurchaseResult>
}
