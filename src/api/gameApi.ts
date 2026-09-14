export type GameBootstrap = {
  player: {
    id: string
    rootBalance: number
  }
  activeMission: unknown | null
  inventory: unknown[]
  storyNodes: unknown[]
}

const API_BASE_URL = 'http://127.0.0.1:8000'

export async function getGameBootstrap(): Promise<GameBootstrap> {
  const response = await fetch(`${API_BASE_URL}/api/v1/game/bootstrap`)

  if (!response.ok) {
    throw new Error(`Bootstrap request failed: ${response.status}`)
  }

  return response.json() as Promise<GameBootstrap>
}