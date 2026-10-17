# План удаления attempt_deadline_seconds

## Причина

Поле было добавлено ошибочно как «per-attempt timer». Фактически:

- «Общий таймер миссии» (deadline_at из execution_time_limit_seconds) — НЕ
  должен сбрасываться между попытками.
- «Таймер мини-игры» (content.ui.timeLimitSeconds) — клиентский, сбрасывается
  при провале (фикс CipherScreen — отдельно).
- attempt_deadline_seconds — не нужен. Мусор.

Принцип: в код зашивается только механика. Переменные для настройки —
в админке. attempt_deadline_seconds в админке НЕТ → мусор.

## Что удаляем

Полностью: модель + контракт + API + engine + миграция + тесты + фронт-типы + docs.

Team-флоу НЕ использует attempt_deadline_seconds (использует своё
activation.deadlineSeconds) — правок в team нет.

## Порядок шагов

### Шаг 1. ✅ Engine — откат блока шага 6

Файл: backend/app/mission_engine.py.
Удалить 17 строк (блок if policy is not None and policy.attempt_deadline_seconds).
deadline_at снова управляется только в _accept_mission_once.

### Шаг 2. ✅ Тесты engine

Файл: backend/tests/test_mission_engine_integration.py.
Удалить test_zz_attempt_deadline_resets_per_attempt.
Проверить: 2 других zz-теста (fallback, no-limit) — проходят без блока шага 6.
Если да — оставить. Если нет — удалить/адаптировать.
Параметр attempt_deadline_seconds в _seed_policy — удалить.

### Шаг 3. ✅ Контракт

Файл: backend/app/runtime_policy_contract.py.
Удалить:
- аргумент attempt_deadline_seconds из validate_runtime_policy.
- валидацию _integer(attempt_deadline_seconds, ...).
- константы DEADLINE_SECONDS_MIN/MAX.
- упоминания в __all__ (если есть).

### Шаг 4. ✅ Admin API

Файл: backend/app/admin_mission_runtime_policies.py.
Удалить 12 вхождений:
- DEADLINE_SECONDS_MAX.
- UPDATABLE_FIELDS.
- create-payload (обязательное int = Field(ge=1, le=86400)).
- update-payload (attempt_deadline_seconds: int | None).
- upsert-payload (default 3600).
- _policy_arguments, _policy_from_row, _validate_policy_via_contract.
- Сериализация attemptDeadlineSeconds.
- Routes (create/upsert).

### Шаг 5. ✅ Миграция (drop column)

Создать backend/migrations/versions/<rev>_drop_attempt_deadline_seconds.py:
- dialect-aware (PostgreSQL DROP COLUMN; SQLite batch_alter_table).
- downgrade: NotImplementedError.
Backup chimera.db перед применением.

### Шаг 6. ✅ Модель

Файл: backend/app/geo_team_runtime_models.py.
Удалить:
- attempt_deadline_seconds: Mapped[int].
- CheckConstraint("attempt_deadline_seconds >= 1").

### Шаг 7. ✅ Frontend-типы

Файл: src/api/adminApi.ts.
Удалить 3 вхождения (attemptDeadlineSeconds, attempt_deadline_seconds).

### Шаг 8. ✅ Остальные тесты

- test_admin_mission_runtime_policies.py: удалить тесты create с
  attempt_deadline_seconds (границы 0/86401, сериализация).
- test_runtime_policy_contract.py: удалить тесты границ
  attempt_deadline_seconds (1/86400/0/86401).
- test_fallback_shop.py: убрать аргумент seed 600.

### Шаг 9. ✅ Docs

- docs/solo-mission-runtime-policy-contract.md.
- docs/sprint-8.14-plan.md.
- docs/roadmap-detailed.md.
- docs/stage-4-gap-analysis.md.
- docs/audit-2026-10-04.md.

## Итог

Все 9 шагов выполнены 2026-10-16. Поле удалено на всех слоях: engine, контракт,
admin API, модель, миграция, фронт-типы, тесты, docs. `deadline_at` снова
управляется только в `_accept_mission_once`.

Коммиты:
- `b69c2cd` — docs: план.
- `7af016c` — step 1–2 (engine + engine-тесты).
- `262f392` — step 3–4 (контракт + admin API).
- `4a5d606` — step 5–6 (миграция + модель).
- `2b43094` — step 7 (frontend-типы).
- `f719ef0` — step 8 (остальные тесты).
- коммит step 9 — после этого коммита (правка docs).

Результаты:
- Миграция `5c85930cfb3e` (drop column; SQLite batch_alter_table /
  PostgreSQL DROP COLUMN), применена на chimera.db, backup сохранён.
- Тесты: 554 OK (556 − 2 удалённых теста-границы).
- Backend `/health` 200; данные policy сохранены (14 строк).

## Риски

- Shared DDL: колонка в общей таблице для solo/team/race/co-op. Drop
  затрагивает обе СУБД. Нужна dialect-aware миграция и backup.
- SQLite: batch_alter_table пересоздаёт таблицу. Данные 14 policy сохранятся.
- После удаления поля engine вернётся к поведению «deadline только от accept».

## Правила

- Каждый шаг — отдельный промпт.
- Тесты после каждого шага.
- Коммит после каждых 2-3 шагов.
- Не трогать team-флоу.
- Не трогать GeoTeamRun.deadline_at.

## Что НЕ входит

- Фикс CipherScreen (сброс timeLeft при провале) — отдельный промпт.
- Фикс CooldownCountdown (не показывается при 409 / тайм-ауте) — отдельный промпт.
- Sprint 8.17 (админ-форма policy) — отдельно.