# Sprint 8.23 — Каскадный конструктор (Сезон → Глава → Сегмент → Миссия)

## 1. Цель

Админ получает единый экран-конструктор: пошаговым выбором (Сезон → Глава →
Сегмент → Миссия) он находит нужный элемент иерархии или создаёт новый прямо из
каскада — без ручного ввода ID и без переключения между четырьмя вкладками. На
каждом шаге видны только элементы выбранного родителя, рядом — команда «создать
новый» (форма заполняется с уже проставленным родителем).

## 2. Текущее состояние (что уже есть)

Иерархия в БД готова, миграции не нужны:

- Season → Chapter (FK `chapters.season_id`).
- Chapter → Segment (FK `segments.chapter_id`), Chapter → Mission (FK
  `missions.chapter_id`), Chapter → StoryNode (FK `story_nodes.chapter_id`).
- Segment → Mission через N:M `segments_missions` (SegmentMission: `sort_order`,
  lifecycle `active`/`archived`, immutable history, partial unique index на
  active-связь).

Каскад частично реализован в UI и API:

- **Сезон → Глава**: `ChaptersSection.tsx` — dropdown сезона (из `listSeasons()`,
  фильтр не-archived).
- **Глава → Сегмент**: `SegmentsEditor.tsx` — dropdown Chapter ID.
- **Сегмент → Миссия**: `SegmentsEditor.tsx` — строки-связи `linkedMissions`
  (missionId + sortOrder); бэкенд проверяет совпадение главы миссии и сегмента.
- **Глава → StoryNode**: `MissionsSection.tsx` — story node dropdown
  перезагружается по `form.chapterId` через `listStoryNodes(undefined, chapterId)`
  (8.24-доп).

Дыры (по разведке):

- `GET /api/v1/admin/chapters` не принимает `?season_id`, хотя `api-contracts.md`
  это обещает.
- `GET /api/v1/admin/segments` и `GET /api/v1/admin/missions` — без фильтров
  (отдают всё).
- В `SegmentsEditor.tsx` выпадашка миссий для привязки не фильтруется по главе
  (админ видит все миссии, бэкенд отклонит несовпадение 4xx).
- Нет `backend/tests/test_admin_segments.py` (модуль `admin_segments.py`,
  714 строк, без выделенных тестов).

## 3. Что делаем

### Этап 1 — бэкенд-фильтры (только query-параметры, без миграций)

- `GET /api/v1/admin/chapters?season_id=` — фильтр по сезону в
  `list_admin_chapters` (закрывает расхождение с `api-contracts.md`).
  Валидация: если `season_id` задан и сезона нет — 404 (стиль `_validate_season`).
- `GET /api/v1/admin/segments?chapter_id=` — фильтр по главе в
  `list_admin_segments`. Валидация: если глава не существует — 404.
- `GET /api/v1/admin/missions?chapter_id=` — фильтр по главе в
  `list_admin_missions`. Вариант `?segment_id` НЕ берём: сегмент уже отдаёт
  `linkedMissions` в своём payload, а миссия привязана к сегменту только через
  junction-таблицу; фильтр по главе симметричен остальным уровням каскада и
  закрывает потребность «миссии сегмента» через 2 запроса.
- Паттерны: существующие `_serialize`/`_validate_*`/permissions
  (`chapters.read`, `segments.read`, `missions.read`), без изменения схемы БД,
  без новых роутов.
- Тесты на каждый фильтр (см. раздел 6).

### Этап 2 — фронт: CascadeSection + adminApi + вкладка

- `src/api/adminApi.ts`: сигнатуры `listChapters(status?, seasonId?)`,
  `listSegments(chapterId?)`, `listAdminMissions(chapterId?)` — передают
  `season_id`/`chapter_id` в query.
- Новый `src/components/admin/CascadeSection.tsx`: 4 колонки/шага:
  1. Сезон — «выбрать существующий / создать новый»;
  2. Глава — только главы выбранного сезона (`listChapters(undefined, seasonId)`)
     + «создать новую» с pre-filled родителем;
  3. Сегмент — только сегменты выбранной главы (`listSegments(chapterId)`)
     + «создать новый» (форма как в `SegmentsEditor`, родитель проставляется);
  4. Миссия — только миссии выбранной главы (`listAdminMissions(chapterId)`)
     + «создать новую» (форма как в `MissionsSection`, `chapterId` pre-filled).
  Навигация вниз: клик по элементу шага N фильтрует шаг N+1; шаги ниже
  сбрасываются при смене родителя.
- `src/AdminApp.tsx`: новая вкладка «Конструктор» (section `cascade`) + рендер
  секции; показ — при `seasons.read && chapters.read && segments.read &&
  missions.read`, действия — через существующие `*.manage` и API-функции
  созданий каждого уровня.
- **Фикс** `SegmentsEditor.tsx`: выпадашка «Привязанные миссии» фильтруется по
  `chapter_id` выбранного сегмента, чтобы не предлагать невалидные связи.

### Этап 3 — тесты сегментов + контракт + закрытие 8.23

- Новый `backend/tests/test_admin_segments.py` — закрывает дыру покрытия
  `admin_segments.py` (кейсы в разделе 6).
- Обновить `docs/api-contracts.md`: добавить `?season_id` для chapters (теперь
  реализован), `?chapter_id` для segments и missions.
- После зелёного прогона — закрыть 8.23 в `docs/roadmap-detailed.md`.

## 4. Что НЕ трогаем

- `backend/app/mission_engine.py` — игровой движок, bootstrap не меняется.
- `backend/app/shop_service.py`, `backend/app/fallback_shop.py` — магазин.
- `backend/app/qr_service.py` — QR.
- Существующие миграции (`backend/migrations/versions/*`) — миграций в 8.23 нет.
- `backend/app/team_missions_service.py`, `backend/app/admin_teams.py` — команды.
- Игровой клиент (`src/components/screens/*`, `src/hooks/*`) — только админка.

## 5. Риски

- **Расхождение контракта `chapters?season_id`**: `api-contracts.md` обещает
  параметр, код не поддерживает — закрываем в Этапе 1, иначе мастер глав без
  него не построить.
- **Несовпадение глав в связях Сегмент↔Миссия**: бэкенд уже отклоняет
  cross-chapter-связь; без фикса выпадашки (Этап 2) админ увидит невалидные
  опции и получит 4xx.
- **Published не редактируется**: `_ensure_editable` у всех сущностей; в
  мастере «создать новый» стартует как draft, редактирование published — только
  publish/unpublish/archive, как в существующих секциях.
- **N:M Сегмент↔Миссия**: у сегмента может быть несколько миссий (и миссия —
  в нескольких сегментах); в мастере НЕ показывать связь как «1:1» без
  оговорки. Ограничение 1:1 — отдельный спринт (8.25), в 8.23 не реализуется.
- Смена родителя сбрасывает выбранные шаги ниже — иначе каскад показывает
  несогласованные данные.

## 6. Тесты

Файлы:

- `backend/tests/test_admin_chapters.py` (+кейсы): `?season_id` возвращает только
  главы сезона; несуществующий `season_id` → 404; без параметра — все.
- `backend/tests/test_admin_segments.py` (новый): +кейсы CRUD/lifecycle +
  `?chapter_id` фильтр (существующая и отсутствующая глава), publish-правила
  (chapter published, ≥1 active-link с published-миссией той же главы),
  archive/unpublish, immutable history связей.
- `backend/tests/test_admin_missions.py` (+кейсы): `?chapter_id` фильтр;
  несуществующая глава → 404.
- Фронт: ручной сценарий — мастер создаёт Сезон→Главу→Сегмент→Миссию за один
  проход; фикс выпадашки миссий в SegmentsEditor (нет опций чужой главы).
- Прогон: `python -m pytest backend/tests/` и `npm run build` (EXIT=0).

## 7. Порядок коммитов (3 коммита, по этапу)

1. `feat(admin): cascade filters for chapters/segments/missions (season_id/chapter_id) + tests`
2. `feat(admin-ui): CascadeSection wizard (season→chapter→segment→mission) + segment mission link dropdown filter`
3. `docs: api-contracts cascade filters, test_admin_segments coverage, close sprint 8.23`