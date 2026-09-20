import type { EngineMission } from '../api/engineApi'

export function missionText(
  mission: EngineMission | undefined,
  field: string,
  fallback: string,
): string {
  const value = mission?.content[field]
  return typeof value === 'string' ? value : fallback
}

export function missionBlocks(
  mission: EngineMission | undefined,
  fallback: string[],
): string[] {
  const blocks = mission?.content.blocks
  return Array.isArray(blocks) &&
    blocks.every((block) => typeof block === 'string')
    ? blocks
    : fallback
}
