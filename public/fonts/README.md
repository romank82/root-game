# Шрифты (локальные, переменные)

Скачаны с Google Fonts (fonts.gstatic.com). Лицензия — SIL Open Font License 1.1 (OFL-1.1).

| Семейство | Диапазон весов | Подмножества | Файлы |
|-----------|----------------|--------------|-------|
| Manrope | 200–800 | latin, cyrillic | `Manrope-latin.woff2`, `Manrope-cyrillic.woff2` |
| Unbounded | 200–900 | latin, cyrillic | `Unbounded-latin.woff2`, `Unbounded-cyrillic.woff2` |
| JetBrains Mono | 100–800 | latin, cyrillic | `JetBrainsMono-latin.woff2`, `JetBrainsMono-cyrillic.woff2` |

## Зачем latin + cyrillic
Интерфейс игры на русском, поэтому для каждого семейства подключены подмножества
`latin` (базовая латиница, цифры, пунктуация) и `cyrillic` (кириллица). В `App.css`
они объявлены через `@font-face` с `unicode-range`.

## Почему один файл на подмножество (variable)
Все три семейства — variable-шрифты: Google Fonts отдаёт один и тот же файл для
всех начертаний. Вес задаётся диапазоном `font-weight` в `@font-face`
(например `font-weight: 200 800`), поэтому дублировать файлы по весам не нужно.

## Источники и лицензия
- OFL-1.1: https://openfontlicense.org/
- Manrope: https://fonts.google.com/specimen/Manrope
- Unbounded: https://fonts.google.com/specimen/Unbounded
- JetBrains Mono: https://fonts.google.com/specimen/JetBrains+Mono