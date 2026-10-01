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
