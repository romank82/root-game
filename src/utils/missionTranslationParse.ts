/**
 * Разбирает перевод с нумерованными полями вида `[N] текст`.
 * Строки до первого маркера игнорируются, а последующие строки относятся
 * к последнему найденному полю. Пустые строки внутри поля сохраняются.
 */
export function parseNumbered(
  text: string,
  fieldsCount: number,
): string[] | null {
  const result = new Array<string>(fieldsCount).fill('')
  let currentIndex: number | null = null

  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*\[(\d+)\]\s*(.*)$/)
    if (match) {
      const index = Number.parseInt(match[1], 10) - 1
      if (index < 0 || index >= fieldsCount) {
        return null
      }
      currentIndex = index
      result[index] = match[2]
      continue
    }

    if (currentIndex !== null) {
      result[currentIndex] += `\n${line}`
    }
  }

  return result.map((value) => value.trim())
}

/** Сливает непустые значения разбора с уже введённой записью языка. */
export function mergeParsedFields(
  previous: Record<string, unknown>,
  parsed: string[],
  fields: string[],
): Record<string, unknown> | null {
  if (parsed.every((value) => value.trim() === '')) {
    return null
  }

  const merged = { ...previous }
  const previousContentUi = previous.contentUi
  const contentUi: Record<string, unknown> =
    previousContentUi !== null && typeof previousContentUi === 'object'
      ? { ...(previousContentUi as Record<string, unknown>) }
      : {}

  fields.forEach((field, index) => {
    const value = parsed[index]?.trim() ?? ''
    if (value === '') return
    if (field === 'title' || field === 'description') {
      merged[field] = value
    } else {
      contentUi[field] = value
    }
  })

  merged.contentUi = contentUi
  return merged
}

/** Нормализует JSON-значение code_repair.blocks для формы и API. */
export function normalizeBlocks(
  raw: string,
): { blocks: string[] | null; error: string | null } {
  if (raw.trim() === '') {
    return { blocks: [], error: null }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { blocks: null, error: 'Блоки должны быть валидным JSON-массивом строк.' }
  }

  if (!Array.isArray(parsed)) {
    return { blocks: null, error: 'Блоки должны быть JSON-массивом строк.' }
  }
  if (!parsed.every((item): item is string => typeof item === 'string')) {
    return { blocks: null, error: 'Все элементы blocks должны быть строками.' }
  }

  return { blocks: parsed, error: null }
}
