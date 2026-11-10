// Sprint 11.8 NanoROOT: форматирование дробного ROOT (nano → строка).
// 1 ROOT = 10^8 наноROOT. API отдаёт *_nano (BigInteger), на фронте
// делим на 10^8 и показываем с разделителями. Без лишних нулей:
//   formatRootFromNano(62500000000) → "625"
//   formatRootFromNano(1050000000) → "10,5"
//   formatRootFromNano(100) → "0,000001"
//   formatRootFromNano(0) → "0"
//   formatRootFromNano(null) → "0"

const NANO_PER_ROOT = 100_000_000

/**
 * Дробный ROOT из nano → строка для отображения (ru-RU, разделители,
 * без trailing zeros). null/undefined/NaN → "0".
 */
export function formatRootFromNano(nano: number | null | undefined): string {
  if (nano === null || nano === undefined || Number.isNaN(nano)) {
    return '0'
  }
  const root = nano / NANO_PER_ROOT
  // Intl.NumberFormat с максимум 8 знаками после запятой: не теряем
  // дробную часть (0,000001 ROOT = 100 nano), но и не печатаем нули.
  return new Intl.NumberFormat('ru-RU', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8,
    useGrouping: true,
  }).format(root)
}

/**
 * Дробный ROOT из nano → сырое число (для сравнений/расчётов, не для UI).
 * null/undefined/NaN → 0.
 */
export function nanoToRoot(nano: number | null | undefined): number {
  if (nano === null || nano === undefined || Number.isNaN(nano)) {
    return 0
  }
  return nano / NANO_PER_ROOT
}

/**
 * ROOT → nano (целое, 10^8 на 1 ROOT). Для ввода и тестов.
 * null/undefined/NaN → 0.
 */
export function rootToNano(root: number | null | undefined): number {
  if (root === null || root === undefined || Number.isNaN(root)) {
    return 0
  }
  return Math.round(root * NANO_PER_ROOT)
}
