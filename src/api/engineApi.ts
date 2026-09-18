export type EngineMissionStatus =
  | 'locked'
  | 'available'
  | 'in_progress'
  | 'completed'

export type EngineMission = {
  id: string
  slug: string
  missionType: 'text_answer' | 'code_repair' | string
  title: string
  description: string
  content: Record<string, unknown>
  status: EngineMissionStatus
  attemptCount: number
  startedAt: string | null
  completedAt: string | null
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

type SubmitPayload = {
  answer?: string
  sequence?: string[]
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8001'

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

export async function resetEngineDemoProgress(): Promise<EngineBootstrap> {
  const response = await apiFetch('/api/v1/engine/reset-demo-progress', {
    method: 'POST',
  })

  if (!response.ok) {
    throw new Error(await readError(response))
  }

  return response.json() as Promise<EngineBootstrap>
}
