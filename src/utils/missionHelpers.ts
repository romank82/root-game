import type { EngineMission } from '../api/engineApi'

function publicMissionUi(
  mission: EngineMission | undefined,
): Record<string, unknown> | undefined {
  const ui = mission?.content.ui
  return ui !== null && typeof ui === 'object' && !Array.isArray(ui)
    ? ui as Record<string, unknown>
    : undefined
}

export function missionText(
  mission: EngineMission | undefined,
  field: string,
  fallback: string,
): string {
  const value = publicMissionUi(mission)?.[field]
  return typeof value === 'string' && value.trim()
    ? value
    : fallback
}

export function missionBlocks(
  mission: EngineMission | undefined,
  fallback: string[],
): string[] {
  const blocks = publicMissionUi(mission)?.blocks
  return Array.isArray(blocks) &&
    blocks.every((block) => typeof block === 'string' && block.trim())
    ? blocks
    : fallback
}
