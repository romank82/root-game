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
  // Командные миссии (7.1): X/Y-счётчик состава в карточке активной
  // миссии. sessionMemberCount — активные участники командной сессии игрока
  // на эту миссию; maxMembers — лимит состава (validationConfig.team.maxMembers
  // на бэкенде). Для индивидуальных миссий — 0 / null; отсутствуют у старых
  // ответов → опциональны.
  sessionMemberCount?: number
  maxMembers?: number
  // sessionStatus — статус активной командной сессии игрока на эту миссию
  // ('collecting' | 'ready_to_start' | 'active'); sessionCreatedAt — время её
  // создания (клиент строит по нему окно отказа createdAt + 3 мин, как solo
  // по startedAt). Для индивидуальных миссий и без сессии — null.
  sessionStatus?: string | null
  sessionCreatedAt?: string | null
  // Sprint 8.x-4-refuse-fix: id активной командной сессии игрока на эту миссию
  // (team-session-...). Нужен для leave_team_session (эндпоинт ждёт sessionId,
  // а не mission.id). Для индивидуальных миссий и без сессии — null.
  sessionId?: string | null
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

// ============================================================================
// Teams (этап 6.4) и командные сессии (этап 7.1) — player-facing endpoints.
// Контракты соответствуют сериализаторам бэкенда: _serialize_team
// (teams_service.py) и _serialize_team_session (team_missions_service.py):
// поля team — camelCase, у сессии часть полей snake_case (mission_id,
// started_at) — это реальный контракт сервера.
// ============================================================================

export type EngineTeamStatus = 'active' | 'disbanded'
export type EngineTeamJoinPolicy = 'open' | 'by_request' | 'invite_only'
export type EngineTeamMemberRole = 'leader' | 'member'

export type EngineTeam = {
  id: string
  name: string
  description: string | null
  emblemUrl: string | null
  status: EngineTeamStatus
  joinPolicy: EngineTeamJoinPolicy
  maxMembers: number | null
  memberCount: number
  leader: {
    id: string
    displayName: string | null
  }
  members: Array<{
    id: string
    role: EngineTeamMemberRole
    joinedAt: string | null
  }>
}

export type EngineTeamSessionStatus =
  | 'collecting'
  | 'ready_to_start'
  | 'active'
  | 'succeeded'
  | 'failed'
  | 'expired'
  | 'cancelled_before_start'

export type EngineTeamSessionMyStatus =
  | 'joined'
  | 'ready'
  | 'left'
  | 'removed'
  | 'settled'

// Sprint 8.x-3: статус текущей cipher-волны командной мини-игры (тот же набор
// значений отдаёт бэкенд и в EngineTeamSession.waveStatus, и в
// EngineTeamWaveSubmitResult.waveStatus).
export type EngineTeamWaveStatus = 'playing' | 'passed' | 'failed'

export type EngineTeamSession = {
  id: string
  mission_id: string
  missionTitle: string | null
  status: EngineTeamSessionStatus
  started_at: string | null
  createdAt: string | null
  memberCount: number
  myStatus: EngineTeamSessionMyStatus | null
  myReadyAt: string | null
  // Sprint 8.x-3: игровое состояние волн командной мини-игры для
  // TeamSessionScreen. Бэкенд отдаёт всегда (поля с server_default в БД,
  // миграция c8a4e2b6f9d3) → поля required.
  currentWave: number
  maxWaves: number
  waveStatus: EngineTeamWaveStatus
  wavePlayedCount: number
  myWavePlayed: boolean
  // cipher-сессия текущей волны для мини-игры (барабаны + правильный код +
  // лимит времени, ключи в camelCase — стиль фронта). null после финализации.
  cipherSession: {
    correctCode: string[]
    drums: string[][]
    timeLimitSeconds: number | null
  } | null
}

export type EngineTeamAwarded = {
  root: number
  items: Array<{
    id: string
    code: string
    title: string
    quantity: number
  }>
  storyNodeIds: string[]
}

// Sprint 8.x-2b: ответ POST submit-wave. Успех и провал волны (неверная
// комбинация) приходят в одной форме. message — только при accepted:false;
// missionRunId/awarded — только при accepted:true.
export type EngineTeamWaveSubmitResult = {
  sessionId: string
  waveStatus: EngineTeamWaveStatus
  currentWave: number
  maxWaves: number
  sessionStatus: EngineTeamSessionStatus
  accepted: boolean
  message?: string
  missionRunId?: string
  awarded?: EngineTeamAwarded
}

export type CreateTeamPayload = {
  name: string
  description?: string | null
  emblem_url?: string | null
  join_policy?: EngineTeamJoinPolicy
  max_members?: number | null
}

export async function createTeam(
  name: string,
  description?: string | null,
  joinPolicy?: EngineTeamJoinPolicy,
  maxMembers?: number | null,
): Promise<EngineTeam> {
  const response = await apiFetch('/api/v1/engine/teams', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    // Контракт бэкенда (TeamCreatePayload): поля snake_case.
    body: JSON.stringify({
      name,
      description: description ?? null,
      emblem_url: null,
      join_policy: joinPolicy ?? 'by_request',
      max_members: maxMembers ?? null,
    }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeam>
}

export async function getMyTeam(): Promise<EngineTeam | null> {
  const response = await apiFetch('/api/v1/engine/teams/me')

  // Бэкенд отвечает 404 «Вы не состоите в команде.» — трактуем как null,
  // чтобы вызывающий код отличал «нет команды» от настоящей ошибки.
  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeam>
}

export async function getTeam(teamId: string): Promise<EngineTeam> {
  const response = await apiFetch(`/api/v1/engine/teams/${teamId}`)

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeam>
}

export async function joinTeam(teamId: string): Promise<EngineTeam> {
  const response = await apiFetch(`/api/v1/engine/teams/${teamId}/join`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeam>
}


export async function leaveTeam(teamId: string): Promise<void> {
  const response = await apiFetch(`/api/v1/engine/teams/${teamId}/leave`, {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function disbandTeam(teamId: string): Promise<void> {
  const response = await apiFetch(`/api/v1/engine/teams/${teamId}/disband`, {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function getTeamSessions(): Promise<{
  sessions: EngineTeamSession[]
}> {
  const response = await apiFetch(
    '/api/v1/engine/team-missions/sessions/me',
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<{ sessions: EngineTeamSession[] }>
}

// Sprint 8.x-4-final-status-2: последняя терминальная сессия игрока
// (succeeded/failed) + его награды. Контракт бэкенда:
// GET /api/v1/engine/team-missions/sessions/last → {"session": {...} | null}.
// session — EngineTeamSession + awarded (награды ИГРОКА из его
// awarded_snapshot: root/items/storyNodeIds; null, если наград не было).
// Вызывается ОДИН раз при sessionEnded (поллинг вернул []), не каждые 3 сек.
export type EngineTeamLastSessionResult = {
  session:
    | (EngineTeamSession & { awarded?: EngineTeamAwarded | null })
    | null
}

export async function getLastTeamSession(): Promise<EngineTeamLastSessionResult> {
  const response = await apiFetch(
    '/api/v1/engine/team-missions/sessions/last',
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamLastSessionResult>
}

export async function createTeamSession(
  missionId: string,
): Promise<EngineTeamSession> {
  const response = await apiFetch('/api/v1/engine/team-missions/sessions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    // Контракт бэкенда (TeamSessionCreatePayload): mission_id (snake_case).
    body: JSON.stringify({ mission_id: missionId }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamSession>
}

export async function markTeamSessionReady(
  sessionId: string,
): Promise<EngineTeamSession> {
  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/ready`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamSession>
}

export async function joinTeamSession(
  sessionId: string,
): Promise<EngineTeamSession> {
  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/join`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamSession>
}

export async function leaveTeamSession(
  sessionId: string,
): Promise<{ left: boolean; refunded: boolean }> {
  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/leave`,
    { method: 'POST' },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<{ left: boolean; refunded: boolean }>
}

// Sprint 8.x-2b: ответ игрока на cipher-волну командной мини-игры. Контракт
// бэкенда: POST /api/v1/engine/team-missions/sessions/{sessionId}/submit-wave,
// body { sequence }. Вызывается только в TeamSessionScreen (шаг 8.x-4b-2).
export async function submitTeamWave(
  sessionId: string,
  sequence: string[],
): Promise<EngineTeamWaveSubmitResult> {
  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/submit-wave`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      // Контракт бэкенда (submit_wave_route): ключ "sequence" (camelCase).
      body: JSON.stringify({ sequence }),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamWaveSubmitResult>
}

// Sprint 8.x-4-location-ui: отметка гео-присутствия игрока в командной сессии.
// Контракт бэкенда: POST /api/v1/engine/team-missions/sessions/{sessionId}/location,
// body { latitude, longitude, accuracy_meters } — Verified LocationProof
// (свежий proof нужен для активации сессии при всех готовых участниках).
export type EngineTeamLocationSubmitResult = {
  sessionId: string
  zoneId: string
  verified: boolean
  expiresAt: string
}

export async function submitTeamLocation(
  sessionId: string,
  latitude: number,
  longitude: number,
  accuracyMeters: number,
): Promise<EngineTeamLocationSubmitResult> {
  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/location`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        latitude,
        longitude,
        accuracy_meters: accuracyMeters,
      }),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamLocationSubmitResult>
}

// Sprint 6.6-a/6.6-b: чат КОМАНДНОЙ СЕССИИ (только внутри TeamSession — не в
// Team). Контракт бэкенда (app/team_session_chat_service.py):
//   GET  .../sessions/{sessionId}/messages?limit=50&before=<ISO>  →
//        { messages: [{id, playerId, displayName, text, createdAt}],
//          hasMore, limit }
//   POST .../sessions/{sessionId}/messages  body { text } → сообщение
// Доступ: только участники сессии (joined/ready) и только пока сессия в
// collecting/ready_to_start/active; после финала бэкенд отвечает 409.
// Выдача — новые сверху; before — createdAt самого старого загруженного.
export type EngineTeamMessage = {
  id: string
  playerId: string
  displayName: string | null
  text: string
  createdAt: string
}

export type EngineTeamMessagesResult = {
  messages: EngineTeamMessage[]
  hasMore: boolean
  limit: number
}

export async function getTeamSessionMessages(
  sessionId: string,
  limit = 50,
  before: string | null = null,
): Promise<EngineTeamMessagesResult> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (before) params.set('before', before)

  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/messages?${params.toString()}`,
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamMessagesResult>
}

export async function sendTeamSessionMessage(
  sessionId: string,
  text: string,
): Promise<EngineTeamMessage> {
  const response = await apiFetch(
    `/api/v1/engine/team-missions/sessions/${sessionId}/messages`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      // Контракт бэкенда (send_session_message_route): ключ "text".
      body: JSON.stringify({ text }),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineTeamMessage>
}

