# Stage 4 — Gap analysis: legacy solo-путь против runtime-контрактов

## Назначение

Документ фиксирует разрыв между работающим движком миссий и целевой вертикалью
одиночных runtime-миссий.

Опорные контракты: `docs/mission-run-contract.md` (авторитет по run и attempt),
`docs/solo-mission-runtime-policy-contract.md` (policy),
`docs/mission-state-machines.md` (state machines),
`docs/inventory-ledger-contract.md` (инвентарь),
`docs/economy-and-root-ledger.md` (ROOT ledger),
`docs/system-settings.md` (платформенные defaults и граница конфигурации),
`docs/game-rules.md`, `docs/geo-team-mission-contract.md` (cipher и
shared-runtime boundary), `docs/api-contracts.md`.

Документ описательный: он фиксирует состояние и разрывы, но не заменяет
профильные контракты и ничего не предписывает исполнять.

## Метод и точка отсчёта

Анализ выполнен read-only на коммите `f82bb95` (ветка `feat/segments-missions`).

Прочитано полностью: `docs/mission-run-contract.md`,
`docs/solo-mission-runtime-policy-contract.md`, `docs/mission-state-machines.md`,
`docs/system-settings.md`, `docs/inventory-ledger-contract.md`,
`docs/economy-and-root-ledger.md`, `docs/geo-team-mission-contract.md`,
`docs/game-rules.md` (раздел solo), `docs/segment-content-contract.md`,
`docs/api-contracts.md`; код `backend/app/mission_engine.py`, engine-роуты
`backend/app/main.py`, `backend/app/content_contract.py`,
`backend/app/system_settings_catalog.py`, `backend/app/admin_system_settings.py`;
схема PostgreSQL и SQLite; `src/api/engineApi.ts`, `src/hooks/useGameState.ts`,
`src/components/screens/*`.

Изменений в коде, схеме, данных и миграциях не производилось.

## 1. Текущий legacy solo-путь

Функционален и используется игроком.

| Маршрут | Назначение |
|---|---|
| `GET /api/v1/engine/bootstrap` | публичный срез игрока, миссий, сегментов, инвентаря, story nodes |
| `POST /api/v1/engine/missions/{mission_id}/submit` | проверка ответа и выдача награды |
| `POST /api/v1/engine/reset-demo-progress` | dev-only, в production отвечает 404 |

Модель данных legacy-пути:

- прогресс — `player_missions`, статусы `locked → available → in_progress → completed`;
- попытки — счётчик `player_missions.attempt_count`;
- проверка ответа — `missions.validation_config` (`normalized_text_match`,
  `ordered_blocks_match`);
- награды — `mission_rewards`, проводка `WalletTransaction` с
  `reference_type='mission_reward'`;
- предметы — прямая мутация `player_items.quantity` без `InventoryEvent`.

`docs/system-settings.md` уже фиксирует, что публичный reset endpoint подлежит
удалению отдельной задачей после backup и аудита demo-данных.

## 2. Существующая основа, пригодная для новой вертикали

### 2.1 Чистые утилиты движка

| Компонент | Роль |
|---|---|
| `_new_id(prefix)` | генерация идентификаторов |
| `_utcnow()` | UTC-время |
| `_ensure_player(session, player_id)` | проверка существования и активности игрока |
| `_get_or_create_root_wallet(session, player_id)` | получение или создание ROOT-кошелька |
| `_serialize_item`, `_serialize_story_node` | безопасная сериализация публичных данных |
| `validate_mission_content`, `validate_segment_content` | валидация публичного content |
| `_reject_hidden` | рекурсивный запрет server-only ключей |

Утилиты не привязаны к `PlayerMission` и переносятся как есть либо переезжают в
общий модуль.

### 2.2 Валидация system settings

`backend/app/system_settings_catalog.py` содержит `SYSTEM_SETTING_CATALOG` на 13
ключей, `get_definition()` и `validate_value()`. `backend/app/admin_system_settings.py`
реализует чтение каталога и значений, обновление non-sensitive ключей,
создание approval request и domain executor для `system_setting.change`.

Механизм валидации значений существует и переиспользуем. Он покрывает
платформенные defaults, но не mission-specific policy: согласно
`docs/system-settings.md` §Mission-runtime configuration boundary, entry price,
item requirements, attempt policy, cipher configuration, reward policy и
repeatability остаются validated versioned CMS configuration и в system settings
не хранятся.

## 3. Не переносится в новую вертикаль

| Компонент | Причина |
|---|---|
| `_synchronize_player_missions` | пересчитывает `locked/available` при каждом чтении |
| `_validate_submission` | два типа валидатора из `validation_config`; в v1 единственный `challengeType` — cipher |
| `_award_mission_rewards` | награды из `mission_rewards`; целевая модель — settlement |
| мутация `player_items.quantity` | прямая запись проекции без `InventoryEvent` |
| `submit_mission` retry-loop | идемпотентность через перехват `IntegrityError`; целевая — явный `Idempotency-Key` |
| `reset_demo_engine_progress` | физическое удаление `PlayerMission` и `PlayerItem`; контракты запрещают удаление |
| legacy `submit` как основная точка входа | не создаёт `MissionRun` и `MissionAttempt` |

Legacy-маршрут сам по себе не удаляется (см. §9).

## 4. Отсутствует полностью

| Компонент | Назначение |
|---|---|
| CMS-валидатор и admin API для `MissionRuntimePolicy` | верхние границы, значения `repeatability_policy`, версии JSON-схем, запрет policy для не-solo |
| Executor: start run | `POST /missions/{id}/runs`, атомарный старт, списание ROOT и items |
| Executor: issue attempt | `POST /mission-runs/{id}/attempts`, генерация cipher, protected snapshot |
| Executor: submit и resolve attempt | `POST /mission-attempts/{id}/submit`, deadline, ownership, snapshot |
| Executor: settlement | `MissionSettlement`, multiplier, ROOT и item credit с reference на settlement |
| Idempotency-слой | разбор `Idempotency-Key`, fingerprint, HTTP 409 при reuse |
| Cipher generator | комбинация из `drumCount` / `alphabet` / `falseChoicesPerDrum` |
| Reward calculator | детерминированная целочисленная арифметика, без float |
| Идемпотентный серверный timeout attempt | перевод `issued → timed_out` без повторного resolve |
| Runtime read path для system settings | чтение лимитов и feature flags вне admin-слоя |

`MissionRuntimePolicy`, `MissionRun`, `MissionAttempt`, `MissionSettlement` и
`InventoryEvent` не используются ни в одном модуле, кроме определения моделей.
Реализации нет.

## 5. Как legacy и новая вертикаль соотносятся по данным

| Аспект | Legacy | Целевое | Пересечение |
|---|---|---|---|
| Прогресс миссии | `player_missions` | `mission_runs`, `mission_attempts` | нет |
| Кошелёк и ROOT ledger | `wallets`, `wallet_transactions` | те же таблицы | да, общие |
| Инвентарь | `player_items`, прямая мутация | `player_items` как проекция плюс `inventory_events` | да, общая проекция |
| Ссылка проводки | `mission_reward` / `mission_id` | settlement-specific reference | различимы в истории |
| Попытки | `attempt_count` | `sequence_number` в `mission_attempts` | независимые счётчики |

Вывод: run-таблицы не пересекаются, но **финансовое и инвентарное состояние
общее**. Legacy и новый executor пишут в одни и те же кошельки и проекции
инвентаря, поэтому параллельная работа обеих вертикалей затрагивает общие
проекции, а различить операции можно только по `reference_type` и reference id.

Отдельная зависимость: `_build_bootstrap()` определяет разблокированные story
nodes через `player_missions.status == 'completed'`. Новый runtime пишет в
`mission_runs`, поэтому без явной политики обновления проекции прогресс,
полученный через новый flow, не отразится в bootstrap. Для v1 конфликт
ограничен, так как `story_node` reward через runtime settlement исключён из
первой версии, но политика обновления `PlayerMission` обязана быть определена.

## 6. Решения

### 6.1 Уже определено контрактами (не требует решения)

- Solo start — единая атомарная операция без reservation-фазы
  (`mission-state-machines.md`, `mission-run-contract.md`, `game-rules.md`).
- `MissionRun`: `active → succeeded | failed | timeout | abandoned`; terminal
  состояние не переходит дальше; у terminal run не более одного settlement.
- `MissionAttempt`: `issued → submitted → succeeded | failed`,
  `issued → timed_out`; `sequence_number` начинается с 1 и уникален в run;
  лимит попыток берётся из snapshot, а не из константы в коде.
- Все configured attempts включены в entry price
  (`economy-and-root-ledger.md`).
- Обычного refund после успешного старта нет; компенсация — отдельная
  авторизованная проводка с immutable reference.
- Protected challenge state хранится только на сервере; клиент не решает
  outcome; время браузера не авторитетно.
- Каждый state-changing endpoint требует player identity и idempotency key.
- Технический сбой без committed outcome не расходует попытку; retry с тем же
  ключом возвращает прежний результат.
- Серверный timeout attempt обязан быть идемпотентным.
- ROOT — integer atomic units; float запрещён для balances, prices, rewards и
  multipliers.
- Event types: `credited`, `consumed`, `reserved`, `released`; signed non-zero
  delta; uniqueness constraint работает как idempotency guard.
- Критическая мутация `PlayerItem.quantity` недопустима без matching event в
  той же транзакции.
- Старт запрещён, пока не выполнены все entry requirements; executor не
  покупает и не подставляет предметы.
- CMS lifecycle и runtime state разделены.
- Повторяемость — validated mission-level CMS policy; глобального hardcoded
  правила нет.

### 6.2 Решения реализации

1. **Legacy-валидатор в новую вертикаль не переносится.** Единственный
   `challengeType` версии 1 — `cipher`; он читается из `challenge_policy_json` и
   `protected_challenge_snapshot`. Второй путь валидации внутри одного executor
   не заводится.

2. **`selection` передаёт те же display-строки, что видит игрок.** Сравнение —
   поэлементное, точное, без нормализации; сервер требует
   `len(selection) == drumCount`. Уникальность `alphabet` проверяется CMS при
   публикации policy, включая регистрово-различающиеся и похожие символы.
   Контракты форму сравнения не определяют, поэтому это решение реализации.

3. **Все три active-run лимита проверяются в одной транзакции со стартом:**
   `missions.max_active_solo`, `missions.max_active_team`,
   `missions.max_active_global`. Не отдельным шагом и не в middleware.

4. **Запрет policy для Mission с `mission_type != 'solo'` обеспечивает
   CMS-валидатор, а не схема БД.** Кросс-табличный CHECK невозможен, триггер на
   двух СУБД избыточен для schema foundation. Следствие вынесено в §8.

5. **Открыто:** политика обновления `PlayerMission` как current projection при
   solo runtime flow (см. §5).

## 7. Разрывы, требующие закрытия в Stage 5

### 7.1 Границы валидации, не защищённые схемой БД

Таблица `mission_runtime_policies` принимает значения, запрещённые контрактом,
до появления CMS-валидатора.

| Правило контракта | Гарантия БД |
|---|---|
| `max_attempts` от 1 до 10 | только `>= 1` |
| `attempt_deadline_seconds` от 1 до 86400 | только `>= 1` |
| `repeatability_policy` ∈ {one_time, after_terminal, after_failure_only} | нет |
| JSON-схемы `schemaVersion=1` и их поля | нет |
| policy только для `mission_type='solo'` | нет |

Нижняя граница `max_attempts` подтверждается каталогом system settings
(`missions.default_max_attempts` от 1 до 10).

### 7.2 Поля ledger

`docs/economy-and-root-ledger.md` требует у проводки `direction`,
`balance_before`, `idempotency_key`, `initiated_by_type`, `initiated_by_id`.
Код создания проводок в `mission_engine.py` эти поля не заполняет. Требует
проверки, отсутствуют ли колонки или только их заполнение.

### 7.3 Multipliers и целочисленная арифметика

Каталог хранит multipliers как JSON с дробными значениями
(`[1.0, 0.5, 0.25]`), а контракты запрещают float для multipliers и требуют
детерминированной целочисленной арифметики. Нужна схема перевода
(например, целочисленные доли) и явное правило округления.

### 7.4 Валидация multipliers

`docs/system-settings.md` задаёт форму: ровно `default_max_attempts` чисел,
диапазон 0..1, невозрастающая последовательность, первое значение равно 1.0.
CMS-валидатор policy обязан следовать этой же форме, а не вводить собственную.

### 7.5 Идемпотентный timeout attempt

Контракт требует серверного механизма перевода `issued → timed_out`, который
не может повторно разрешить уже terminal attempt. Такого механизма нет.

### 7.6 Проекция `PlayerMission` и интеграция с bootstrap

См. §5 и §6.2 п.5.

### 7.7 Dialect-aware locking

`docs/mission-run-contract.md` требует «required locking semantics for the
database dialect». SQLite не поддерживает `SELECT ... FOR UPDATE`, PostgreSQL
поддерживает. Нужна dialect-aware схема блокировок, аналогично
dialect-aware миграциям.

## 8. Accepted risks

| Риск | Обоснование |
|---|---|
| Прямая SQL-вставка создаёт policy для не-solo Mission | цена отказа от триггера; риск ограничен административным доступом к БД |
| `fallback_policy_json` существует как nullable-колонка при требовании `null` в v1 | заложение на будущее, поле не читается кодом v1 |
| До появления CMS-валидатора таблица принимает значения вне контракта | см. §7.1, закрывается в Stage 5 |
| Без политики обновления проекции новый прогресс не виден в bootstrap | см. §5; для v1 ограничено исключением story_node reward |

## 9. Зависимость фронтенда от legacy submit

Маршрут `POST /api/v1/engine/missions/{mission_id}/submit` вызывается фронтендом:

- `src/api/engineApi.ts` — запрос;
- `src/hooks/useGameState.ts` — `submitMission`;
- `src/components/screens/TerminalScreen.tsx` — тип `text_answer`, поле `answer`;
- `src/components/screens/ScannerScreen.tsx` — тип `code_repair`, поле `sequence`.

Следствие: legacy-маршрут нельзя снимать до отдельной задачи по миграции
фронтенда. Новый cipher-flow потребует собственных экранов и другого контракта
ответа. Упоминание legacy-маршрута есть также в
`docs/segment-content-contract.md` — при деприкации документ подлежит ревизии.

## 10. Вне области Stage 4

Team sessions, geo/location proof, AR/QR, reservations, fallback offers и
purchases, entitlement creation, TON, Stars, transfers, withdrawals,
`story_node` reward через runtime settlement. Границы определены в
`docs/solo-mission-runtime-policy-contract.md`.

## 11. Не подтверждено этим анализом

- какой профиль БД использует запущенный backend в конкретный момент;
- полный набор колонок `wallet_transactions` и `inventory_events` (см. §7.2);
- наличие таблицы `coins` в SQLite (в PostgreSQL таблицы нет);
- причина расхождения `dist/` в репозитории со `src/`.

## 12. Наблюдения по существующим контрактам

Оба дефекта найдены при анализе и исправлены в этом же коммите.

- В `docs/mission-run-contract.md`, §Solo start transition, три пункта
  подряд были помечены «2»; шаги пронумерованы `1, 2, 3, 4, 5, 6, 7, 8, 9`.
- Там же, в блоке attempt lifecycle, закрывающая последовательность была
  приклеена к последней строке `-> timed_out`; блок кода не закрывался.

## 13. Следующий шаг

Stage 5 — CMS-валидатор policy и domain executors. Начинать с CMS-валидатора и
runtime read path для system settings: они не требуют изменений схемы и
закрывают §7.1, §7.4 и часть §8. Затем dialect-aware locking и idempotency-слой,
затем executors, затем идемпотентный timeout и политика проекции.
