# Sprint 8.14 — Многоразовые миссии

Архитектурный план реализации повторно проходимых одиночных миссий
(`repeatability_policy = "after_terminal"`). Построен на фактах read-only
разведки №191. Контракт, на который опирается этот спринт, —
`docs/solo-mission-runtime-policy-contract.md` (lifecycle policy, scalar
правила, повторное прохождение, награды).

## Цель

Сделать так, чтобы миссия типа "многоразовая" (`repeatability_policy = after_terminal`):

1. Возвращалась в `available` после завершения (без ручного SQL-сброса).
2. Начисляла награду за **КАЖДЫЙ** успешный проход (не только за первый).
3. Ограничивала количество попыток (`max_attempts`).
4. Уменьшала награду за поздние попытки (`attemptMultipliers`).
5. Давала отдельный таймер на каждую попытку (`attempt_deadline_seconds`).

## Что уже есть в проекте

- Модель `PlayerMission` с `attempt_count`, `deadline_at`, `available_again_at`.
- Таблица `mission_runtime_policies`: `max_attempts`, `attempt_deadline_seconds`,
  `repeatability_policy`, `reward_policy_json.attemptMultipliers` (модель в
  `geo_team_runtime_models.py`, админка в `admin_mission_runtime_policies.py`).
- `MissionRun` (`geo_team_runtime_models.py:159`, таблица `mission_runs`) —
  per-run сущность **для team-флоу**: `team_session_id`, `start_idempotency_key`,
  статусы `reserved/accepted/active/succeeded/failed/timeout/abandoned/
  cancelled_before_start`. В solo НЕ используется, но паттерн готов.
- `team_missions_service.py:759` — уже вызывает `_award_mission_rewards` с
  `reference_id=team_session.id` и `mission_run_id=mission_run.id`. Это рабочий
  пример per-run награды для team.
- `scaled_attempt_multipliers()` в `runtime_policy_contract.py` — готова,
  тесты есть, но не вызывается из production-кода.
- Уникальный индекс `(wallet_id, reference_type, reference_id)` — идемпотентность
  проводок при повторных submit.
- `expire_mission` + `Mission.reentry_cooldown_seconds` — работает для
  `expired → available` (после провала), НО НЕ для `completed → available`.
- `Mission.execution_time_limit_seconds` — ставит `deadline_at` при accept
  (один раз). НЕ per-attempt.
- `docs/solo-mission-runtime-policy-contract.md` — контракт policy (границы,
  lifecycle, scalar-правила, повторное прохождение, награды).

## Что надо добавить/изменить

### 1. Счётчик успешных проходов

**Решение: НЕ создавать MissionRun для solo.** Причины:
- `MissionRun` заточен под team: `team_session_id`, `start_idempotency_key`,
  специфичные статусы (`reserved/accepted/active/succeeded/...`).
- Для solo достаточно простого поля на `PlayerMission`.

**Что делаем:** добавить поле `PlayerMission.successful_completions` (int, default 0).

**Зачем:** служит компонентом per-run `reference_id` для награды (см. п. 2).
Сейчас счётчика успешных проходов нет — повторная награда за одну миссию
заблокирована unique index, потому что `reference_id` всегда равен `mission.id`.

**Миграция:**
```sql
ALTER TABLE player_missions
    ADD COLUMN successful_completions INTEGER NOT NULL DEFAULT 0;
```
(через Alembic, dialect-aware для PostgreSQL и SQLite; head миграции на старте
спринта — `922c9bace039`).

**Инкремент:** в `_submit_mission_once` при успешной валидации (рядом с уже
существующим `attempt_count += 1`), до вызова `_award_mission_rewards`, чтобы
внутри награды можно было использовать обновлённое значение.

### 2. Per-run reference_id

**Решение:** `reference_id = f"{player_mission.id}_{successful_completions}"`.

**Что меняется:** в `_award_mission_rewards` для solo передавать per-run id
вместо дефолтного `mission.id`. Дефолт `reference_id = mission.id` в сигнатуре
остаётся для обратной совместимости (legacy вызовы без передачи), но
solo-submit начинает передавать per-run id явно.

**Рабочий пример для team:** `team_missions_service.py:759` уже передаёт
`reference_id=team_session.id` и `mission_run_id=mission_run.id` — solo
повторяет этот паттерн без `MissionRun`.

**Идемпотентность:** сохраняется — повторный submit той же попытки не создаёт
второй транзакции (unique index `wallet_id + reference_type("mission_reward") +
reference_id`).

### 3. max_attempts enforcement

**Решение:** в `_submit_mission_once` перед инкрементом `attempt_count`
проверить `attempt_count >= max_attempts` (из published policy). При исчерпании —
НЕ инкрементировать, НЕ валидировать, вернуть `409 "Попытки исчерпаны"`.

**Что происходит при исчерпании:**
- `status = "expired"`
- если `Mission.reentry_cooldown_seconds > 0` → `available_again_at = now + cooldown`
- если `= 0` → `available_again_at = NULL` (сразу `available` для `after_terminal`,
  остаётся `expired` для одноразовой миссии)

### 4. attemptMultipliers — применять

**Решение:** подключить `scaled_attempt_multipliers()` в `_award_mission_rewards`
и умножить ROOT-награду на множитель для `attempt_count_before` (sequence_number
попытки, начиная с 1; индекс 0 — первая попытка). ROOT считается целочисленной
арифметикой, без float.

**Что меняется:**
- Убрать хардкод `[1.0] * max_attempts` в `admin_mission_runtime_policies.py`
  (upsert, строка ~657): при создании/upsert policy читать
  `missions.default_attempt_reward_multipliers` из System Settings.
- **Per-mission multipliers: отложено.** Сейчас только глобально.

**Пример:** `attemptMultipliers = [1.0, 0.5, 0.25]`:
- 1-я попытка (`attempt_count_before = 0`) → 100% награды.
- 2-я (`attempt_count_before = 1`) → 50%.
- 3-я (`attempt_count_before = 2`) → 25%.

### 5. Timer per-attempt

**Решение:** подключить `attempt_deadline_seconds` из policy — время **НА КАЖДУЮ
ПОПЫТКУ**.

**Что меняется:**
- При новой попытке (в `_submit_mission_once`, при `attempt_count > 0`):
  `deadline_at = now + attempt_deadline_seconds`.
- При первой попытке (в `_accept_mission_once`): если `attempt_deadline_seconds`
  задан — использовать его; иначе — `execution_time_limit_seconds`.
- `execution_time_limit_seconds` — оставить как fallback, **не удалять**.
- Frontend: `MissionTimer` показывает время до `deadline_at` (как сейчас).
- При новой попытке таймер визуально сбрасывается.

### 6. after_terminal для solo

**Решение:** в `_synchronize_player_missions` читать `repeatability_policy`
из published-версии `mission_runtime_policies`.

**Что делать:**
- `repeatability_policy = "after_terminal"` → после `completed` миссия
  становится `available`:
  - если `Mission.reentry_cooldown_seconds > 0` → ждать cooldown
  - если `= 0` → сразу `available`
- `repeatability_policy = "once"` → остаётся `completed` навсегда (текущее
  поведение).

### 7. Инвариант status ↔ attempt_count

**Решение:** в `_synchronize_player_missions` добавить проверку:
`status == "in_progress"` и `attempt_count >= max_attempts` → `expired`.

**Зачем:** защита от несогласованных состояний (например,
`attempt_count = 4` при `max_attempts = 3`), когда лимит меняется админом
после старта или миссия попадает в рассинхрон.

## Порядок работ

1. План (этот документ) — обновление. ✅
2. Миграция: `PlayerMission.successful_completions`. ✅
3. Per-run `reference_id` + инкремент `successful_completions`. ✅
4. `max_attempts` enforcement. ✅
5. `attemptMultipliers` подключение + убрать хардкод. ✅
6. `after_terminal` для solo (sync). ⏳
7. Timer per-attempt. ⏳
8. Инвариант `status ↔ attempt_count`. ⏳
9. Обновление docs: roadmap + audit. ✅ (этот шаг)

## Принятые решения

Все ключевые архитектурные решения приняты (см. выше). Оставшиеся детали — в
процессе реализации.

## Что НЕ входит

- Античит (Sprint 8.9).
- LocationProof в solo (Sprint 8.5).
- UI админки для multi-attempt policy (отдельно, если понадобится).

## Известный баг (требует фикса)

**Entry debit не per-run:** _apply_entry_debit использует reference_id=mission.id.
При повторном заходе debit не создаётся (unique index).
Решение: reference_id = f"{player_mission.id}_entry_{successful_completions}".
Статус: не исправлено.

## Открытые долги

- Per-key цена fallback.
- Fallback offer_id из миссии.
- UX админ-формы.
