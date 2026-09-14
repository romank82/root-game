export type GameBootstrap = {
  player: {
    id: string
    rootBalance: number
  }
  activeMission: unknown | null
  inventory: unknown[]
  storyNodes: unknown[]
  completedRewards: string[]
}

export type RewardAction =
  | 'puzzle-a-01'
  | 'puzzle-a-02'
  | 'segment-archive-017'

export type RewardClaimResponse = {
  playerId: string
  action: RewardAction
  awarded: number
  alreadyCompleted: boolean
  rootBalance: number
}

export type ResetDemoProgressResponse = {
  playerId: string
  rootBalance: number
  completedRewards: string[]
}

const API_BASE_URL = 'http://127.0.0.1:8000'

export async function getGameBootstrap(): Promise<GameBootstrap> {
  const response = await fetch(`${API_BASE_URL}/api/v1/game/bootstrap`)

  if (!response.ok) {
    throw new Error(`Bootstrap request failed: ${response.status}`)
  }

  return response.json() as Promise<GameBootstrap>
}

export async function claimReward(
  action: RewardAction,
): Promise<RewardClaimResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/game/rewards/${action}`,
    {
      method: 'POST',
    },
  )

  if (!response.ok) {
    throw new Error(`Reward claim failed: ${response.status}`)
  }

  return response.json() as Promise<RewardClaimResponse>
}

export async function resetDemoProgress(): Promise<ResetDemoProgressResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/game/reset-demo-progress`,
    {
      method: 'POST',
    },
  )

  if (!response.ok) {
    throw new Error(`Demo progress reset failed: ${response.status}`)
  }

  return response.json() as Promise<ResetDemoProgressResponse>
}