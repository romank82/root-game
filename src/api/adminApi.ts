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
  slug: string
  missionType: string
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
  slug: string
  mission_type: string
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
