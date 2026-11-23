export type AdminRole = 'super_admin' | 'owner' | 'editor' | 'viewer' | 'admin'
export type AdminMissionStatus = 'draft' | 'published'

// Sprint Trans-3a: статус ручного перевода контента миссии (admin API Trans-2b-2).
export type MissionTranslationStatus = 'none' | 'partial' | 'complete'

export type AdminUser = {
  id: string
  username: string
  // Legacy display value. Do not use it as the source of authorization.
  role: AdminRole
  isSuperAdmin: boolean
}

export type AdminReward = {
  id?: string
  rewardType: 'currency' | 'item' | string
  amount: number | null
  itemId: string | null
  rewardValue: Record<string, unknown>
  sortOrder: number
}

export type AdminMission = {
  id: string
  seasonId: string
  geoZoneId: string | null
  arObjectId: string | null
  // Backend admin API пока не отдаёт это поле (шаг 8.17.5), поэтому поле optional.
  minigameProfileId?: string | null
  slug: string
  missionType: string
  missionCategory: string
  missionLayer: string
  executionTimeLimitSeconds: number | null
  reentryCooldownSeconds: number
  unlockAfterMissionId: string | null
  title: string
  description: string | null
  content: Record<string, unknown>
  validationConfig: Record<string, unknown>
  status: AdminMissionStatus
  // Sprint Trans-3a: пересчитанный сервером статус переводов. Поле optional,
  // чтобы старые ответы/моки без него оставались валидными.
  translationStatus?: MissionTranslationStatus
  sortOrder: number
  rewards: AdminReward[]
  createdAt: string | null
  updatedAt: string | null
}

export type AdminMissionPayload = {
  season_id: string
  geo_zone_id?: string | null
  ar_object_id?: string | null
  minigame_profile_id?: string | null
  slug?: string
  mission_type: string
  mission_category?: string
  mission_layer?: string
  execution_time_limit_seconds?: number | null
  reentry_cooldown_seconds?: number | null
  unlock_after_mission_id?: string | null
  title: string
  description?: string | null
  content?: Record<string, unknown>
  validation_config?: Record<string, unknown>
  sort_order?: number
  rewards?: Array<{
    reward_type: string
    amount?: number | null
    item_id?: string | null
    reward_value?: Record<string, unknown>
    sort_order?: number
  }>
}

// Sprint Trans-3a: переводы контента миссии (admin API Trans-2b-2).
// contentUi — словарь content.ui-ключей: строки текста + blocks (string[]) для
// code_repair; технические ключи (alphabet/combination/drumCount) не переводятся.
export type MissionTranslation = {
  title?: string
  description?: string
  contentUi?: Record<string, string | string[]>
}

export type MissionTranslations = Record<string, MissionTranslation>

export type MissionTranslationsResponse = {
  missionId: string
  translations: MissionTranslations
  translationStatus: MissionTranslationStatus
  supportedLanguages: string[]
  requiredContentUiKeys: string[]
}

export type MissionTranslationsPayload = {
  translations: MissionTranslations
}

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? ''

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail ?? `HTTP ${response.status}`
  } catch {
    return `HTTP ${response.status}`
  }
}

async function adminFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  return fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: 'same-origin',
  })
}

export async function getAdminMe(): Promise<AdminUser> {
  const response = await adminFetch('/api/v1/admin/auth/me')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as {
    authenticated: true
    admin: AdminUser
  }

  return body.admin
}

export async function loginAdmin(
  username: string,
  password: string,
): Promise<void> {
  const response = await adminFetch('/api/v1/admin/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function logoutAdmin(): Promise<void> {
  const response = await adminFetch('/api/v1/admin/auth/logout', {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }
}

export async function listAdminMissions(
  seasonId?: string,
): Promise<AdminMission[]> {
  const params = new URLSearchParams()
  if (seasonId) params.set('season_id', seasonId)
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/missions${query}`)

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { missions: AdminMission[] }
  return body.missions
}

export async function createAdminMission(
  payload: AdminMissionPayload,
): Promise<AdminMission> {
  const response = await adminFetch('/api/v1/admin/missions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { mission: AdminMission }
  return body.mission
}

export async function updateAdminMission(
  missionId: string,
  payload: Partial<AdminMissionPayload>,
): Promise<AdminMission> {
  const response = await adminFetch(`/api/v1/admin/missions/${missionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { mission: AdminMission }
  return body.mission
}

export async function publishAdminMission(
  missionId: string,
): Promise<AdminMission> {
  const response = await adminFetch(
    `/api/v1/admin/missions/${missionId}/publish`,
    { method: 'POST' },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { mission: AdminMission }
  return body.mission
}

export async function unpublishAdminMission(
  missionId: string,
): Promise<AdminMission> {
  const response = await adminFetch(
    `/api/v1/admin/missions/${missionId}/unpublish`,
    { method: 'POST' },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { mission: AdminMission }
  return body.mission
}

export async function getMissionTranslations(
  missionId: string,
): Promise<MissionTranslationsResponse> {
  const response = await adminFetch(
    `/api/v1/admin/missions/${missionId}/translations`,
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<MissionTranslationsResponse>
}

export async function putMissionTranslations(
  missionId: string,
  payload: MissionTranslationsPayload,
): Promise<MissionTranslationsResponse> {
  const response = await adminFetch(
    `/api/v1/admin/missions/${missionId}/translations`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<MissionTranslationsResponse>
}

export type AdminSystemSetting = {
  key: string
  value: unknown
  valueType: string
  category: string
  title: string
  description: string | null
  isSensitive: boolean
  status: string
  updatedAt: string | null
}

export async function listSystemSettings(): Promise<AdminSystemSetting[]> {
  const response = await adminFetch('/api/v1/admin/system-settings')

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { settings: AdminSystemSetting[] }
  return body.settings
}

export async function updateSystemSetting(
  key: string,
  value: unknown,
  reason?: string,
): Promise<AdminSystemSetting> {
  const response = await adminFetch(
    `/api/v1/admin/system-settings/${encodeURIComponent(key)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value, reason: reason ?? null }),
    },
  )

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  const body = (await response.json()) as { setting: AdminSystemSetting }
  return body.setting
}
export type AdminPermissionGrant = {
  permissionCode: string
  executionMode: string
  isActive: boolean
  grantedByAdminId: string | null
  grantedAt: string | null
  revokedByAdminId: string | null
  revokedAt: string | null
  reason: string | null
}

export type AdminUserFull = {
  id: string
  username: string
  role: string
  isSuperAdmin: boolean
  isActive: boolean
  isDeleted: boolean
  createdByAdminId: string | null
  createdAt: string | null
  updatedAt: string | null
  lastLoginAt: string | null
  deactivatedAt: string | null
  deactivationReason: string | null
  permissions: AdminPermissionGrant[]
}

export async function listAdmins(): Promise<AdminUserFull[]> {
  const response = await adminFetch('/api/v1/admin/admins')
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { admins: AdminUserFull[] }
  return body.admins
}
export type PermissionCatalogEntry = {
  code: string
  title: string
  category: string
}

export const PERMISSION_CATALOG: PermissionCatalogEntry[] = [
  { code: 'admin_approvals.read', title: 'Просмотр заявок', category: 'administration' },
  { code: 'admin_approvals.review', title: 'Одобрение заявок', category: 'administration' },
  { code: 'admin_permissions.manage', title: 'Управление правами', category: 'administration' },
  { code: 'admins.manage', title: 'Управление админами', category: 'administration' },
  { code: 'admins.read', title: 'Просмотр админов', category: 'administration' },
  { code: 'audit.read', title: 'Просмотр аудита', category: 'administration' },
  { code: 'ar_objects.manage', title: 'Управление AR-объектами', category: 'content' },
  { code: 'ar_objects.read', title: 'Просмотр AR-объектов', category: 'content' },
  { code: 'missions.manage', title: 'Управление миссиями', category: 'content' },
  { code: 'missions.read', title: 'Просмотр миссий', category: 'content' },
  { code: 'seasons.read', title: 'Просмотр сезонов', category: 'content' },
  { code: 'seasons.manage', title: 'Управление сезонами', category: 'content' },
  { code: 'key_rules.manage', title: 'Управление правилами ключей', category: 'economy' },
  { code: 'key_rules.read', title: 'Просмотр правил ключей', category: 'economy' },
  { code: 'reward_pools.manage', title: 'Управление пулами наград', category: 'economy' },
  { code: 'reward_pools.read', title: 'Просмотр пулов наград', category: 'economy' },
  { code: 'geo_zones.manage', title: 'Управление геозонами', category: 'geo' },
  { code: 'geo_zones.read', title: 'Просмотр геозон', category: 'geo' },
  { code: 'players.block', title: 'Блокировка игроков', category: 'players' },
  { code: 'players.manage', title: 'Управление игроками', category: 'players' },
  { code: 'players.read', title: 'Просмотр игроков', category: 'players' },
  { code: 'players.restrict', title: 'Ограничения игроков', category: 'players' },
  { code: 'system_settings.manage', title: 'Управление настройками', category: 'system_settings' },
  { code: 'system_settings.read', title: 'Просмотр настроек', category: 'system_settings' },
  { code: 'teams.manage', title: 'Управление командами', category: 'teams' },
  { code: 'teams.read', title: 'Просмотр команд', category: 'teams' },
]
export type GrantPermissionPayload = {
  permission_code: string
  execution_mode?: string
  reason?: string
}

export async function grantPermission(
  adminId: string,
  payload: GrantPermissionPayload,
): Promise<AdminUserFull> {
  const response = await adminFetch(
    `/api/v1/admin/admins/${encodeURIComponent(adminId)}/permissions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        permission_code: payload.permission_code,
        execution_mode: payload.execution_mode ?? 'direct',
        reason: payload.reason ?? null,
      }),
    },
  )
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { admin: AdminUserFull }
  return body.admin
}

export async function revokePermission(
  adminId: string,
  permissionCode: string,
): Promise<AdminUserFull> {
  const response = await adminFetch(
    `/api/v1/admin/admins/${encodeURIComponent(adminId)}/permissions/${encodeURIComponent(permissionCode)}`,
    { method: 'DELETE' },
  )
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { admin: AdminUserFull }
  return body.admin
}

export async function deactivateAdmin(
  adminId: string,
  reason: string,
): Promise<AdminUserFull> {
  const response = await adminFetch(
    `/api/v1/admin/admins/${encodeURIComponent(adminId)}/deactivate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
  )
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { admin: AdminUserFull }
  return body.admin
}

export async function reactivateAdmin(
  adminId: string,
): Promise<AdminUserFull> {
  const response = await adminFetch(
    `/api/v1/admin/admins/${encodeURIComponent(adminId)}/reactivate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
  )
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { admin: AdminUserFull }
  return body.admin
}

export type CreateAdminPayload = {
  username: string
  password: string
}

export async function createAdmin(
  payload: CreateAdminPayload,
): Promise<AdminUserFull> {
  const response = await adminFetch('/api/v1/admin/admins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const body = (await response.json()) as { admin: AdminUserFull }
  return body.admin
}
export type KeyRule = {
  id: string
  itemId: string
  itemTitle: string
  itemCode: string
  itemSymbol: string | null
  itemStatus: string
  isConsumable: boolean
  stackLimit: number
  price: number | null
  sortOrder: number
  transferForbidden: boolean
  saleForbidden: boolean
  tradeForbidden: boolean
  createdAt: string | null
  updatedAt: string | null
}

export type KeyItem = {
  id: string
  code: string
  title: string
  symbol: string | null
  status: string
}

export async function listKeyRules(): Promise<KeyRule[]> {
  const response = await adminFetch('/api/v1/admin/key-rules')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { keyRules: KeyRule[] }
  return body.keyRules
}

export async function getKeyRule(keyRuleId: string): Promise<KeyRule> {
  const response = await adminFetch(
    `/api/v1/admin/key-rules/${encodeURIComponent(keyRuleId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { keyRule: KeyRule }
  return body.keyRule
}

export type CreateKeyRulePayload = {
  item_id: string
  is_consumable?: boolean
  stack_limit?: number
  price?: number | null
  sort_order?: number
  transfer_forbidden?: boolean
  sale_forbidden?: boolean
  trade_forbidden?: boolean
}

export async function createKeyRule(
  payload: CreateKeyRulePayload,
): Promise<KeyRule> {
  const response = await adminFetch('/api/v1/admin/key-rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { keyRule: KeyRule }
  return body.keyRule
}

export type UpdateKeyRulePayload = {
  is_consumable?: boolean
  stack_limit?: number
  price?: number | null
  sort_order?: number
  transfer_forbidden?: boolean
  sale_forbidden?: boolean
  trade_forbidden?: boolean
}

export async function updateKeyRule(
  keyRuleId: string,
  payload: UpdateKeyRulePayload,
): Promise<KeyRule> {
  const response = await adminFetch(
    `/api/v1/admin/key-rules/${encodeURIComponent(keyRuleId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { keyRule: KeyRule }
  return body.keyRule
}

export async function listKeyItems(
  status: string = 'published',
): Promise<KeyItem[]> {
  const params = new URLSearchParams({ status })
  const response = await adminFetch(
    `/api/v1/admin/key-rules/items?${params.toString()}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { items: KeyItem[] }
  return body.items
}

export type CreateKeyItemPayload = {
  title: string
  code: string
  symbol?: string | null
  description?: string | null
  rarity?: string
  is_consumable?: boolean
  stack_limit?: number
  price?: number | null
  sort_order?: number
  transfer_forbidden?: boolean
  sale_forbidden?: boolean
  trade_forbidden?: boolean
}

export async function createKeyItem(
  payload: CreateKeyItemPayload,
): Promise<KeyRule> {
  const response = await adminFetch('/api/v1/admin/key-rules/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { keyRule: KeyRule }
  return body.keyRule
}
export type MissionRuntimePolicy = {
  id: string
  missionId: string
  version: number
  status: string
  entryRootAtomic: number
  // Sprint 11.8 NanoROOT (этап 2C): параллельное значение в nano.
  entryRootAtomicNano?: number | null
  maxAttempts: number
  repeatabilityPolicy: string
  requiredItemsJson: Record<string, unknown>
  challengePolicyJson: Record<string, unknown>
  rewardPolicyJson: Record<string, unknown>
  fallbackPolicyJson: Record<string, unknown> | null
  featureFlagsJson: Record<string, unknown>
  createdAt: string | null
  updatedAt: string | null
}

export type CreateMissionRuntimePolicyPayload = {
  mission_id: string
  entry_root_atomic: number
  max_attempts: number
  repeatability_policy: string
  required_items_json: Record<string, unknown>
  challenge_policy_json: Record<string, unknown>
  reward_policy_json: Record<string, unknown>
  fallback_policy_json?: Record<string, unknown> | null
  feature_flags_json?: Record<string, unknown>
}

export type UpdateMissionRuntimePolicyPayload = Partial<
  Omit<CreateMissionRuntimePolicyPayload, 'mission_id'>
>

export async function listMissionRuntimePolicies(): Promise<
  MissionRuntimePolicy[]
> {
  const response = await adminFetch('/api/v1/admin/mission-runtime-policies')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    missionRuntimePolicies: MissionRuntimePolicy[]
  }
  return body.missionRuntimePolicies
}

export async function getMissionRuntimePolicy(
  policyId: string,
): Promise<MissionRuntimePolicy> {
  const response = await adminFetch(
    `/api/v1/admin/mission-runtime-policies/${encodeURIComponent(policyId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    missionRuntimePolicy: MissionRuntimePolicy
  }
  return body.missionRuntimePolicy
}

export async function createMissionRuntimePolicy(
  payload: CreateMissionRuntimePolicyPayload,
): Promise<MissionRuntimePolicy> {
  const response = await adminFetch('/api/v1/admin/mission-runtime-policies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    missionRuntimePolicy: MissionRuntimePolicy
  }
  return body.missionRuntimePolicy
}

export async function updateMissionRuntimePolicy(
  policyId: string,
  payload: UpdateMissionRuntimePolicyPayload,
): Promise<MissionRuntimePolicy> {
  const response = await adminFetch(
    `/api/v1/admin/mission-runtime-policies/${encodeURIComponent(policyId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    missionRuntimePolicy: MissionRuntimePolicy
  }
  return body.missionRuntimePolicy
}

export async function getMissionRuntimePolicyByMission(
  missionId: string,
): Promise<MissionRuntimePolicy | null> {
  const response = await adminFetch(
    `/api/v1/admin/missions/${encodeURIComponent(missionId)}/runtime-policy`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    runtimePolicy: MissionRuntimePolicy | null
  }
  return body.runtimePolicy
}

export type MissionRuntimePolicyUpsertPayload = {
  entry_root_atomic: number
  required_items_json: Record<string, unknown>
  max_attempts?: number
  repeatability_policy?: string
  challenge_policy_json?: Record<string, unknown> | null
}

export async function upsertMissionRuntimePolicy(
  missionId: string,
  payload: MissionRuntimePolicyUpsertPayload,
): Promise<MissionRuntimePolicy> {
  const response = await adminFetch(
    `/api/v1/admin/missions/${encodeURIComponent(missionId)}/runtime-policy`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    runtimePolicy: MissionRuntimePolicy
  }
  return body.runtimePolicy
}

export async function publishMissionRuntimePolicy(
  policyId: string,
): Promise<MissionRuntimePolicy> {
  const response = await adminFetch(
    `/api/v1/admin/mission-runtime-policies/${encodeURIComponent(policyId)}/publish`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    missionRuntimePolicy: MissionRuntimePolicy
  }
  return body.missionRuntimePolicy
}

export type AdminGeoZone = {
  id: string
  slug: string
  title: string
  description: string | null
  zoneType: string
  status: string
  sortOrder: number
  latitude: number | null
  longitude: number | null
  radiusMeters: number | null
  searchRadiusMeters: number | null
  locationConstraints: Record<string, boolean>
  polygonCoordinates: unknown[] | null
  timezone: string
  startsAt: string | null
  endsAt: string | null
  maxLocationAccuracyMeters: number | null
  minimumPresenceSeconds: number
  createdAt: string | null
  updatedAt: string | null
}

export type CreateGeoZonePayload = {
  slug?: string
  title: string
  description?: string | null
  zone_type?: string
  sort_order?: number
  latitude?: number | null
  longitude?: number | null
  radius_meters?: number | null
  search_radius_meters?: number | null
  location_constraints?: Record<string, boolean>
  polygon_coordinates?: unknown[] | null
  timezone?: string
  starts_at?: string | null
  ends_at?: string | null
  max_location_accuracy_meters?: number | null
  minimum_presence_seconds?: number
}

export type UpdateGeoZonePayload = {
  slug?: string
  title?: string
  description?: string | null
  zone_type?: string
  status?: string
  sort_order?: number
  latitude?: number | null
  longitude?: number | null
  radius_meters?: number | null
  search_radius_meters?: number | null
  location_constraints?: Record<string, boolean>
  polygon_coordinates?: unknown[] | null
  timezone?: string
  starts_at?: string | null
  ends_at?: string | null
  max_location_accuracy_meters?: number | null
  minimum_presence_seconds?: number
}

export async function listGeoZones(): Promise<AdminGeoZone[]> {
  const response = await adminFetch('/api/v1/admin/geo-zones')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { geoZones: AdminGeoZone[] }
  return body.geoZones
}

export async function getGeoZone(zoneId: string): Promise<AdminGeoZone> {
  const response = await adminFetch(
    `/api/v1/admin/geo-zones/${encodeURIComponent(zoneId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { geoZone: AdminGeoZone }
  return body.geoZone
}

export async function createGeoZone(
  payload: CreateGeoZonePayload,
): Promise<AdminGeoZone> {
  const response = await adminFetch('/api/v1/admin/geo-zones', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { geoZone: AdminGeoZone }
  return body.geoZone
}

export async function updateGeoZone(
  zoneId: string,
  payload: UpdateGeoZonePayload,
): Promise<AdminGeoZone> {
  const response = await adminFetch(
    `/api/v1/admin/geo-zones/${encodeURIComponent(zoneId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { geoZone: AdminGeoZone }
  return body.geoZone
}
export type AdminARObject = {
  id: string
  slug: string
  title: string
  description: string | null
  status: string
  sortOrder: number
  geoZoneId: string
  objectType: string
  assetUri: string
  assetMimeType: string | null
  scenePreset: string | null
  scaleMeters: number
  orientation: string
  discoveryScenario: Record<string, unknown>
  minigameConfig: Record<string, unknown>
  instructionText: string | null
  validationConfig: Record<string, unknown>
  startsAt: string | null
  endsAt: string | null
  createdAt: string | null
  updatedAt: string | null
}

export type CreateARObjectPayload = {
  slug?: string
  title: string
  description?: string | null
  sort_order?: number
  geo_zone_id: string
  object_type: string
  asset_uri: string
  asset_mime_type?: string | null
  scene_preset?: string | null
  scale_meters?: number
  orientation?: string
  discovery_scenario?: Record<string, unknown>
  minigame_config?: Record<string, unknown>
  instruction_text?: string | null
  validation_config?: Record<string, unknown>
  starts_at?: string | null
  ends_at?: string | null
}

export type UpdateARObjectPayload = {
  slug?: string
  title?: string
  description?: string | null
  status?: string
  sort_order?: number
  geo_zone_id?: string
  object_type?: string
  asset_uri?: string
  asset_mime_type?: string | null
  scene_preset?: string | null
  scale_meters?: number
  orientation?: string
  discovery_scenario?: Record<string, unknown>
  minigame_config?: Record<string, unknown>
  instruction_text?: string | null
  validation_config?: Record<string, unknown>
  starts_at?: string | null
  ends_at?: string | null
}

export async function listARObjects(): Promise<AdminARObject[]> {
  const response = await adminFetch('/api/v1/admin/ar-objects')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { arObjects: AdminARObject[] }
  return body.arObjects
}

export async function getARObject(arObjectId: string): Promise<AdminARObject> {
  const response = await adminFetch(
    `/api/v1/admin/ar-objects/${encodeURIComponent(arObjectId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { arObject: AdminARObject }
  return body.arObject
}

export async function createARObject(
  payload: CreateARObjectPayload,
): Promise<AdminARObject> {
  const response = await adminFetch('/api/v1/admin/ar-objects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { arObject: AdminARObject }
  return body.arObject
}

export async function updateARObject(
  arObjectId: string,
  payload: UpdateARObjectPayload,
): Promise<AdminARObject> {
  const response = await adminFetch(
    `/api/v1/admin/ar-objects/${encodeURIComponent(arObjectId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { arObject: AdminARObject }
  return body.arObject
}

// =============================================================================
// Minigame profiles (Sprint 8.17, шаг 4а)
// =============================================================================

export type AdminMinigameProfile = {
  id: string
  name: string
  gameType: string
  settings: Record<string, unknown>
  status: 'draft' | 'published' | 'archived'
  createdAt: string | null
  updatedAt: string | null
}

export type CreateMinigameProfilePayload = {
  name: string
  game_type: string
  settings: Record<string, unknown>
}

export type UpdateMinigameProfilePayload = {
  name?: string
  game_type?: string
  settings?: Record<string, unknown>
}

export async function listMinigameProfiles(): Promise<AdminMinigameProfile[]> {
  const response = await adminFetch('/api/v1/admin/minigame-profiles')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    minigameProfiles: AdminMinigameProfile[]
  }
  return body.minigameProfiles
}

export async function getMinigameProfile(
  id: string,
): Promise<AdminMinigameProfile> {
  const response = await adminFetch(
    `/api/v1/admin/minigame-profiles/${encodeURIComponent(id)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    minigameProfile: AdminMinigameProfile
  }
  return body.minigameProfile
}

export async function createMinigameProfile(
  payload: CreateMinigameProfilePayload,
): Promise<AdminMinigameProfile> {
  const response = await adminFetch('/api/v1/admin/minigame-profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    minigameProfile: AdminMinigameProfile
  }
  return body.minigameProfile
}

export async function updateMinigameProfile(
  id: string,
  payload: UpdateMinigameProfilePayload,
): Promise<AdminMinigameProfile> {
  const response = await adminFetch(
    `/api/v1/admin/minigame-profiles/${encodeURIComponent(id)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    minigameProfile: AdminMinigameProfile
  }
  return body.minigameProfile
}

export async function publishMinigameProfile(
  id: string,
): Promise<AdminMinigameProfile> {
  const response = await adminFetch(
    `/api/v1/admin/minigame-profiles/${encodeURIComponent(id)}/publish`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    minigameProfile: AdminMinigameProfile
  }
  return body.minigameProfile
}

export async function archiveMinigameProfile(
  id: string,
): Promise<AdminMinigameProfile> {
  const response = await adminFetch(
    `/api/v1/admin/minigame-profiles/${encodeURIComponent(id)}/archive`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    minigameProfile: AdminMinigameProfile
  }
  return body.minigameProfile
}

// Seasons (Sprint 8.21)
// =============================================================================

export type AdminSeason = {
  id: string
  slug: string
  title: string
  description: string | null
  status: 'draft' | 'published' | 'archived'
  sortOrder: number
  createdAt: string | null
  updatedAt: string | null
}

export type CreateSeasonPayload = {
  slug?: string | null
  title: string
  description?: string | null
  sort_order?: number
}

export type UpdateSeasonPayload = {
  slug?: string | null
  title?: string | null
  description?: string | null
  sort_order?: number | null
}

export async function listSeasons(status?: string): Promise<AdminSeason[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const response = await adminFetch(`/api/v1/admin/seasons${query}`)
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { seasons: AdminSeason[] }
  return body.seasons
}

export async function getSeason(seasonId: string): Promise<AdminSeason> {
  const response = await adminFetch(
    `/api/v1/admin/seasons/${encodeURIComponent(seasonId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { season: AdminSeason }
  return body.season
}

export async function createSeason(
  payload: CreateSeasonPayload,
): Promise<AdminSeason> {
  const response = await adminFetch('/api/v1/admin/seasons', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { season: AdminSeason }
  return body.season
}

export async function updateSeason(
  seasonId: string,
  payload: UpdateSeasonPayload,
): Promise<AdminSeason> {
  const response = await adminFetch(
    `/api/v1/admin/seasons/${encodeURIComponent(seasonId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { season: AdminSeason }
  return body.season
}

export async function publishSeason(seasonId: string): Promise<AdminSeason> {
  const response = await adminFetch(
    `/api/v1/admin/seasons/${encodeURIComponent(seasonId)}/publish`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { season: AdminSeason }
  return body.season
}

export async function archiveSeason(seasonId: string): Promise<AdminSeason> {
  const response = await adminFetch(
    `/api/v1/admin/seasons/${encodeURIComponent(seasonId)}/archive`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { season: AdminSeason }
  return body.season
}

export type AdminEconomyTransaction = {
  id: string
  walletId: string
  playerId: string
  playerDisplayName: string | null
  amount: number
  balanceAfter: number
  // Sprint 11.8 NanoROOT (этап 2C): параллельное значение в nano.
  balanceAfterNano?: number | null
  transactionType: 'credit' | 'debit'
  reason: string
  referenceType: string | null
  referenceId: string | null
  createdAt: string | null
}

export type EconomyTransactionsFilters = {
  playerId?: string
  search?: string
  type?: 'credit' | 'debit'
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export async function listEconomyTransactions(
  filters: EconomyTransactionsFilters = {},
): Promise<{
  transactions: AdminEconomyTransaction[]
  total: number
  limit: number
  offset: number
}> {
  const params = new URLSearchParams()
  if (filters.playerId) params.set('player_id', filters.playerId)
  if (filters.search) params.set('search', filters.search)
  if (filters.type) params.set('type', filters.type)
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/economy/transactions${query}`)
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    transactions: AdminEconomyTransaction[]
    total: number
    limit: number
    offset: number
  }
  return body
}


// ---- Журнал Stars-платежей (Sprint 12.2) --------------------------------
// Read-only: контракт — backend/app/admin_economy.py (list_stars_payments).
// Ответ — конверт {items, total, limit, offset}. gasAmount приходит строкой:
// на бэке это Numeric(18,4)/Decimal, str() сохраняет точность.
// playerId уходит как snake_case player_id (точное совпадение), playerSearch —
// как player_search (id ИЛИ ник/имя: ILIKE по display_name/telegram_*/nickname
// на бэке); оба — query-параметры FastAPI, как в listEconomyTransactions выше.

export type AdminStarsPaymentStatus = 'pending' | 'completed' | 'refunded'

export type AdminStarsPayment = {
  id: string
  playerId: string
  playerDisplayName: string | null
  gasAmount: string
  amountStars: number
  status: AdminStarsPaymentStatus
  telegramPaymentChargeId: string | null
  referenceId: string
  payload: string
  createdAt: string | null
}

export type StarsPaymentsFilters = {
  status?: AdminStarsPaymentStatus
  playerId?: string
  playerSearch?: string
  search?: string
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export type AdminStarsPaymentsResponse = {
  items: AdminStarsPayment[]
  total: number
  limit: number
  offset: number
}

export async function listStarsPayments(
  filters: StarsPaymentsFilters = {},
): Promise<AdminStarsPaymentsResponse> {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.playerId) params.set('player_id', filters.playerId)
  if (filters.playerSearch) params.set('player_search', filters.playerSearch)
  if (filters.search) params.set('search', filters.search)
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  params.set('limit', String(filters.limit ?? 50))
  params.set('offset', String(filters.offset ?? 0))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(
    `/api/v1/admin/economy/stars-payments${query}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  return (await response.json()) as AdminStarsPaymentsResponse
}


// ---- Игроки (10.0.3, часть 1) -------------------------------------------
// Read-only типы и функции для вкладки «Игроки». Контракты — из
// admin_players.py: _serialize_player_summary, _serialize_player_card,
// GET /profile-fields (PROFILE_FIELDS).

export type AdminPlayerSummary = {
  id: string
  displayName: string | null
  authProvider: string
  status: string
  nickname: string | null
  country: string | null
  gender: string | null
  age: number | null
  telegramUsername: string | null
  telegramFirstName: string | null
  telegramLastName: string | null
  telegramPhotoUrl: string | null
  createdAt: string | null
  rootBalance: number
  // Sprint 11.8 NanoROOT (этап 2C): параллельное значение в nano.
  rootBalanceNano?: number | null
}

export type AdminProfileField = {
  key: string
  label: string
  type: 'text' | 'select' | 'number'
  options?: string[]
  readOnly?: boolean
  maxLength?: number
  min?: number
  max?: number
}

export type AdminPlayerCard = {
  player: {
    id: string
    displayName: string | null
    authProvider: string
    status: string
    nickname: string | null
    country: string | null
    gender: string | null
    age: number | null
    externalId: string | null
    telegram: {
      username: string | null
      firstName: string | null
      lastName: string | null
      photoUrl: string | null
      normalizedUsername: string | null
    }
    registeredAt: string | null
    lastActivityAt: string | null
    lastSeenAt: string | null
  }
  wallet: {
    currency: string
    availableBalance: number
    // Sprint 11.8 NanoROOT (этап 2C): параллельные значения в nano.
    availableBalanceNano?: number | null
    lockedBalance: number
    lockedBalanceNano?: number | null
  }
  gasBalance: string
  inventory: Array<{
    id: string
    itemId: string
    slug: string
    code: string
    title: string
    symbol: string
    category: string
    rarity: string
    quantity: number
    obtainedFromType: string | null
    obtainedFromId: string | null
  }>
  activeMissions: Array<{
    missionId: string
    slug: string
    title: string
    missionType: string
    status: string
    attemptCount: number
    startedAt: string | null
  }>
  missionHistory: Array<{
    missionId: string
    slug: string
    title: string
    status: string
    attemptCount: number
    startedAt: string | null
    completedAt: string | null
  }>
  restrictions: Array<{
    id: string
    restrictionType: string
    status: string
    reason: string
    evidence: string | null
    adminId: string
    startsAt: string | null
    expiresAt: string | null
    approvedByApprovalId: string | null
    revokedAt: string | null
    revocationReason: string | null
  }>
  recentTransactions: Array<{
    id: string
    amount: number
    balanceAfter: number
    // Sprint 11.8 NanoROOT (этап 2C): параллельное значение в nano.
    balanceAfterNano?: number | null
    transactionType: 'credit' | 'debit'
    reason: string
    referenceType: string | null
    referenceId: string | null
    metadata: Record<string, unknown>
    createdAt: string | null
  }>
  stats: {
    totalMissionsCompleted: number
    totalRootEarned: number
    totalRootSpent: number
    // Sprint 8.x-fractional-transfer: те же суммы в nanoROOT (1 ROOT = 10^8).
    totalRootEarnedNano?: number | null
    totalRootSpentNano?: number | null
  }
}

export type PlayersFilters = {
  search?: string
  status?: string
  authProvider?: string
  limit?: number
  offset?: number
}

export async function listPlayers(
  filters: PlayersFilters = {},
): Promise<{
  players: AdminPlayerSummary[]
  total: number
  limit: number
  offset: number
}> {
  const params = new URLSearchParams()
  if (filters.search) params.set('search', filters.search)
  if (filters.status) params.set('status', filters.status)
  if (filters.authProvider) params.set('auth_provider', filters.authProvider)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/players${query}`)
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as {
    players: AdminPlayerSummary[]
    total: number
    limit: number
    offset: number
  }
  return body
}

// 13.7-i-1/13.7-i-2: статистика всех игроков (total/online/active).
export type PlayersStats = {
  period: string // 'day' | 'week' | 'month'
  total: number
  online: number
  active: number
}

export async function getPlayersStats(period: string): Promise<PlayersStats> {
  const params = new URLSearchParams()
  params.set('period', period)
  const response = await adminFetch(
    `/api/v1/admin/players/stats?${params.toString()}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as PlayersStats
  return body
}

export async function getPlayer(playerId: string): Promise<AdminPlayerCard> {
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { player: AdminPlayerCard }
  return body.player
}

export type PlayerProfileUpdatePayload = {
  country?: string | null
  gender?: string | null
  age?: number | null
}

export async function updatePlayerProfile(
  playerId: string,
  payload: PlayerProfileUpdatePayload,
): Promise<AdminPlayerCard> {
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { player: AdminPlayerCard }
  return body.player
}

export type GasAdjustmentPayload = {
  amount: string // Decimal строкой — точность Numeric(18,4); бэк парсит в Decimal
  reason: string
}

export async function updatePlayerGas(
  playerId: string,
  payload: GasAdjustmentPayload,
): Promise<AdminPlayerCard> {
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}/gas`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { player: AdminPlayerCard }
  return body.player
}

export type RootAdjustmentPayload = {
  amount: number
  reason: string
}

export async function updatePlayerRoot(
  playerId: string,
  payload: RootAdjustmentPayload,
): Promise<AdminPlayerCard> {
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}/root`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { player: AdminPlayerCard }
  return body.player
}

export type PlayerBlockPayload = {
  reason: string
}

export async function blockPlayer(
  playerId: string,
  payload: PlayerBlockPayload,
): Promise<AdminPlayerCard> {
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}/block`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { player: AdminPlayerCard }
  return body.player
}

export async function unblockPlayer(
  playerId: string,
  payload: PlayerBlockPayload,
): Promise<AdminPlayerCard> {
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}/unblock`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { player: AdminPlayerCard }
  return body.player
}

export type GasTransaction = {
  id: string
  amount: string
  balanceAfter: string
  transactionType: string
  reason: string
  referenceType: string | null
  referenceId: string | null
  metadata: Record<string, unknown>
  createdAt: string | null
}

export type GasTransactionsResponse = {
  transactions: GasTransaction[]
  total: number
  limit: number
  offset: number
}

export async function getPlayerGasTransactions(
  playerId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<GasTransactionsResponse> {
  const params = new URLSearchParams()
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}/gas-transactions${query}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as GasTransactionsResponse
  return body
}

export type RootTransaction = {
  id: string
  amount: number // ROOT — int
  balanceAfter: number
  // Sprint 11.8 NanoROOT (этап 2C): параллельное значение в nano.
  balanceAfterNano?: number | null
  transactionType: string
  reason: string
  referenceType: string | null
  referenceId: string | null
  metadata: Record<string, unknown>
  createdAt: string | null
}

export type RootTransactionsResponse = {
  transactions: RootTransaction[]
  total: number
  limit: number
  offset: number
}

export async function getPlayerRootTransactions(
  playerId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<RootTransactionsResponse> {
  const params = new URLSearchParams()
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(
    `/api/v1/admin/players/${encodeURIComponent(playerId)}/root-transactions${query}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<RootTransactionsResponse>
}

export async function getProfileFields(): Promise<{
  fields: AdminProfileField[]
}> {
  const response = await adminFetch('/api/v1/admin/players/profile-fields')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { fields: AdminProfileField[] }
  return body
}

export type MonitoringError = {
  id: string
  correlationId: string
  severity: string
  errorType: string
  message: string
  safeContext: Record<string, unknown> | null
  endpoint: string | null
  statusCode: number | null
  playerId: string | null
  stack: string | null
  createdAt: string | null
}

export type MonitoringErrorsResponse = {
  errors: MonitoringError[]
  total: number
  limit: number
  offset: number
}

export type MonitoringEvent = {
  id: string
  playerId: string
  eventType: string
  payloadJson: Record<string, unknown> | null
  correlationId: string | null
  createdAt: string | null
}

export type MonitoringEventsResponse = {
  events: MonitoringEvent[]
  total: number
  limit: number
  offset: number
}

export async function getMonitoringErrors(
  options: {
    severity?: string
    period?: string
    correlationId?: string
    errorType?: string
    endpoint?: string
    statusCode?: number
    limit?: number
    offset?: number
  } = {},
): Promise<MonitoringErrorsResponse> {
  const params = new URLSearchParams()
  if (options.severity) params.set('severity', options.severity)
  if (options.period) params.set('period', options.period)
  if (options.correlationId) params.set('correlation_id', options.correlationId)
  if (options.errorType) params.set('error_type', options.errorType)
  if (options.endpoint) params.set('endpoint', options.endpoint)
  if (options.statusCode !== undefined)
    params.set('status_code', String(options.statusCode))
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/monitoring/errors${query}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<MonitoringErrorsResponse>
}

export type MonitoringErrorGroup = {
  errorType: string
  endpoint: string | null
  statusCode: number | null
  count: number
  affectedPlayers: number
  firstSeen: string | null
  lastSeen: string | null
  isGlobal: boolean
}

export type MonitoringErrorGroupsResponse = {
  groups: MonitoringErrorGroup[]
  total: number
  limit: number
  offset: number
}

export async function getErrorGroups(
  options: {
    severity?: string
    period?: string
    minCount?: number
    limit?: number
    offset?: number
  } = {},
): Promise<MonitoringErrorGroupsResponse> {
  const params = new URLSearchParams()
  if (options.severity) params.set('severity', options.severity)
  if (options.period) params.set('period', options.period)
  if (options.minCount !== undefined)
    params.set('min_count', String(options.minCount))
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(
    `/api/v1/admin/monitoring/error-groups${query}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<MonitoringErrorGroupsResponse>
}

export async function getMonitoringEvents(
  options: {
    eventType?: string
    playerId?: string
    period?: string
    limit?: number
    offset?: number
  } = {},
): Promise<MonitoringEventsResponse> {
  const params = new URLSearchParams()
  if (options.eventType) params.set('event_type', options.eventType)
  if (options.playerId) params.set('player_id', options.playerId)
  if (options.period) params.set('period', options.period)
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/monitoring/events${query}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<MonitoringEventsResponse>
}

export type Withdrawal = {
  id: string
  playerId: string
  amountRoot: number
  // Sprint 11.8 NanoROOT (этап 2C): параллельное значение суммы в nano.
  amountRootNano?: number | null
  toAddress: string
  status: string
  tonTxHash: string | null
  batchId: string | null
  adminId: string | null
  reason: string | null
  // Причина отказа ВЫПЛАТЫ (не путать с reason — это отклонение админом).
  // Заполняется из последнего PayoutAttempt: сеть, конфиг, баланс.
  payoutError?: string | null
  payoutAttemptStatus?: string | null
  payoutAttemptedAt?: string | null
  createdAt: string | null
  updatedAt: string | null
}

export type WithdrawalsListResponse = {
  withdrawals: Withdrawal[]
  total: number
  limit: number
  offset: number
}

// 11.6-b: админ-эндпоинты заявок на вывод ROOT → TON (players.read/players.manage).
export async function listWithdrawals(
  options: {
    status?: string
    playerId?: string
    period?: string
    limit?: number
    offset?: number
  } = {},
): Promise<WithdrawalsListResponse> {
  const params = new URLSearchParams()
  if (options.status) params.set('status', options.status)
  if (options.playerId) params.set('player_id', options.playerId)
  if (options.period) params.set('period', options.period)
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/withdrawals${query}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<WithdrawalsListResponse>
}

// --- Батчи для внешней оплаты (TON Connect, 11.x-external-payout) ----------

export type PayoutBatchItem = {
  withdrawalId: string
  playerId: string
  toAddress: string
  amountRoot: number
  amountRootNano: number
  // Ключ сверки в блокчейне: по нему подтверждается конкретная заявка.
  queryId: string | null
  status: string
}

export type PayoutBatch = {
  batchId: string
  status: 'ready' | 'submitted' | 'confirmed' | 'rolled_back' | string
  totalNano: number
  totalRoot: number
  itemCount: number | null
  openedAt: string | null
  txHash: string | null
  payloadText: string | null
  items: PayoutBatchItem[] | null
}

export type PayoutBatchRow = {
  batchId: string
  status: string
  totalNano: number
  totalRoot: number
  itemCount: number
  openedAt: string | null
  // Сколько дней батч висит открытым (для подсветки «залежался»).
  ageDays: number | null
  stale: boolean
  txHash: string | null
  rollbackReason: string | null
}

export type PayoutBatchesListResponse = {
  batches: PayoutBatchRow[]
  total: number
  limit: number
  offset: number
}

/** Сформировать батч из pending-заявок (или вернуть уже открытый). */
export async function createPayoutBatch(limit = 50): Promise<PayoutBatch> {
  const response = await adminFetch(
    `/api/v1/admin/withdrawals/payout-batches?limit=${limit}`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<PayoutBatch>
}

export async function listPayoutBatches(
  options: { status?: string; limit?: number; offset?: number } = {},
): Promise<PayoutBatchesListResponse> {
  const params = new URLSearchParams()
  if (options.status) params.set('status', options.status)
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.offset !== undefined) params.set('offset', String(options.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(
    `/api/v1/admin/withdrawals/payout-batches${query}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<PayoutBatchesListResponse>
}

export type PayoutBatchConfirmResult = {
  batchId: string
  status: 'confirmed' | 'submitted' | string
  confirmedCount: number
  pendingCount: number
  totalCount: number
  confirmed: { withdrawalId: string; queryId: string; txHash: string }[]
  pending: { withdrawalId: string; queryId: string; reason: string }[]
}

/** Подтвердить батч подписанным BOC от TON Connect. */
export async function confirmPayoutBatch(
  batchId: string,
  boc: string,
): Promise<PayoutBatchConfirmResult> {
  const response = await adminFetch(
    `/api/v1/admin/withdrawals/payout-batches/${encodeURIComponent(batchId)}/confirm`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ boc }),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<PayoutBatchConfirmResult>
}

export async function getPayoutBatch(batchId: string): Promise<PayoutBatch> {
  const response = await adminFetch(
    `/api/v1/admin/withdrawals/payout-batches/${encodeURIComponent(batchId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<PayoutBatch>
}


export async function runWithdrawalBatch(
  limit = 50,
): Promise<{ batchId: string; confirmed: number; failed: number }> {
  const response = await adminFetch(
    `/api/v1/admin/withdrawals/batch?limit=${limit}`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<{
    batchId: string
    confirmed: number
    failed: number
  }>
}

export async function rejectWithdrawal(
  id: string,
  reason: string,
): Promise<{ withdrawalId: string; status: string; reason: string }> {
  const response = await adminFetch(
    `/api/v1/admin/withdrawals/${encodeURIComponent(id)}/reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<{
    withdrawalId: string
    status: string
    reason: string
  }>
}



// ---- Гео-аудит (Sprint 8.9.c + Security-Audit B6/B7) ---------------------
// Список флагов античита + решение админа (reviewGeoAuditFlag):
//   reviewed  — «Снять блок» (revoke withdrawal_restricted/transfer_restricted);
//   dismissed — «Заблокировать» (blocked + revoke обоих).
// Контракт — backend/app/admin_geo_audit.py. Сырых координат в ответе нет:
// только производные числа (speedKmh/accuracyMeters/...) и ids.

export type GeoAuditSignal = {
  signal: 'velocity' | 'accuracy'
  speedKmh?: number
  distanceKm?: number
  elapsedSeconds?: number
  thresholdKmh?: number
  accuracyMeters?: number
  thresholdMeters?: number
}

export type GeoAuditReviewDecision = 'reviewed' | 'dismissed'

export type GeoAuditReviewStatus = 'review' | 'reviewed' | 'dismissed'

export type GeoAuditFlag = {
  id: string
  playerId: string
  missionId: string | null
  zoneId: string | null
  mode: string | null
  signals: GeoAuditSignal[]
  reviewStatus: GeoAuditReviewStatus | null
  correlationId: string | null
  createdAt: string | null
}

export type GeoAuditFlagsResponse = {
  flags: GeoAuditFlag[]
  total: number
  limit: number
  offset: number
}

export type GeoAuditFlagsFilters = {
  playerId?: string
  period?: string
  signal?: string
  limit?: number
  offset?: number
}

export async function getGeoAuditFlags(
  filters: GeoAuditFlagsFilters = {},
): Promise<GeoAuditFlagsResponse> {
  const params = new URLSearchParams()
  if (filters.playerId) params.set('player_id', filters.playerId)
  if (filters.period) params.set('period', filters.period)
  if (filters.signal) params.set('signal', filters.signal)
  if (filters.limit !== undefined) params.set('limit', String(filters.limit))
  if (filters.offset !== undefined) params.set('offset', String(filters.offset))
  const query = params.toString() ? `?${params.toString()}` : ''
  const response = await adminFetch(`/api/v1/admin/geo-audit/flags${query}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<GeoAuditFlagsResponse>
}

export async function reviewGeoAuditFlag(
  playerId: string,
  missionId: string,
  decision: GeoAuditReviewDecision,
  reason?: string,
): Promise<{ playerId: string; missionId: string; status: string }> {
  const response = await adminFetch(
    `/api/v1/admin/geo-audit/flags/${encodeURIComponent(playerId)}/${encodeURIComponent(missionId)}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, reason: reason ?? null }),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  return response.json() as Promise<{
    playerId: string
    missionId: string
    status: string
  }>
}

