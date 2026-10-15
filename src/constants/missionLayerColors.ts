/**
 * Цвета слоёв миссии (story / team / solo).
 *
 * Единый источник правды для всего проекта. Используется в:
 * - TerminalScreen (аккордеон-папки)
 * - MapScreen (цвет круга миссии)
 * - ScannerScreen (цвет радара)
 * - CameraTestScreen (цвет рёбер AR-куба)
 * - App.css через CSS-переменные (свитчер слоёв, куб)
 *
 * Sprint 8.13: вынесено из дублей в TerminalScreen/MapScreen/ScannerScreen.
 */

export type MissionLayer = 'solo' | 'team' | 'story'

export const MISSION_LAYER_COLORS: Record<MissionLayer, string> = {
  story: '#ff5c5c', // красный
  team: '#4da6ff',  // синий
  solo: '#ffcc00',  // жёлтый
}

/**
 * Fallback для неизвестных или пустых слоёв.
 * Применяется, если missionLayer не определён или не входит в MissionLayer.
 */
export const DEFAULT_MISSION_LAYER_COLOR = MISSION_LAYER_COLORS.solo

/**
 * Безопасно получить цвет слоя. Возвращает fallback при неизвестном значении.
 */
export function getMissionLayerColor(layer: string | null | undefined): string {
  if (layer === 'story' || layer === 'team' || layer === 'solo') {
    return MISSION_LAYER_COLORS[layer]
  }
  return DEFAULT_MISSION_LAYER_COLOR
}

/**
 * Список известных слоёв в порядке отображения (story → team → solo).
 */
export const MISSION_LAYER_ORDER: MissionLayer[] = ['story', 'team', 'solo']