export type SegmentType =
  | 'DATA_SEGMENT'
  | 'DAMAGED_SEGMENT'
  | 'ARCHIVE_SEGMENT'
  | 'KEY_SEGMENT'
  | 'BLACK_SEGMENT'
  | 'GHOST_SEGMENT'

export type ActiveSegment = {
  id: string
  code: string
  type: SegmentType
  title: string
  description: string
  searchRadiusMeters: number
  safeScanRadiusMeters: number
  safeScanPoint: {
    latitude: number
    longitude: number
  }
  reward: {
    root: number
    itemName?: string
  }
  arScene: {
    scenePreset: string
    scanHoldDurationMs: number
  }
}

/*
  ВРЕМЕННЫЕ ДАННЫЕ ПРОТОТИПА.

  Позже этот объект заменится ответом backend API.
  Администратор будет создавать и редактировать Сегменты
  через админ-панель, а клиент будет получать только
  доступные конкретному игроку задания.
*/
export const activeSegment: ActiveSegment = {
  id: 'segment-archive-017',
  code: 'ARCHIVE_NODE_017',
  type: 'ARCHIVE_SEGMENT',
  title: 'ПОТЕРЯННЫЙ КОНТУР',
  description:
    'В городском пространстве зафиксирован нестабильный архивный след. Найдите безопасную точку сканирования и запустите AR-поиск Сегмента.',

  searchRadiusMeters: 250,
  safeScanRadiusMeters: 15,

  /*
    ТЕСТОВЫЕ КООРДИНАТЫ.
    Поменяйте их на координаты рядом с вами, чтобы проверить
    разблокировку AR-поиска на реальном телефоне.
  */
  safeScanPoint: {
    latitude: 55.7558,
    longitude: 37.6173,
  },

  reward: {
    root: 10,
    itemName: 'АРХИВНЫЙ СЕГМЕНТ A-17',
  },

  arScene: {
    scenePreset: 'archive_cube_damaged_v1',
    scanHoldDurationMs: 1800,
  },
}