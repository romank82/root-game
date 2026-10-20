export type AdminRole = 'super_admin' | 'owner' | 'editor' | 'viewer' | 'admin'
export type AdminMissionStatus = 'draft' | 'published'

export type AdminUser = {
  id: string
  username: string
  // Legacy display value. Do not use it as the source of authorization.
  role: AdminRole
  isSuperAdmin: boolean
}

export type AdminReward = {
  id?: string
  rewardType: 'currency' | 'item' | 'story_node' | string
  amount: number | null
  itemId: string | null
  storyNodeId: string | null
  rewardValue: Record<string, unknown>
  sortOrder: number
}

export type AdminMission = {
  id: string
  chapterId: string
  storyNodeId: string | null
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
  sortOrder: number
  rewards: AdminReward[]
  createdAt: string | null
  updatedAt: string | null
}

export type AdminMissionPayload = {
  chapter_id: string
  story_node_id?: string | null
  geo_zone_id?: string | null
  ar_object_id?: string | null
  minigame_profile_id?: string | null
  slug: string
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
    story_node_id?: string | null
    reward_value?: Record<string, unknown>
    sort_order?: number
  }>
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

export async function listAdminMissions(): Promise<AdminMission[]> {
  const response = await adminFetch('/api/v1/admin/missions')

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
  { code: 'segments.manage', title: 'Управление сегментами', category: 'content' },
  { code: 'segments.read', title: 'Просмотр сегментов', category: 'content' },
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

export type AdminSegmentLink = {
  id: string
  missionId: string
  sortOrder: number
}

export type AdminSegment = {
  id: string
  chapterId: string
  slug: string
  title: string
  description: string | null
  content: Record<string, unknown>
  status: string
  sortOrder: number
  linkedMissions: AdminSegmentLink[]
  createdAt: string | null
  updatedAt: string | null
}

export type CreateSegmentPayload = {
  chapter_id: string
  slug: string
  title: string
  description?: string | null
  content?: Record<string, unknown>
  sort_order?: number
  linked_missions?: Array<{ mission_id: string; sort_order: number }>
}

export type UpdateSegmentPayload = {
  chapter_id?: string
  slug?: string
  title?: string
  description?: string | null
  content?: Record<string, unknown>
  sort_order?: number
  linked_missions?: Array<{ mission_id: string; sort_order: number }>
}

export async function listSegments(): Promise<AdminSegment[]> {
  const response = await adminFetch('/api/v1/admin/segments')
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segments: AdminSegment[] }
  return body.segments
}

export async function getSegment(segmentId: string): Promise<AdminSegment> {
  const response = await adminFetch(
    `/api/v1/admin/segments/${encodeURIComponent(segmentId)}`,
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segment: AdminSegment }
  return body.segment
}

export async function createSegment(
  payload: CreateSegmentPayload,
): Promise<AdminSegment> {
  const response = await adminFetch('/api/v1/admin/segments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segment: AdminSegment }
  return body.segment
}

export async function updateSegment(
  segmentId: string,
  payload: UpdateSegmentPayload,
): Promise<AdminSegment> {
  const response = await adminFetch(
    `/api/v1/admin/segments/${encodeURIComponent(segmentId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segment: AdminSegment }
  return body.segment
}

export async function publishSegment(segmentId: string): Promise<AdminSegment> {
  const response = await adminFetch(
    `/api/v1/admin/segments/${encodeURIComponent(segmentId)}/publish`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segment: AdminSegment }
  return body.segment
}

export async function unpublishSegment(segmentId: string): Promise<AdminSegment> {
  const response = await adminFetch(
    `/api/v1/admin/segments/${encodeURIComponent(segmentId)}/unpublish`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segment: AdminSegment }
  return body.segment
}

export async function archiveSegment(segmentId: string): Promise<AdminSegment> {
  const response = await adminFetch(
    `/api/v1/admin/segments/${encodeURIComponent(segmentId)}/archive`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(await readError(response))
  const body = (await response.json()) as { segment: AdminSegment }
  return body.segment
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
  slug: string
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
  slug: string
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
