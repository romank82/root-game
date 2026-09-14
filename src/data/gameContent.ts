export type SegmentType =
  | 'DATA_SEGMENT'
  | 'DAMAGED_SEGMENT'
  | 'ARCHIVE_SEGMENT'
  | 'KEY_SEGMENT'
  | 'BLACK_SEGMENT'
  | 'GHOST_SEGMENT'

export type PuzzleType =
  | 'CODE_REPAIR'
  | 'QR_RECONSTRUCT'
  | 'PACKET_ROUTING'
  | 'FREQUENCY_DECODE'
  | 'COOPERATIVE_ASSEMBLY'

export type Segment = {
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

  arScene: {
    scenePreset: string
    scanHoldDurationMs: number
    visibleFaces: string[]
    qrMode: 'VIRTUAL_FACE_QR'
  }

  availability: {
    startsAt: string | null
    endsAt: string | null
    countriesBlocked: string[]
  }
}

export type Reward = {
  root: number
  inventoryItemId?: string
  unlocksStoryNodeId?: string
}

export type InventoryItem = {
  id: string
  code: string
  title: string
  description: string
  symbol: string
  category: 'ARCHIVE' | 'KEY' | 'COSMETIC' | 'QUEST'
  isUnique: boolean
}

export type MissionAttempt = {
  number: 1 | 2 | 3
  unlockAfterMinutes: number
  stakeRoot: number
  rewardMultiplier: number
  givesUniqueItem: boolean
}

export type Puzzle = {
  id: string
  type: PuzzleType
  title: string
  instruction: string
  config: Record<string, unknown>

  /*
    Важно:
    правильное решение здесь намеренно НЕ хранится.
    Клиент отправляет действие на backend,
    а backend проверяет результат и создаёт награду в ledger.
  */
  validation: {
    mode: 'SERVER'
    validatorKey: string
  }
}

export type Mission = {
  id: string
  segmentId: string
  title: string
  description: string

  requiredMissionIds: string[]
  puzzleId: string

  attempts: MissionAttempt[]

  reward: Reward

  alternativeRoute: {
    enabled: boolean
    storyNodeId: string | null
    description: string | null
  }
}

export type StoryNode = {
  id: string
  title: string
  body: string
  requiredMissionIds: string[]
}

/*
  ---------------------------------------------------------------
  ВРЕМЕННЫЙ ЛОКАЛЬНЫЙ КОНТЕНТ ДЛЯ ПРОТОТИПА.
  ---------------------------------------------------------------

  Позже эти объекты не будут храниться во frontend-проекте:
  FastAPI будет получать их из PostgreSQL,
  а администратор — создавать и редактировать в админ-панели.

  React-клиент будет получать только разрешённые текущему игроку
  сегменты, миссии, награды и прогресс.
*/

export const inventoryItems: InventoryItem[] = [
  {
    id: 'item-archive-a17',
    code: 'ARCHIVE_A17',
    title: 'АРХИВНЫЙ СЕГМЕНТ A-17',
    description:
      'Связанный с исчезнувшей записью фрагмент. Его данные повреждены, но структура указывает на внешний архивный контур.',
    symbol: '◈',
    category: 'ARCHIVE',
    isUnique: true,
  },
  {
    id: 'item-key-a01',
    code: 'KEY_A01',
    title: 'КЛЮЧ A-01',
    description:
      'Повреждённый ключ доступа, извлечённый из первого архивного пакета.',
    symbol: '⌘',
    category: 'KEY',
    isUnique: true,
  },
]

export const segments: Segment[] = [
  {
    id: 'segment-archive-017',
    code: 'ARCHIVE_NODE_017',
    type: 'ARCHIVE_SEGMENT',
    title: 'ПОТЕРЯННЫЙ КОНТУР',
    description:
      'В городском пространстве зафиксирован нестабильный архивный след. Найдите безопасную точку сканирования и запустите AR-поиск Сегмента.',

    searchRadiusMeters: 250,
    safeScanRadiusMeters: 15,

    /*
      Тестовые координаты.

      Для реальной проверки на телефоне замените на безопасную
      пешеходную точку рядом с собой. В production их выдаёт backend.
    */
    safeScanPoint: {
      latitude: 54.958598,
      longitude: 82.906663,
    },

    arScene: {
      scenePreset: 'archive_cube_damaged_v1',
      scanHoldDurationMs: 1800,
      visibleFaces: ['north', 'east'],
      qrMode: 'VIRTUAL_FACE_QR',
    },

    availability: {
      startsAt: null,
      endsAt: null,
      countriesBlocked: [],
    },
  },
]

export const puzzles: Puzzle[] = [
  {
    id: 'puzzle-code-repair-a17',
    type: 'CODE_REPAIR',
    title: 'ВОССТАНОВЛЕНИЕ КОДА',
    instruction:
      'Восстановите повреждённую последовательность в архивном пакете.',

    /*
      Сюда админ-панель позже будет передавать данные мини-игры:
      блоки кода, позиции ошибок, лимит времени, уровень сложности
      и другие параметры конкретной головоломки.
    */
    config: {
      difficulty: 1,
      timeLimitSeconds: 120,
      damagedBlocks: 3,
    },

    validation: {
      mode: 'SERVER',
      validatorKey: 'code_repair_v1',
    },
  },
]

export const missions: Mission[] = [
  {
    id: 'mission-archive-017',
    segmentId: 'segment-archive-017',
    title: 'ИЗВЛЕЧЕНИЕ ARCHIVE_NODE_017',
    description:
      'Зафиксируйте грань AR-куба, извлеките виртуальный QR-маркер и восстановите повреждённый пакет.',

    requiredMissionIds: [],
    puzzleId: 'puzzle-code-repair-a17',

    attempts: [
      {
        number: 1,
        unlockAfterMinutes: 0,
        stakeRoot: 5,
        rewardMultiplier: 1,
        givesUniqueItem: true,
      },
      {
        number: 2,
        unlockAfterMinutes: 15,
        stakeRoot: 0,
        rewardMultiplier: 0.35,
        givesUniqueItem: false,
      },
      {
        number: 3,
        unlockAfterMinutes: 720,
        stakeRoot: 0,
        rewardMultiplier: 0.15,
        givesUniqueItem: false,
      },
    ],

    reward: {
      root: 10,
      inventoryItemId: 'item-archive-a17',
      unlocksStoryNodeId: 'story-node-a17',
    },

    alternativeRoute: {
      enabled: true,
      storyNodeId: 'story-node-fallback-a17',
      description:
        'После трёх попыток архив открывает нестабильный альтернативный маршрут.',
    },
  },
]

export const storyNodes: StoryNode[] = [
  {
    id: 'story-node-a17',
    title: 'ФРАГМЕНТ A-17',
    body:
      'Архивный контур откликнулся. В извлечённых данных найдено упоминание Оператора и координат следующего Сегмента.',
    requiredMissionIds: ['mission-archive-017'],
  },
  {
    id: 'story-node-fallback-a17',
    title: 'ОСТАТОЧНЫЙ СЛЕД A-17',
    body:
      'Первичный пакет не удалось восстановить. Контур оставил только слабый след, ведущий к альтернативной ветке расследования.',
    requiredMissionIds: [],
  },
]

export function getSegmentById(segmentId: string) {
  return segments.find((segment) => segment.id === segmentId)
}

export function getMissionById(missionId: string) {
  return missions.find((mission) => mission.id === missionId)
}

export function getPuzzleById(puzzleId: string) {
  return puzzles.find((puzzle) => puzzle.id === puzzleId)
}

export function getInventoryItemById(itemId: string) {
  return inventoryItems.find((item) => item.id === itemId)
}