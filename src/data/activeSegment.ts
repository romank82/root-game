import { segments, type Segment } from './gameContent'

/*
  Временный адаптер для уже готового экрана Сегмента в App.tsx.

  Когда App.tsx начнёт получать активную миссию через API,
  этот файл будет больше не нужен.
*/
export type ActiveSegment = Segment & {
  reward: {
    root: number
    itemName?: string
  }
}

const segment = segments[0]

if (!segment) {
  throw new Error('Не найден тестовый Сегмент.')
}

export const activeSegment: ActiveSegment = {
  ...segment,
  reward: {
    root: 10,
    itemName: 'АРХИВНЫЙ СЕГМЕНТ A-17',
  },
}