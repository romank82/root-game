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

export type EngineReward = {
  type: string // 'currency' | 'item' | 'story_node'
  amount: number | null
  itemId: string | null
  // Sprint 8.x: человекочитаемый код предмета (Item.code, например
  // TEST_KEY_003) — его же показывает магазин; null у не-item наград
  // и если предмет не найден. В UI предпочтителен над itemId.
  itemCode: string | null
  storyNodeId: string | null
}

export type EngineMission = {
  id: string
  slug: string
  missionType: 'text_answer' | 'code_repair' | string
  missionLayer: string
  title: string
  description: string
  content: Record<string, unknown>
  // Sprint 8.17 (шаг 6-7): сгенерированная backend-сессия cipher-игры.
  // Барабаны и правильный код создаются при accept и пересоздаются при
  // каждом промахе. У старых миссий отсутствует → фронт использует
  // content.ui как fallback до миграции (шаг 8.17.10).
  cipherSession?: {
    drums: string[][]
    correctCode: string[]
    // 8.17-timer: лимит времени на попытку cipher (null = без лимита).
    timeLimitSeconds: number | null
  } | null
  geoZoneId: string | null
  arObjectId: string | null
  spawn: EngineMissionSpawn | null
  status: EngineMissionStatus
  attemptCount: number
  maxAttempts: number | null
  startedAt: string | null
  completedAt: string | null
  executionTimeLimitSeconds: number | null
  deadlineAt: string | null
  availableAgainAt: string | null
  // Sprint 8.x: публичные данные published runtime policy (цена входа в atomic
  // ROOT и требуемые ключи). Отдаются движком в bootstrap для показа в карточке
  // миссии ДО accept; у старых ответов отсутствуют → поля опциональны.
  entryRoot?: number | null
  requiredItems?: {
    itemId: string
    // Sprint 8.x: человекочитаемый код ключа (Item.code, например
    // TEST_KEY_003). null, если предмет не найден; в UI предпочтителен над itemId.
    itemCode: string | null
    quantity: number
  }[]
  // Sprint 8.x: публичные награды миссии из MissionReward (currency ROOT /
  // item / story_node) для блока «Возможные награды» в карточке.
  rewards?: EngineReward[]
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
  // 10.4-j-0: баланс газа — строка (дробный Numeric(18,4) с бэка).
  gasBalance: string
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

export type ShopCatalogItem = {
  itemId: string
  code: string
  title: string
  symbol: string | null
  category: string
  rarity: string
  priceRoot: number
  owned: number
}

export async function listShopItems(): Promise<{ items: ShopCatalogItem[] }> {
  const response = await apiFetch('/api/v1/engine/shop/items')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<{ items: ShopCatalogItem[] }>
}

export type ShopPurchaseResult = {
  purchased: boolean
  itemId: string
  code: string
  title: string
  priceRoot: number
  rootBalance: number
  owned: number
}

export async function purchaseShopItem(
  itemId: string,
): Promise<ShopPurchaseResult> {
  const response = await apiFetch(
    `/api/v1/engine/shop/items/${encodeURIComponent(itemId)}/purchases`,
    {
      method: 'POST',
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<ShopPurchaseResult>
}

export type MyProfile = {
  id: string
  nickname: string | null
  country: string | null
  country_source: string | null
  gender: string | null
  age: number | null
}

export type MyProfilePayload = {
  country?: string | null
  gender?: string | null
  age?: number | null
}

export async function getMyProfile(): Promise<{ player: MyProfile }> {
  const response = await apiFetch('/api/v1/engine/me/profile')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<{ player: MyProfile }>
}

export async function saveMyProfile(
  payload: MyProfilePayload,
): Promise<{ player: MyProfile }> {
  const response = await apiFetch('/api/v1/engine/me/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<{ player: MyProfile }>
}
export type SearchPlayerHit = {
  id: string
  nickname: string | null
  country: string | null
}

export type SearchPlayersResponse = {
  players: SearchPlayerHit[]
  total: number
  limit: number
}

// 10.0.1: игровой поиск игроков по нику (для переводов 10.1+).
// q >= 3 символа (иначе 422), rate limit 10/min, кука уходит сама.
export async function searchPlayers(
  query: string,
  limit = 20,
): Promise<SearchPlayersResponse> {
  const params = new URLSearchParams()
  params.set('q', query)
  params.set('limit', String(limit))
  const response = await apiFetch(
    `/api/v1/players/search?${params.toString()}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<SearchPlayersResponse>
}

// 10.1+: перевод ROOT. Тело — snake_case (1:1 с бэком:
// TransferPayload в main.py). Ответ — camelCase (как отдаёт
// transfer_service.py).
export type TransferPayload = {
  to_player_id: string
  amount: number
  request_id: string
}

export type TransferResponse = {
  transferId: string
  fromPlayerId: string
  toPlayerId: string
  amount: number
  status: string
  fromBalance: number
  toBalance: number
}

// 10.1+: перевод ROOT другому игроку. request_id — клиентский
// (uuid) для идемпотентности: повторный запрос с тем же request_id
// возвращает первый результат без второго перевода.
export async function transferRoot(
  payload: TransferPayload,
): Promise<TransferResponse> {
  const response = await apiFetch('/api/v1/players/transfer', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response.json() as Promise<TransferResponse>
}

// 10.4-j-0/j-1: инвойс Stars на покупку газа (POST /api/v1/engine/gas/invoice).
export type GasInvoiceResponse = {
  invoiceLink: string
  referenceId: string
  gasAmount: number
  amountStars: number
}

export async function createGasInvoice(
  gasAmount: number,
): Promise<GasInvoiceResponse> {
  const response = await apiFetch('/api/v1/engine/gas/invoice', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ gas_amount: gasAmount }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<GasInvoiceResponse>
}

// 10.4-fix-b: инвойс Stars в чат с ботом (POST /api/v1/engine/gas/invoice/send).
// Обход бага Android (WebView openInvoice не доставляет pre_checkout_query).
export type GasInvoiceSendResponse = {
  referenceId: string
  gasAmount: number
  amountStars: number
  chatId: string
}

export async function sendGasInvoice(
  gasAmount: number,
): Promise<GasInvoiceSendResponse> {
  const response = await apiFetch('/api/v1/engine/gas/invoice/send', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ gas_amount: gasAmount }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<GasInvoiceSendResponse>
}

// 11.0-a/b: TON-кошелёк игрока (GET/POST/DELETE /api/v1/me/ton-wallet).
export type MyTonWallet = {
  address: string | null
  status: string | null
}

export async function getMyTonWallet(): Promise<MyTonWallet> {
  const response = await apiFetch('/api/v1/me/ton-wallet')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<MyTonWallet>
}

export async function saveMyTonWallet(
  address: string,
): Promise<MyTonWallet> {
  const response = await apiFetch('/api/v1/me/ton-wallet', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ address }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<MyTonWallet>
}

export async function deleteMyTonWallet(): Promise<{ deleted: boolean }> {
  const response = await apiFetch('/api/v1/me/ton-wallet', {
    method: 'DELETE',
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<{ deleted: boolean }>
}

// 11.7-b: вывод ROOT → TON (POST/GET /api/v1/me/withdrawals) — создание
// заявки и список своих заявок. Поля — игровые, в статусе строки из
// бэкенд-контракта (pending/approved/rejected/processing/confirmed/failed).
export type PlayerWithdrawal = {
  withdrawalId: string
  amountRoot: number
  toAddress: string
  status: string
  tonTxHash: string | null
  reason: string | null
  createdAt: string | null
  updatedAt: string | null
}

export type WithdrawalsListResponse = {
  withdrawals: PlayerWithdrawal[]
  total: number
  limit: number
  offset: number
}

export type CreateWithdrawalResult = {
  withdrawalId: string
  amountRoot: number
  toAddress: string
  status: string
}

export async function createWithdrawal(
  amountRoot: number,
  toAddress: string,
): Promise<CreateWithdrawalResult> {
  const response = await apiFetch('/api/v1/me/withdrawals', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    // Контракт бэкенда (WithdrawalPayload): поля snake_case.
    body: JSON.stringify({ amount_root: amountRoot, to_address: toAddress }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<CreateWithdrawalResult>
}

export async function listMyWithdrawals(
  limit = 50,
  offset = 0,
): Promise<WithdrawalsListResponse> {
  const response = await apiFetch(
    `/api/v1/me/withdrawals?limit=${limit}&offset=${offset}`,
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<WithdrawalsListResponse>
}
