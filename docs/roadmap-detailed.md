# Детальный план реализации ROOT Game

Нумерация шагов соответствует этапам дорожной карты. Статусы синхронизированы с `docs/audit-2026-10-04.md` и обновлением 2026-10-14 (Sprint 8.6.p–u закрыты).

## Уже сделано (не требует работ)

- Этап 1. Проектирование, документация, инвентаризация — ✅ готов
- Этап 2. Фундамент: супер-админ, permissions, approvals, audit, system settings — ✅ готов

---

## Этап 3. CMS игровых заданий — ✅ готов

Уже реализовано: Season, Chapter, StoryNode, Mission, MissionRequirement, MissionReward, Item + админ-роутеры + жизненный цикл draft → published → archived.

### ✅ Шаг 3.1: Модель Key
- **Что**: создать отдельную сущность ключа доступа.
- **Файлы**: файл моделей проекта.
- **Проверка**: создать запись Key через ORM.
- **Зависит от**: —
- **Риск**: низкий

### ✅ Шаг 3.2: Миграция для Key
- **Что**: миграция таблицы ключей.
- **Файлы**: папка alembic-миграций.
- **Проверка**: применить миграцию, проверить таблицу.
- **Зависит от**: 3.1
- **Риск**: низкий

### ✅ Шаг 3.3: Админ-роутер для Key
- **Что**: CRUD для ключей через админку.
- **Файлы**: файл роутера ключей.
- **Проверка**: создание/редактирование ключа через API.
- **Зависит от**: 3.1
- **Риск**: низкий

### ✅ Шаг 3.4: Модель RewardPool
- **Что**: пул случайных наград.
- **Файлы**: файл моделей проекта.
- **Проверка**: создать запись RewardPool.
- **Зависит от**: —
- **Риск**: низкий

### ✅ Шаг 3.5: Миграция для RewardPool
- **Что**: миграция таблицы пулов.
- **Файлы**: папка alembic-миграций.
- **Проверка**: применить миграцию.
- **Зависит от**: 3.4
- **Риск**: низкий

### ✅ Шаг 3.6: Админ-роутер для RewardPool
- **Что**: CRUD для пулов наград.
- **Файлы**: файл роутера пулов.
- **Проверка**: создание пула через API.
- **Зависит от**: 3.4
- **Риск**: низкий

### ✅ Шаг 3.7: Модель GeoZone
- **Что**: справочник геозон (radius/polygon/POI).
- **Файлы**: файл моделей проекта.
- **Проверка**: создать GeoZone.
- **Зависит от**: —
- **Риск**: низкий

### ✅ Шаг 3.8: Миграция и админ-роутер для GeoZone
- **Что**: миграция + CRUD для геозон.
- **Файлы**: папка миграций, файл роутера геозон.
- **Проверка**: создание геозоны через API.
- **Зависит от**: 3.7
- **Риск**: низкий

### ✅ Шаг 3.9: Модель ARObject
- **Что**: AR-объекты, привязанные к геозонам.
- **Файлы**: файл моделей проекта.
- **Проверка**: создать ARObject.
- **Зависит от**: 3.7
- **Риск**: низкий

### ✅ Шаг 3.10: Миграция и админ-роутер для ARObject
- **Что**: миграция + CRUD для AR-объектов.
- **Файлы**: папка миграций, файл роутера AR.
- **Проверка**: создание AR-объекта через API.
- **Зависит от**: 3.9
- **Риск**: низкий

### ✅ Шаг 3.11: Отключение demo-сида и удаление публичного reset-API
- **Что**: убрать автосоздание demo-контента при старте backend и убрать публичный эндпоинт сброса прогресса.
- **Файлы**: скрипт сида, роутер reset-API, файл запуска backend.
- **Проверка**: рестарт backend не создаёт demo-сущностей; эндпоинт сброса возвращает 404.
- **Зависит от**: 3.1–3.10
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ (есть данные в БД, нужен backup и план отката)

### Уже сделано (обновлено 2026-10-05)

- **3.1** Модель `KeyRules` в `backend/app/models.py`.
- **3.2** Миграция `357b704e50ff_add_key_rules_table` (SQLite + PostgreSQL).
- **3.2.1** Миграция `481081d0694d_add_key_rules_admin_permissions` (permissions `key_rules.read`, `key_rules.manage`, category=economy).
- **3.3** Роутер `backend/app/admin_key_rules.py` (4 эндпоинта: GET list, GET one, POST, PATCH).
- **3.3.4** Тесты `backend/tests/test_admin_key_rules.py` (10 тестов).
- **3.4** Модели `RewardPool` и `RewardPoolEntry` в `backend/app/models.py`.
- **3.5** Миграция `8f098e3e0a63_add_reward_pools_tables` (SQLite + PostgreSQL).
- **3.6** Роутер `backend/app/admin_reward_pools.py` (4 эндпоинта: GET list, GET one, POST, PATCH). Permissions `reward_pools.read`, `reward_pools.manage` (category=economy) — миграция `a9d4e2b8c7f1`. Тесты `backend/tests/test_admin_reward_pools.py` (18 тестов).
- **3.7** Модель `GeoZone` в `backend/app/models.py`.
- **3.8** Миграции `a1d2aafc3d3b_add_geo_zones_table` и `38f24f405a8b_add_geo_zones_admin_permissions` (SQLite + PostgreSQL). Permissions `geo_zones.read`, `geo_zones.manage` (category=geo).
- **3.8.9** Роутер `backend/app/admin_geo_zones.py` (4 эндпоинта, cross-field-валидация geometry). Тесты `backend/tests/test_admin_geo_zones.py` (26 тестов).
- **3.9** Модель `ARObject` в `backend/app/models.py` (FK `geo_zone_id → geo_zones.id` с `ondelete=RESTRICT`).
- **3.10** Миграции `f1ab8ea28db5_add_ar_objects_table` и `15ed269093cb_add_ar_objects_admin_permissions` (SQLite + PostgreSQL). Permissions `ar_objects.read`, `ar_objects.manage` (category=content).
- **3.10.8** Роутер `backend/app/admin_ar_objects.py` (4 эндпоинта, cross-field валидация окна доступности). Тесты `backend/tests/test_admin_ar_objects.py` (25 тестов).
- **3.11.a** Удалён публичный reset-endpoint `POST /api/v1/engine/reset-demo-progress` (backend + frontend). Кнопка «Остановить сессию» переделана на локальный выход без потери прогресса.
- **3.11.b** Удалён мёртвый код `reset_demo_engine_progress` из `mission_engine.py` (-42 строки). `seed.py` оформлен как dev-инструмент: production guard (`APP_ENV=production`), явный docstring.
- **3.11.c** Синхронизированы docs: `api-contracts.md`, `roadmap.md` §2.4, `stage-4-gap-analysis.md`, `system-settings.md`, `system_settings_catalog.py`.

Все проверки: 134/134 unit-тестов, эндпоинты зарегистрированы в OpenAPI, миграции применены к SQLite и PostgreSQL. Публичный reset-endpoint удалён, `seed.py` защищён production guard.

### Шаг 3.12: Переопределение Segment как Part (переименование в UI и API)
- **Что**: Segment функционально становится Part (эпизод внутри Chapter). Поля location и arScene переезжают на Mission через FK на GeoZone и ARObject (см. Этап 8). В БД таблица остаётся segments (для совместимости), но в admin UI и клиенте везде «Часть» / «Part».
- **Файлы**: `backend/app/admin_segments.py`, `src/AdminApp.tsx`, `src/api/adminApi.ts`, `src/api/engineApi.ts`.
- **Проверка**: admin UI показывает «Части», старые URL работают, ничего не сломано.
- **Зависит от**: — (можно делать параллельно со Спринтом 8.1).
- **Риск**: средний, требует согласования (затрагивает 4 слоя).

---

## Этап 4. Инвентарь и ключи — ✅ готов

Уже реализовано: Item, Inventory, выдача наград, таблицы резервов и событий инвентаря, fallback-награды.

### ✅ Шаг 4.0: Admin-API для MissionRuntimePolicy
- **Что**: CRUD + publish/unpublish/archive для правил входа миссии.
- **Файлы**: новый `backend/app/admin_mission_runtime_policies.py`,
  регистрация в `main.py`, тесты `backend/tests/test_admin_mission_runtime_policies.py`.
- **Проверка**: через API создать policy, опубликовать, получить.
- **Зависит от**: — (модель `MissionRuntimePolicy`, миграция `3a9e1c7d5f24`
  и контракт `runtime_policy_contract.py` уже готовы).
- **Риск**: низкий.

### ✅ Шаг 4.1: Списание ключа и ROOT-взноса при взятии миссии
- **Что**: при принятии миссии атомарно списывать ключ и entry_fee_root.
- **Файлы**: движок миссий, модели.
- **Проверка**: взять миссию с ключом и ROOT-взносом; баланс уменьшился, ключ исчез из инвентаря.
- **Зависит от**: 3.1, 9.x (ledger уже работает)
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Уже сделано (обновлено 2026-10-06)

- **4.1** `_consume_entry_resources` в `backend/app/mission_engine.py`:
  атомарное списание ROOT (`WalletTransaction`, `transaction_type="debit"`,
  `reference_type="mission_entry_debit"`) и расходуемых ключей
  (`InventoryEvent(event_type="consumed")`, `reference_type="mission_entry"`)
  при взятии миссии. Проверки: баланс → наличие/количество ключей →
  `Item.status == "published"`; порядок списания: ROOT → ключи. Legacy-миссии
  без published policy — проход без действий. Идемпотентность — уникальные
  индексы ledger + retry `submit_mission`. `409` при нехватке ресурсов.
  Тесты `backend/tests/test_mission_engine_integration.py` (7 кейсов, 4.1.1–4.1.7).
- **4.2** Инвариант «ключ не возвращается» зафиксирован тестами в
  `test_mission_engine_integration.py` (4 кейса: 4.2.1–4.2.4). Нового кода не
  требовалось: списание из 4.1 не откатывается никакими функциями, ledger
  immutability защищена DB-триггерами (`0b9e7c6d5a41`, `2f7a9c4e6d81`).
  Сценарии отмены/блокировки/экспайри — этапы 5/6. Ручная компенсация — 5.4/5.5.
- **4.3a** (часть 4.3, применено 2026-10-06) персональный fallback-entitlement
  после **первого неверного ответа**: новый `backend/app/fallback_shop.py`
  (`create_first_failure_entitlement`), вызов в `mission_engine._submit_mission_once`
  только в ветке `not _validate_submission(...)` и после
  `_consume_entry_resources`. V1 semantics (`docs/fallback-shop-contract.md`):
  eligible без paid policy, распространяется и на бесплатные legacy-миссии.
  Параметры `shop.fallback.*` читаются из system_settings (data-миграция
  `07131ffe9d13` сидит 4 ключа, `downgrade` намеренно не реализован —
  append-only). Схема не менялась: `player_fallback_entitlements` уже есть
  (`2f7a9c4e6d81`). Идемпотентность — unique `(player_id, mission_id)` +
  guard `attempt_count_before == 0`. Покупка ключа и пул — шаг 4.4. Тесты
  `backend/tests/test_fallback_shop.py` (9 кейсов 4.3a.1–4.3a.9 + 2 unit-теста
  `validate_value` для типа `string`).
- **4.3b** (часть 4.3, применено 2026-10-06) player-facing
  `GET /api/v1/engine/fallback-offers` — персональная проекция офферов после
  первого провала: презентер `build_fallback_offers` + обёртка
  `get_fallback_offers` в `backend/app/fallback_shop.py`, тонкий роут в
  `main.py` (rate limit 10/minute, `Depends(get_current_player_id)`).
  Response `{"offers": [...]}` без цены (price приходит с продуктом в 4.4);
  `shop.fallback.enabled=False` → `[]`; item не published / KeyRules удалён →
  presentation `status="disabled"` (derived, без записи в БД). Тесты
  `backend/tests/test_fallback_shop.py` (7 кейсов 4.3b.1–4.3b.7).

### ✅ Шаг 4.2: Логика «ключ не возвращается»
- **Что**: во всех сценариях (отмена, провал, блокировка) ключ не возвращается, кроме ручной компенсации через админку.
- **Файлы**: движок миссий.
- **Проверка**: попытка возврата ключа через отмену — ключ не вернулся.
- **Зависит от**: 4.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### ⏳ Шаг 4.3: Логика создания персонального предложения после первого провала
- **Что**: после первого провала игрока создавать персональное предложение магазина на ключ-награду.
- **Файлы**: сервис миссий, сервис магазина.
- **Проверка**: провал первой попытки → в БД появилась запись предложения только для этого игрока.
- **Статус**: 4.3a ✅ 2026-10-06 (entitlement после первого провала) и 4.3b ✅
  2026-10-06 (`GET /api/v1/engine/fallback-offers`) — оба см. «Уже сделано».
  Заголовок остаётся ⏳: 4.3 как единое целое (личный магазин ключа)
  закрывается после 4.4, когда покупка завершит цикл
  «миссия → провал → оффер → покупка».
- **Зависит от**: 4.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### ✅ Шаг 4.4: Логика покупки из персонального магазина
- **Что**: покупка ключа за ROOT с проверкой лимитов и идемпотентности.
- **Файлы**: сервис магазина, ledger.
- **Проверка**: покупка проходит, ключ выдан, баланс уменьшен, проводка в ledger.
- **Зависит от**: 4.3
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Уже сделано (обновлено 2026-10-07)

- **4.4** `purchase_fallback_offer` в `backend/app/fallback_shop.py`:
  атомарная покупка fallback-ключа за ROOT в одной транзакции.
  `POST /api/v1/engine/fallback-offers/{offer_id}/purchases` — путевой параметр
  исторически назван `offer_id`, но адресует `entitlement.id` (GET отдаёт его
  как `entitlementId`; `offer_id` у одного игрока не уникален). Цена —
  `shop.fallback.default_price_root` (5-й ключ, data-миграция `1c439c558aa7`,
  дефолт 100 atomic units). Идемпотентность — `reference_id = "{entitlement.id}:{run_entry_count}:{n}"` (run_entry_count — номер захода, Sprint 8.17.8)
  + unique-индексы WalletTransaction/InventoryEvent; повторный POST возвращает
  committed-результат. Порядок в транзакции: entitlement FOR UPDATE → enabled →
  ключ published/KeyRules → цена → идемпотентный возврат → статус → квота →
  wallet FOR UPDATE → баланс → debit → PlayerItem upsert + InventoryEvent
  `credited` → consumed_count++/exhausted. Пул/mode/expiry не реализованы
  (по контракту). Без `admin_audit` (player-операция), только structured logger.
  Тесты `backend/tests/test_fallback_shop.py` (10 кейсов 4.4.1–4.4.10).
  Покупка здесь — первая покупка проекта: закрывает контрактный гэп, когда
  mission reward upsert'ил PlayerItem без InventoryEvent.

- **5.3** read-only админ-эндпоинты игроков (`backend/app/admin_players.py`):
  `GET /api/v1/admin/players` — список с фильтрами `search` (ilike по username/
  display_name/first_name), `status`, `authProvider` и пагинацией `limit`/`offset`
  (default 50, max 200); `GET /api/v1/admin/players/{player_id}` — полная карточка:
  `player` (external_id показывается полностью, `lastActivityAt = updated_at`,
  приблизительно), `wallet` (нули, если нет), `inventory` (batch JOIN c Item,
  quantity > 0), `activeMissions` (in_progress/available), `missionHistory` (только
  completed, limit 10), `restrictions` (active сверху, limit 20),
  `recentTransactions` (limit 20, metadata через `sanitize_audit_data`), `stats`
  (totalMissionsCompleted, totalRootEarned, totalRootSpent). Оба эндпоинта требуют
  прямое право `players.read`, read-only сессия без `begin()`. Миграция
  `92aa64e01b1a` добавила 4 права категории `players` (read/manage/restrict/block).
  Тесты `backend/tests/test_admin_players.py` (10 unit-кейсов, fake-session без БД).

---

## Этап 5. Карточка игрока, ручные операции, ограничения — 🔄 в работе

### Шаг 5.1: Модель PlayerRestriction
- **Что**: ограничения игрока (suspended, transfer_restricted, mission_restricted и др.) с reason, admin_id, expires_at.
- **Файлы**: файл моделей.
- **Проверка**: создать ограничение через ORM.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 5.2: Миграция для PlayerRestriction
- **Что**: таблица ограничений.
- **Файлы**: папка миграций.
- **Проверка**: применить миграцию.
- **Зависит от**: 5.1
- **Риск**: низкий

### ✅ Шаг 5.3: Админ-роутер «Карточка игрока»
- **Что**: read-only эндпоинты `GET /api/v1/admin/players` (список с фильтрами
  `search`/`status`/`authProvider` и пагинацией `limit`/`offset`) и
  `GET /api/v1/admin/players/{id}` (карточка: баланс, инвентарь, миссии, история,
  ограничения, проводки, статистика).
- **Файлы**: `backend/app/admin_players.py`, миграция `92aa64e01b1a` (права `players.*`).
- **Проверка**: ✅ выполнено — `backend/tests/test_admin_players.py` (10 unit-кейсов).
- **Зависит от**: 5.1
- **Риск**: низкий

### ✅ Шаг 5.4: Ручные операции — начислить/списать ROOT
- **Что**: `POST /api/v1/admin/players/{id}/wallet-adjustment` — начисление/списание ROOT
  с причиной, idempotency `request_id` и аудитом; прямое исполнение при direct-grant и сумме
  ниже `economy.manual_adjustment_approval_threshold` (иначе создаётся approval-заявка).
  Dedicated executor `POST /api/v1/admin/players/wallet-adjustment-requests/{approval_id}/execute`
  — только super-admin, только `player.wallet_credit|player.wallet_debit`.
- **Файлы**: `backend/app/admin_player_wallet.py`, регистрация в `main.py`.
- **Проверка**: ✅ выполнено — `backend/tests/test_admin_player_wallet.py` (18 unit-кейсов).
- **Зависит от**: 5.3
- **Риск**: средний (согласовано в рамках плана 5.4)

### ✅ Шаг 5.5: Ручные операции — выдать/отозвать ключ
- **Что**:
  - `POST /api/v1/admin/players/{id}/inventory-item-adjustment` (`direction=grant|revoke`,
    `item_id`, `quantity`, `reason`, `request_id`) — ручная выдача/отзыв предмета.
    Direct 200 при direct-grant и количестве ниже
    `gameplay.manual_item_adjustment_approval_threshold`, иначе 201 (approval-заявка);
  - `POST /api/v1/admin/players/inventory-item-adjustment-requests/{approval_id}/execute` —
    только super-admin, только `player.inventory_grant|player.inventory_revoke`;
  - ledger: immutable `InventoryEvent`, `event_type=credited|consumed`,
    `reference_type=admin_item_grant|admin_item_revoke`, `reference_id=request_id`;
    новая строка `PlayerItem` — `obtained_from_type="admin_manual"`,
    `obtained_from_id=request_id`. Grant требует `Item.status == "published"`; revoke — только
    существующий `PlayerItem` и достаточное количество. Player-ограничения
    (`sale_forbidden`/`transfer_forbidden`/`trade_forbidden`/`stack_limit`/`is_consumable`)
    админ-операции не блокируют.
- **Файлы**: `backend/app/admin_player_inventory.py`, регистрация в `main.py`,
  новый SystemSetting `gameplay.manual_item_adjustment_approval_threshold`.
- **Проверка**: ✅ выполнено — `backend/tests/test_admin_player_inventory.py` (15 unit-кейсов).
- **Зависит от**: 5.3
- **Риск**: средний (согласовано в рамках плана 5.5)

### Уже сделано (обновлено 2026-10-07)
- ✅ 5.4 Ручные начисление/списание ROOT:
  - `POST /api/v1/admin/players/{id}/wallet-adjustment` — direct 200 при
    direct-grant + сумма < порога, иначе 201 (approval-путь);
  - `POST /api/v1/admin/players/wallet-adjustment-requests/{approval_id}/execute` —
    только super-admin, только `player.wallet_credit|player.wallet_debit`;
  - ledger: immutable `WalletTransaction`, `transaction_type=credit|debit`,
    `amount>0`, `reference_type=admin_credit|admin_debit`, `reference_id=request_id`;
  - идемпотентность по `request_id` (заявки и проводки), 409 при конфликте содержимого;
  - аудит `write_admin_audit` без sensitive-данных; reason в ledger ≤ 255,
    полная причина — в `metadata_json["fullReason"]`;
  - тесты: `backend/tests/test_admin_player_wallet.py` (18 unit-кейсов).
- ✅ 5.5 Ручная выдача/отзыв ключа:
  - `POST /api/v1/admin/players/{id}/inventory-item-adjustment` — direct 200 при
    direct-grant + количество < порога, иначе 201 (approval-путь);
  - `POST /api/v1/admin/players/inventory-item-adjustment-requests/{approval_id}/execute` —
    только super-admin, только `player.inventory_grant|player.inventory_revoke`;
  - ledger: immutable `InventoryEvent`, `event_type=credited|consumed`,
    `reference_type=admin_item_grant|admin_item_revoke`, `reference_id=request_id`;
  - новая строка `PlayerItem` — `obtained_from_type="admin_manual"`, `obtained_from_id=request_id`;
  - grant требует `published`; revoke — существующий `PlayerItem` + достаточное количество;
    идемпотентность по `request_id` (UNIQUE на события и заявки), 409 при конфликте содержимого;
  - аудит `write_admin_audit`; execution_failed с `execution_error`-строкой и ответом 409;
  - тесты: `backend/tests/test_admin_player_inventory.py` (15 unit-кейсов).

### Шаг 5.6: Ручные операции — отменить/завершить миссию
- **Что**: снять игрока с миссии, отменить, принудительно завершить.
- **Файлы**: роутер админ-операций, движок миссий.
- **Проверка**: изменения отражаются в состоянии миссии и аудите.
- **Зависит от**: 5.3
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

Подшаги:
- **5.6.a — mission-cancel** ✅: `POST .../missions/{mission_id}/mission-cancel`
  (+ `/mission-cancel-requests/{approval_id}/execute`), статус `cancelled` (terminal),
  guards в `_synchronize_player_missions`/`_submit_mission_once`, идемпотентность
  через admin_audit_log (вариант B), audit entity_type=player_mission, без
  порога-магнитуды (чувствительность — execution-режим `players.manage`).
  Тесты: `backend/tests/test_admin_player_mission.py` (23 unit-кейса).
- ✅ 5.6.b Принудительное завершение миссии:
  - `POST /api/v1/admin/players/{id}/missions/{mission_id}/mission-force-complete` —
    direct 200 при direct-grant (super-admin или магнитуда < порога), иначе 201 (approval-путь);
  - порог-магнитуда — суммарные ROOT-награды миссии, настройка
    `economy.mission_force_complete_approval_threshold` (default 5000, System Settings);
  - статус `completed` из `available`/`in_progress`/`locked`; награды опционально
    (`awardRewards`, ROOT — ledger-idempotent), entry-ресурсы не возвращаются,
    `rewardSkipped`/`entryConsumed` в аудите;
  - `POST /api/v1/admin/players/mission-force-complete-requests/{approval_id}/execute` —
    только super-admin, только `player.mission_force_complete`;
  - идемпотентность через immutable admin_audit_log (replay из metadata_json);
  - тесты: `backend/tests/test_admin_player_mission.py` (43 unit-кейса, включая 5.6.a).
- **5.6.b — mission-force-complete** ✅: `POST .../missions/{mission_id}/mission-force-complete`
  (+ `/mission-force-complete-requests/{approval_id}/execute`), статус `completed` из
  `available`/`in_progress`/`locked`, опциональная выдача наград (`awardRewards`; ROOT —
  ledger-idempotent), порог-магнитуда (суммарные ROOT-награды миссии)
  `economy.mission_force_complete_approval_threshold` (default 5000, CMS/System Settings,
  super-admin исполняет напрямую), идемпотентность через admin_audit_log
  (replay: awardedRoot/awardedItems/awardedStoryNodeIds/rewardSkipped/entryConsumed).
- **5.6.c — attempts-adjustment** ✅: `POST .../missions/{mission_id}/attempts-adjustment`
  (+ `/attempts-adjustment-requests/{approval_id}/execute`), абсолютная установка `attempt_count`
  (`new_attempt_count` в `[0, 1000]`, не дельта); изменяется только `attempt_count`
  (`status`/`started_at`/`progress` не трогаются); direct/approval по гранту `players.manage`
  (порога-магнитуды нет: super-admin в direct исполняет сразу); терминальные статусы — 409,
  replay через immutable admin_audit_log — 200 idempotent; `new == old` — `changed: false`
  (аудит пишется); fallback-семантика `0` описана в api-contracts.
- **5.6.d — manual reward endpoint** ❌ не делаем: покрывается 5.4/5.5. Известное
  ограничение: `MissionReward.story_node_id` не покрывается 5.4/5.5 — фиксируется
  документально, отдельная работа не планируется.

### Шаг 5.7: Управление ограничениями игрока через админку — ✅ сделано

- `POST /api/v1/admin/players/{id}/restrictions` — создать ограничение
  (chat/transfer/team/mission/payment/withdrawal_restricted, suspended, blocked)
  с причиной, окном действия и аудитом. Direct 200, approval-путь 201
  (`player.restriction_create`). Permission от типа: `blocked`/`suspended` →
  `players.block`, остальные → `players.restrict`. Активное ограничение того же
  типа → 409; replay по `request_id` из immutable admin_audit_log → 200 idempotent.
- `POST /api/v1/admin/players/restriction-requests/{approval_id}/execute` —
  только super-admin, только `player.restriction_create`.
- `POST /api/v1/admin/players/{id}/restrictions/{restriction_id}/revoke` — снять
  (active → revoked) с причиной и аудитом; снятие снятого/истёкшего: replay →
  200 idempotent, иначе 409. Permission — от типа снимаемого ограничения.
- `POST /api/v1/admin/players/restriction-revoke-requests/{approval_id}/execute` —
  только super-admin, только `player.restriction_revoke`.
- Синхронизация: `GamePlayer.status` — кэш-агрегат, пересчитывается ВСЕГДА при
  create/revoke (write-through) через `player_restrictions_engine.recompute_player_status`;
  lazy-expiry просроченных ограничений без фоновых джобов; lazy-рикавери
  запирающих ограничений в auth-гейтах (`get_current_player_id`,
  `_upsert_telegram_player`, `mission_engine._ensure_player`).
- Тесты: `backend/tests/test_admin_player_restrictions.py` (21 кейс: fake-session
  endpoints + real SQLite/alembic для кэша статуса, lazy expiry и гейтов).

### Уже сделано (обновлено 2026-10-08)
- ✅ 5.7 управление ограничениями игрока через админку (см. шаг 5.7 выше):
  создание/снятие с approval-workflow, идемпотентность по request_id,
  права `players.block`/`players.restrict`, write-through синхронизация
  `GamePlayer.status`, lazy-expiry и lazy-рикавери гейтов; аудит без
  sensitive-данных в immutable admin_audit_log.
- ✅ Datetime-fix (pre-existing bug): naive-datetime из SQLite нормализуется
  в UTC через `app/datetime_utils.ensure_utc` в 6 старых executor'ах
  (wallet/inventory/mission/system_settings/approvals). До этого `execute`
  заявки с `expires_at` на dev падал с TypeError.

---

## Этап 6. Команды, приглашения, состав, чат — 🔄 в работе

### ✅ Шаг 6.1: Модель Team
- **Что**: постоянная сущность команды.
- **Файлы**: файл моделей.
- **Проверка**: создать Team.
- **Зависит от**: —
- **Риск**: низкий

### ✅ Шаг 6.2: Модели TeamMember, TeamInvitation, TeamJoinRequest, TeamMembershipHistory
- **Что**: состав команды, приглашения, заявки, история.
- **Файлы**: файл моделей.
- **Проверка**: создать связанные записи.
- **Зависит от**: 6.1
- **Риск**: низкий

### ✅ Шаг 6.3: Миграция для командных таблиц
- **Что**: миграция всех командных сущностей.
- **Файлы**: папка миграций.
- **Проверка**: применить миграцию.
- **Зависит от**: 6.2
- **Риск**: низкий

### ✅ Шаг 6.4: Логика создания команды и вступления
- **Что**: создание команды, выход, исключение, передача лидерства, расформирование.
- **Файлы**: сервис команд.
- **Проверка**: сценарии вступления/выхода/расформирования.
- **Зависит от**: 6.3
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Уже сделано (обновлено 2026-10-08)
- ✅ 6.1/6.2/6.3 модели Team + состав + история + миграция (см. выше).
- ✅ 6.4 player-facing командный сервис `backend/app/teams_service.py`:
  create/me/get/update (только лидер), join (open-only; заявки/приглашения —
  шаг 6.5), leave, kick, transfer-leadership, disband. Инвариант «одна активная
  команда на игрока» — через unique-индекс `uq_team_members_active_player` +
  сервисный guard 409. Повторное вступление реактивирует прежнюю запись
  (uq_team_members_team_player, без дублей). Правило 5.3: leave/disband
  заблокированы (409), пока игрок/любой участник в активной командной миссии
  (`team_sessions.status` in collecting/ready_to_start/active). Лидер не может
  выйти — только передать лидерство или disband. История состава immutable.
- 9 эндпоинтов в `backend/app/main.py` (+ Pydantic-схемы, rate limit
  10/minute, MissionEngineError → HTTPException); контракты в
  `docs/api-contracts.md`. Admin-модерация команд (просмотр/принудительный
  disband) — шаг 6.7. Чат — не в 6.4 (шаг 6.6).
- Тесты: `backend/tests/test_teams_service.py` (21 кейс, disposable SQLite
  через alembic upgrade head, патч SessionLocal).
- ✅ 6.5 приглашения и заявки (см. шаг 6.5 выше): invite/accept/reject/cancel,
  join-request/approve/reject/cancel, списки (мои / команды). Все 11 маршрутов
  в `backend/app/main.py` с rate limit 10/minute и `MissionEngineError →
  HTTPException`; `_join_team` для by_request/invite_only возвращает точные
  указания маршрутов. Ленивый expire приглашений (SQLite-safe naive/aware через
  `ensure_utc`), partial-unique pending-индексы на уровне БД. Тесты: те же
  `test_teams_service.py`, 21 кейс 6.4 сохранён + 25 новых (46 всего OK).

### ✅ Шаг 6.5: Логика приглашений и заявок
- **Что**: приглашение по ссылке, заявка на вступление, approve/reject.
- **Файлы**: сервис команд.
- **Проверка**: приглашение принято, заявка одобрена.
- **Зависит от**: 6.4
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ
- **Реализовано 2026-10-08**: приглашения (invite/accept/reject/cancel лидера)
  и заявки (create/cancel автора, approve/reject лидера, список заявок команды)
  в `backend/app/teams_service.py` + 11 player-facing эндпоинтов в
  `backend/app/main.py`. `joinPolicy` закрыт: open → POST /join; by_request →
  POST /join-requests; invite_only → только invite лидера. TTL инвайтов
  по умолчанию 72 ч с переопределением через system setting `invite.ttl_hours`
  (CMS-first). Ленивый expire, partial-unique pending-индексы, реактивация
  прежней TeamMember (без дублей), immutable history с метаданными via.
  Контракты — `docs/api-contracts.md`; тесты — `backend/tests/test_teams_service.py`.

### Шаг 6.6: Модель командного сообщения и логика чата
- **Что**: сообщения команды, системные события, жалобы, мут, заморозка чата.
- **Файлы**: файл моделей, сервис чата.
- **Проверка**: отправка сообщения, скрытие модератором.
- **Зависит от**: 6.4
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 6.7: Админ-роутер для команд и чата

#### ✅ Шаг 6.7.a: Admin teams (без чата)
- **Что**: просмотр команд, состава, истории, приглашений, заявок;
  force-disband и force-kick через direct или approval;
  dedicated executors для approved-заявок.
- **Файлы**: `backend/app/admin_teams.py`, миграция
  `6aff0c05e0c7_add_team_admin_permissions.py` (создаёт permissions
  `teams.read`, `teams.manage`), 10 эндпоинтов, подключены в `main.py`.
- **Проверка**: `Ran 16 tests ... OK` (test_admin_teams.py).
- **Зависит от**: 6.4
- **Риск**: низкий

#### ❌ Шаг 6.7.b: Модерация чата
- **Что**: admin-просмотр сообщений, скрытие/удаление, мут, жалобы,
  журнал модерации.
- **Зависит от**: 6.6
- **Риск**: средний

---

## Этап 7. Командные задания и совместная геоактивация — ⚠️ в работе

Уже: сессии команд, проверка присутствия, попытки, расчёты наград, политики runtime, тесты.

### Шаг 7.1: Подключить командные сессии к API
- **Что**: API для создания командной миссии, подтверждения присутствия, индивидуального прохождения.
- **Файлы**: роутер командных миссий, движок миссий.
- **Проверка**: команда активирует миссию в геозоне, каждый проходит индивидуально.
- **Зависит от**: 6.4, 3.7
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 7.2: Настройка политик командного выхода при активной миссии
- **Что**: игрок не может выйти из команды во время активной командной миссии, кроме ручного действия администратора.
- **Файлы**: сервис команд, движок миссий.
- **Проверка**: попытка выхода во время активной миссии блокируется.
- **Зависит от**: 7.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

---

## Этап 8. Гео-AR пайплайн — ⚠️ в работе (8.6 Content UX закрыт 2026-10-14; 8.13 Cipher закрыт 2026-10-16; 8.14 Multi-run в работе)

Базовая механика игры: игрок берёт задание → на карте появляется зона → идёт к ней → сканер показывает направление → камера + AR-куб с QR → мини-игра. Миссии без гео-AR пайплайна игроку не выдаются. Работаем вертикальными срезами: каждый спринт = БД + API + admin UI + client UI + проверка.

Политика локации: GPS-only (navigator.geolocation), IP не используется. VPN игрока не влияет на место миссии — оно всегда определяется по реальным координатам.

### Спринт 8.0. Политика локации и подготовка ✅ решение принято
- GPS через navigator.geolocation, IP игнорируется.
- Random spawn только в радиусе от GPS-точки игрока.
- Индивидуальный QR генерируется на сервере (HMAC от player_id + mission_id + nonce + timestamp), не существует как физическая наклейка.
- Связь с античитом — отдельно, в 8.9.

### Спринт 8.1. Mission ↔ GeoZone (FK) — вертикальный срез ✅
- **Статус**: ✅ (2026-10-14) — миграция 30116c3d9ae6, Mission.geo_zone_id (FK) + admin UI dropdown GeoZone в редакторе Mission.
- **БД:** миграция: Mission.geo_zone_id (FK → geo_zones.id, nullable → потом обязательный для published).
- **Backend:** включить geo_zone_id в admin_missions payload; обновить _validate_for_publish.
- **Admin UI:** dropdown GeoZone в редакторе Mission.
- **Client UI:** показ зоны на карте Leaflet+OSM.
- **Проверка:** миссия с зоной видна на карте у игрока.

### Спринт 8.2. Random spawn по GPS — вертикальный срез ⚠️ частично
- **Статус**: ⚠️ частично — accept_mission уже принимает GPS и хранит spawn в PlayerMission.progress; отдельная таблица MissionSpawn не сделана.
- **БД:** модель MissionSpawn (player_id, mission_id, center_lat, center_lng, radius_meters, generated_at, expires_at).
- **Backend:** POST /api/v1/engine/missions/{id}/accept — принимает GPS-координаты игрока, генерирует spawn в радиусе N от точки. N — настройка в Mission.
- **Admin UI:** параметры spawn в редакторе Mission (радиус разброса).
- **Client UI:** запрос GPS, отправка на сервер, получение spawn.
- **Проверка:** зона появляется рядом с игроком, не зависит от VPN.

### Спринт 8.3. Mission ↔ ARObject (FK) — вертикальный срез ✅
- **Статус**: ✅ (2026-10-14) — Mission.ar_object_id (FK) + admin UI dropdown ARObject.
- **БД:** миграция: Mission.ar_object_id (FK → ar_objects.id).
- **Backend:** включить ar_object_id в payload.
- **Admin UI:** dropdown ARObject в редакторе Mission.
- **Client UI:** показ AR-маркера поверх зоны.
- **Проверка:** игрок видит точку AR-объекта.

### Спринт 8.4. Сканер направления — вертикальный срез ⚠️ частично
- **Статус**: ⚠️ частично — EchoRadar работает (компас + дистанция до зоны), но без полной спецификации из roadmap.
- **Backend:** GET /api/v1/engine/missions/{id}/spawn — отдаёт центр зоны, расстояние, направление.
- **Admin UI:** — (без изменений).
- **Client UI:** экран сканера с компасом и расстоянием.
- **Проверка:** сканер показывает направление до точки.

### Спринт 8.5. LocationProof в solo-flow — вертикальный срез ⏳
- **Статус**: ⏳ не начат — LocationProof работает только в team-flow; в solo-flow не перенесён.
- **БД:** переиспользовать LocationProof (уже есть в geo_team_runtime_models.py).
- **Backend:** перенести логику проверки присутствия из team_missions_service в mission_engine; POST /api/v1/engine/missions/{id}/location-proof; проверка accuracy, freshness, расстояния.
- **Admin UI:** настройки точности (max_location_accuracy_meters, minimum_presence_seconds) в GeoZone.
- **Client UI:** фоновая отправка координат при движении.
- **Проверка:** сервер принимает доказательства только от игрока в зоне.

### Cleanup после Sprint 8.4.f

- **Что**: удалить временный dev-компонент `src/components/DevAcceptMissionButton.tsx` и его рендер в `src/App.tsx` (строка с `{import.meta.env.DEV && <DevAcceptMissionButton />}`).
- **Причина**: временная кнопка для проверки accept на телефоне (Sprint 8.4.f). В production не появляется (защита через `import.meta.env.DEV`), но код нужно удалить.
- **Как найти**: `grep -rn "DevAcceptMissionButton" src/`.
- **Проверка**: после удаления `npm run build` зелёный, `grep -rn "DevAcceptMissionButton" src/` пуст.
- **Статус**: ✅ done (2026-10-13), кнопка удалена в Sprint 8.5.f.

### Спринт 8.6. AR-камера + куб — ✅ реализовано (см. Спринт 8.6 — Content UX ниже)
- **Backend:** — (без изменений).
- **Client UI:** WebXR/Three.js: рендер куба в камере телефона, привязка к координатам.
- **Проверка:** куб виден в AR-камере рядом с точкой.

### Спринт 8.7. Индивидуальный QR — вертикальный срез ✅
- **Статус**: ✅ (2026-10-14) — полный цикл: HMAC-пейлоад, рендер QR на кубе, scan-qr, запуск мини-игры.
- **Backend:** GET /api/v1/engine/missions/{id}/qr-payload — генерирует {payload, hmac, expires_at}; HMAC от (player_id + mission_id + nonce + timestamp).
- **Client UI:** рендер QR на гранях куба (например, через qrcode.react).
- **Проверка:** каждый игрок видит свой QR; скриншот другого игрока не сработает.

### Спринт 8.8. QR-скан + запуск мини-игры — вертикальный срез ⚠️ частично
- **Статус**: ⚠️ частично — POST /scan-qr работает и возвращает ответ сервера, но мини-игра не запускается как отдельный экран.
- **Backend:** POST /api/v1/engine/missions/{id}/scan-qr — принимает {payload, hmac}, проверяет HMAC + принадлежность + свежесть + наличие свежего LocationProof; возвращает mini-game config.
- **Client UI:** QR-scanner через камеру (getUserMedia или встроенный API).
- **Проверка:** после скана запускается мини-игра (text_answer / code_repair / cipher / team).

### Спринт 8.9. Античит — вертикальный срез ⏳
- **Статус**: ⏳ не начат.
- **Backend:** проверка velocity между spawn и scan; anomalies detection (телепорт, идеальная accuracy); флаги в admin_audit_log; при подозрении — миссия помечается в review.
- **Admin UI:** раздел «Гео-аудит» с флагами.
- **Проверка:** имитация подмены GPS даёт флаг.

### Спринт 8.10. Segment → Part (переименование) ⏳
- **Статус**: ⏳ не начат.
- **БД:** оставить таблицу segments (совместимость), переименовать в UI.
- **Backend:** алиасы в API (не ломать существующие роуты).
- **Admin UI:** переименовать везде «Сегмент» → «Часть».
- **Client UI:** переименовать в типах и в ScannerScreen.
- **Проверка:** пользователь видит «Части» в админке, ничего не сломано.

### Спринт 8.11. CMS GeoZone / ARObject ⚠️ частично
- **Статус**: ⚠️ частично — отдельный раздел «Геозоны» сделан в админке (в разделе «Контент»), AR-объекты тоже; полное соответствие задумке roadmap требует ревизии.
- **Admin UI:** два новых раздела в меню (по образцу Segment).
- **Проверка:** админ создаёт зону и AR-объект через UI.

### Спринт 8.12. End-to-end играбельная миссия ⚠️ частично
- **Статус**: ⚠️ частично — прототип работает (accept → spawn → радар → AR-куб с QR → scan-qr), но мини-игра и награды после QR не запускаются.
- Полный путь: взял миссию → GPS → зона → скенер → AR → QR → мини-игра.
- **Проверка:** игрок проходит одну миссию от начала до конца на реальной карте.

### Спринт 8.13. Cipher (drum-lock мини-игра) — ✅ закрыт (2026-10-16)

- **Статус**: ✅ закрыт (2026-10-16).
- Спецификация: docs/minigame-cipher.md.
- Backend: content_contract (schema cipher), mission_engine (cipher_match), admin_missions (publish-валидация).
- Admin UI: форма cipher + авто-переключение валидатора при смене mission_type.
- Frontend: CipherScreen (drum-lock), интеграция в App.tsx, тап по кубу.
- QR: frontend удалён, backend помечен deprecated (qr_service.py).
- CSS: CipherScreen + .is-tappable.
- TerminalScreen: фильтр !== 'team' (пропускает cipher).
- Единый модуль цветов слоёв: src/constants/missionLayerColors.ts.
- Цвет куба от слоя (через CSS-переменную --cube-color).
- Унификация цветов в TerminalScreen, MapScreen, ScannerScreen, EchoRadar.
- Тесты: 547 OK (было 519 на 2026-10-14).

### Спринт 8.14. Multi-run миссии (повторное прохождение) — ✅ закрыт (2026-10-16)

- **Статус**: ✅ закрыт (2026-10-16).
- **8.14.1** ✅ PlayerMission.successful_completions (миграция d77ea4701199).
- **8.14.2** ✅ per-run reference_id для solo-наград.
- **8.14.3** ✅ max_attempts enforcement (409 + expired).
- **8.14.4** ✅ attemptMultipliers (подключён scaled_attempt_multipliers, убран хардкод).
- **8.14.5** ✅ after_terminal для solo — миссия возвращается в available после completed (`e0ce223`).
- **8.14.6** ❌ отменён: timer per-attempt — мёртвое поле удалено 2026-10-16 (не настраивается в админке; `deadline_at` только от accept, план — docs/remove-attempt-deadline-plan.md).
- **8.14.7** ✅ Инвариант status ↔ attempt_count (`3126bc9`).
- **Известный баг**: entry debit (mission_entry_debit) использует reference_id=mission.id (не per-run) — при повторном заходе debit не создаётся (unique index). Требует reference_id = f"{player_mission.id}_entry_{N}". Не исправлено.

### Спринт 8.15. Expire_mission при cooldown=0 — ✅ закрыт (2026-10-17)

**Было:** при cooldown = 0 миссия после провала терялась навсегда.
**Стало:** expired следует repeatability_policy:
- one_time / legacy → expired (архив).
- after_terminal + cooldown=0 → immediately available.
- after_terminal + cooldown>0 → wait cooldown → available.
**Тесты:** 571 OK.

### Спринт 8.16. Магазин ключей (per-key fallback) — ✅ закрыт (2026-10-18)

**Что сделано:**
- Backend: per-key entitlements (item_id в player_fallback_entitlements).
  При провале 1 → ВСЕ ключи-награды миссии → отдельные офферы.
  Провал 2+ → не добавляется.
- Backend: admin invalidate ALL entitlements on mission cancel.
- Backend: shop_service (каталог) + shop.catalog settings — оставлен
  как альтернатива (не используется основным UI).
- Frontend: ShopScreen → fallback-офферы, "В магазине: N" (remainingQuota).
- Тесты: 586 OK.

**Долги (перенесены в 8.20):**
- Per-key цена fallback (сейчас глобальная).
- Fallback offer_id из миссии.

### Спринт 8.17. Профили мини-игр (вынос настроек из формы миссии) — ✅ закрыт (2026-10-19), кроме 8.17.13 (долг)

**Зачем:** настройки игры (drumCount, falseChoicesPerDrum, timeLimitSeconds)
сейчас в каждой миссии вбиваются заново. Нужен отдельный раздел
"Настройки мини-игр": админ создаёт профиль (игра + параметры сложности),
в миссии выбирает профиль.

**Логика:**
- Профиль обязателен для миссии.
- Имя профиля уникальное.
- Админ создаёт любые профили (CRUD).
- В профиле — ТОЛЬКО настройки игры. Тексты (label, instruction,
  successTitle) остаются в миссии.
- Существующие cipher-миссии → автоматически создаём профили.

**План (19 подшагов: 8.17.1–8.17.19):**
- 8.17.1 ✅ Модель MinigameProfile (id, name, game_type, settings JSON, status).
- 8.17.2 ✅ Миграция: таблица + FK в Mission.
- 8.17.3 ✅ Backend CRUD (admin_minigame_profiles.py + main.py).
- 8.17.4 ✅ Frontend: раздел в sidebar ("Настройки мини-игр").
- 8.17.5 ✅ Профиль: только параметры (drumCount, falseChoicesPerDrum,
  timeLimitSeconds). Без alphabet/combination.
- 8.17.6 ✅ Backend-генератор: CIPHER_ALPHABET (A-Z + 0-9, 36 символов);
  generate_cipher_session — случайный код (длина = drumCount), барабаны
  (1 верный + N ложных без повторов, при N>35 — с повторами);
  генерация при accept, регенерация при промахе.
- 8.17.7 ✅ CipherScreen: читает mission.cipherSession (drums, correctCode)
  с backend; fallback на content.ui для старых миссий.
- 8.17.8 ✅ Re-arm per run: run_entry_count в PlayerFallbackEntitlement;
  новый заход (entry_count != run_entry_count) → re-arm
  (available, consumed НЕ сбрасывается, run=current); шаг 8b —
  quota_limit копится на reward.amount захода; reference_id покупки =
  {entitlement.id}:{run}:{count}.
- 8.17.9 ✅ Frontend: dropdown "Профиль мини-игры" в форме миссии (dropdown есть; 8.17.9c → 8.17.18 — форма переведена на профиль, старые поля скрыты и не отправляются).
- 8.17.10 ✅ Backend: чтение профиля в mission_engine (при accept/submit) — реализовано через _resolve_minigame_settings (8.17.15).
- 8.17.11 ✅ Миграция существующих cipher-миссий в новый формат (обе test-cipher-01/02 мигрированы на профиль test_cipher_ilght; старые поля content.ui вычищены).
- 8.17.12 ✅ Тесты (7 автотестов published-ветки в test_minigame_profile_cipher_publish.py; 627 OK).
  Обязательные тесты новых шагов: (а) cipher + published-профиль + пустой content.ui →
  publish OK; (б) cipher + published-профиль + неполный content.ui (без drumCount/alphabet) →
  publish OK; (в) cipher + draft/archived-профиль + пустой content.ui → 422;
  (г) legacy cipher без профиля + пустой content.ui → 422;
  (д) accept: профильная миссия → settings из профиля, legacy → content.ui.
- 8.17.13 ❌ Долг после 8.17 — Edge-кейс (stale available): если игрок провалил 1-ю, не купил,
  а в новом заходе успех с 1-й → ключ наградой, но старый available-оффер
  остаётся в магазине (можно купить второй ключ). Решение: при успешном
  submit помечать entitlement'ы run_entry_count текущего захода (исключить
  покупку после успеха). Требует согласования (трогает
  mission_engine._submit_mission_once — награды; не в этом спринте).

**Архитектурное решение:**
- Настройки профиля — только параметры сложности (drumCount,
  falseChoicesPerDrum, timeLimitSeconds).
- Алфавит — фиксированный A-Z + 0-9 (36 символов). Не редактируется.
- Правильный код — генерируется на backend случайно (длина = drumCount).
- Символы барабанов — генерируются на backend (1 верный + N ложных
  из алфавита, случайный порядок).
- При каждой попытке — новый код и новые символы.
- Проверка ответа — на backend (безопаснее).

### Архитектурное решение: реестр обработчиков мини-игр (2026-10-19)

Мини-игр будет несколько, с разной логикой (cipher, code_repair, text_answer и будущие). Каждая настраивается отдельно через профиль (minigame_profile). Миссия ссылается на профиль через minigame_profile_id. Движок НЕ должен содержать жёстких if mission_type == "cipher" — вместо этого вводится реестр обработчиков:

- backend/app/minigame_handlers.py — словарь MINIGAME_HANDLERS: {game_type: handler}.
- Каждый handler отвечает за: (а) генерацию сессии по profile.settings (для cipher — код + барабаны), (б) валидацию ответа игрока.
- mission_engine.py при accept/submit берёт mission.minigame_profile_id → грузит MinigameProfile → по profile.game_type выбирает handler из реестра → передаёт ему profile.settings.
- Legacy-путь: если minigame_profile_id IS NULL (старые миссии) — fallback на текущий код (content.ui), чтобы test-cipher-01/02 не сломались.
- Новая мини-игра = новый файл-обработчик + одна строка регистрации в MINIGAME_HANDLERS. mission_engine.py не трогается.
- Валидация настроек профиля (whitelist по game_type) уже есть в admin_minigame_profiles.py:45-49 — её используем как справочник допустимых полей, но диспетчеризация в рантайме — через MINIGAME_HANDLERS.

Новые подшаги (добавить в план 8.17 после 8.17.13):
- 8.17.14 ✅ Backend: minigame_handlers.py — реестр + CipherHandler (перенос generate_cipher_session и cipher-ветки _validate_submission из mission_engine.py). Legacy-fallback сохранён.
- 8.17.15 ✅ Backend: mission_engine.py — при accept/submit читает profile.settings через _resolve_minigame_settings/реестр; legacy content.ui сохранён.
- 8.17.16 ✅ Backend: require_full_cipher_ui — для published-профиля поля content.ui.drumCount/falseChoicesPerDrum/alphabet/combination не требуются; без профиля (legacy) — требуются как раньше.
- 8.17.17 ✅ Frontend: CipherScreen — рисует по cipherSession (drums + correctCode), content.ui не требуется; legacy fallback сохранён.
- 8.17.18 ✅ Frontend: AdminApp.tsx — для cipher скрыть старые поля формы (все параметры сложности cipher: drumCount, falseChoicesPerDrum, combination, alphabet, validationCorrectCombination, timeLimitSeconds — они живут в profile.settings), оставить только dropdown профиля + тексты (label/instruction/successTitle/successText/wrongAnswerText); formToPayload старые поля не отправляет. Это и есть 8.17.9c. Выполнено 2026-10-19.
- 8.17.18-hotfix ✅ Backend: correctCombination не требуется для published-профиля (гейт в _validate_for_publish, admin_missions.py).
- 8.17.19 ✅ Backend: publish-валидация — для cipher-миссии с mission_type="cipher" minigame_profile_id обязателен (admin_missions._validate_for_publish:440).
- 8.17-timer ✅ (внеплановый фикс) Backend + Frontend: timeLimitSeconds из profile.settings доходит до CipherScreen (таймер на попытку cipher). CipherHandler.generate_session кладёт в сессию; _serialize_cipher_session_for_bootstrap пробрасывает в cipherSession; типы CipherSession содержат поле; parseCipherContent читает из cipherSession с приоритетом над content.ui. Фикс e2b2f2b.

Статус: реализовано в 8.17.14–8.17.18. handler-реестр, чтение profile.settings, смягчение контракта для published-профиля, отрисовка CipherScreen по cipherSession. Legacy-путь сохранён для миссий без профиля.

**Границы ответственности handler'а (зафиксировано 2026-10-19 по разведке mission_engine.py):**

Handler мини-игры отвечает ТОЛЬКО за:
- (а) генерацию сессии по profile.settings (для cipher — код + барабаны);
- (б) проверку ответа игрока → возвращает bool, без side-effect'ов.

Handler НЕ трогает (остаётся в mission_engine.py без изменений):

| Что | Файл:строки (сверить с grep) | Функции |
|---|---|---|
| Начисление наград (currency/items/story_node, множители попыток, идемпотентность) | mission_engine.py:685-887 | `_award_mission_rewards` |
| Смена статуса/счётчиков миссии | mission_engine.py:1128, 1136-1152, 1154, 1159, 1210-1211, 1218-1219 | `_submit_mission_once` (статусы) |
| Оркестрация submit-флоу | mission_engine.py:1073-1242 | `_submit_mission_once` |
| Идемпотентный retry-цикл | mission_engine.py:1470-1507 | `submit_mission` |
| Fallback-офферы при провале | mission_engine.py:1179-1184 | `create_first_failure_entitlements` |
| Entry-debit legacy-fallback | mission_engine.py:1168-1169, 890+ | `_apply_entry_debit`, `_consume_entry_resources` |

**Порядок начисления наград заморожен (заказчик 2026-10-19). Не менять:**
1. `_validate_submission` → True (1171-1173)
2. `player_mission.status = "completed"` (1210)
3. `completed_at` (1211)
4. `successful_completions += 1` (1218)
5. `run_reference_id` (1219)
6. `_award_mission_rewards` (1221-1233): загрузка MissionReward → кошелёк → множитель попытки → WalletTransaction(credit) → PlayerItem → story ids → flush
7. return `{accepted: True, awarded, ...}` (1235-1242)

**Два хрупких места при выносе cipher в handler (8.17.14) — сохранить в той же точке флоу:**
1. Регенерация сессии при провале (mission_engine.py:1188-1193) живёт МЕЖДУ `create_first_failure_entitlements` (1179-1184) и `return` (1194-1208). При выносе вызов handler'а должен остаться в этой же точке — иначе сломается контракт «провал → новый код».
2. `_serialize_cipher_session_for_bootstrap` (599-622) вызывается из `_build_bootstrap` (471-474) для ВСЕХ миссий и должен продолжать gracefully возвращать `None` для non-cipher. Не сломать.

**Регресс-тест при выносе (8.17.14):** сценарий «успех cipher-миссии → награда начислена ровно один раз, в том же порядке, что и до выноса» должен остаться зелёным. Существующие 620 unittest-тестов — не трогать, они и есть защита.

**Текущие расхождения docs vs код (на 2026-10-19, зафиксировано разведкой):**
1. ✅ ЗАКРЫТО 8.17.15 (движок читает profile.settings через реестр, legacy content.ui сохранён).
2. ✅ ЗАКРЫТО 8.17.19 («профиль обязателен для published cipher» реализовано в admin_missions._validate_for_publish).
3. ✅ ЗАКРЫТО 8.17.11 (обе test-cipher-01/02 мигрированы на профиль test_cipher_ilght; старые поля content.ui вычищены).
4. ✅ ЗАКРЫТО 8.17.18 (старые поля скрыты, не отправляются; timeLimitSeconds тоже в profile.settings).
5. ✅ ЗАКРЫТО (docs обновлены в f8ee3d3; minigame-cipher.md + api-contracts.md синхронизированы).
6. ✅ ЗАКРЫТО (комментарий models.py:155 поправлен).
7. ✅ ЗАКРЫТО 8.17.17 (CipherScreen рисует по cipherSession, content.ui не требуется; legacy fallback сохранён).
8. 8.17.13 (stale available) — не сделано, долг после 8.17 (трогает _submit_mission_once, награды; не в этом спринте).

**После 8.17:**
- 8.18 — Улучшения формы (справочники вместо JSON, gate !canWrite для ключей,
  координаты геозоны, 3 тихих catch).
- 8.19 — Декомпозиция AdminApp.tsx (4800 строк → компоненты).

### Спринт 8.18. Улучшения формы админки — ✅ закрыт (2026-10-20), с оговорками

- 3 тихих catch ✅ (3 места: AdminApp.tsx getAdminMe, listKeyItems, getMissionRuntimePolicyByMission; показывают ошибку + console.error).
- Bug №244 (ключи) — проверить ещё раз. (не входило в 8.18 — остаётся долгом)
- Справочники вместо JSON ✅ частично (Reward value JSON убран; авто-подстановка по типу: currency → {currency:ROOT}, item/story_node → {}; content/validation JSON — не трогали, это закрытые данные/структурированные редакторы по типу).
- Gate !canWrite для раздела "Ключи" ⏭️ пропущен (viewer-роли нет; если появится — отдельный шаг; записан в долги).
- Координаты геозоны в UI ⏭️ не актуально (координаты генерируются сервером при взятии миссии — дизайн 8.2; админ их не вводит).

**Долги после 8.18:**
- gate !canWrite для ключей — если появится viewer-роль.
- тост-система уведомлений (сейчас inline-баннеры без автоскрытия) — отдельный UX-апгрейд.
- granular-права (фронт проверяет только роль canWrite, не permissions) — отдельный долг.
- content/validation JSON → структурированные редакторы для text_answer/code_repair (cipher уже есть) — отдельный шаг.

### Спринт 8.19. Декомпозиция AdminApp.tsx — ❌ запланирован

AdminApp.tsx — 5336 строк (wc -l), один гигантский компонент (485: `function AdminApp()`,
~88 useState, ~20 useEffect, ~40 хендлеров). Разбить на компоненты по возрастанию риска,
после каждого шага — `npm run build` (tsc) + ручной прогон админки:

- SettingsSection — 3464–3690 (~226 строк). Низкий риск.
- AdminsSection — 3691–3997 (~306). Низкий риск.
- KeysSection — 3998–4291 (~293). Средний риск: делит `keyItems` с формой миссии.
- ContentSection — 4526–5336 (~810; вкладки Segment/GeoZone/ARObject).
  Средний риск: делит `geoZones`/`arObjects` с формой миссии.
- MissionsSection — 2410–3462 (~1052). Высокий риск: редактор наград + policy-блок,
  тянет `keyItems`/`geoZones`/`arObjects`/`missions`.
- Шапка/навигация (2340–2409) → AdminShell; хелперы миссии (1–484) → missionFormModels.ts.
- Перекрёстные стейты (`keyItems`, `geoZones`, `arObjects`, `missions`) — поднять
  в родителя/прокинуть пропсами, не дублировать.
- adminApi.ts (~1030 строк) → по доменам.

### Спринт 8.20. Fallback per-key цена + offer_id из миссии — ✅ закрыт (2026-10-20)

- **Статус**: ✅ закрыт (2026-10-20).
- **Что сделано (per-key цена ключа):**
- Добавлено `key_rules.price` (nullable, per-key цена).
- Хелпер `resolve_key_price` (`app/key_price.py`): приоритет — `key_rules.price` → глобальная настройка (`shop.catalog.default_price_root` / `shop.fallback.default_price_root`) → default.
- Магазин (`shop_service`) и fallback (`fallback_shop`) берут цену через хелпер. Логика выдачи/списания не тронута.
- Форма ключа: добавлено «Цена (ROOT)» (пусто = глобальная), убран «Стак-лимит» (мёртвая колонка, не проверяется).
- Глобальные настройки оставлены как fallback (не удалять).
- Награды, вход в миссию, выдача — не тронуты.

**Долги после 8.20:**
- gate !canWrite для ключей — если появится viewer-роль (долг из 8.18).
- тост-система уведомлений (сейчас inline-баннеры без автоскрытия) — отдельный UX-апгрейд (долг из 8.18).
- granular-права (фронт проверяет только роль canWrite, не permissions) — отдельный долг (долг из 8.18).
- content/validation JSON → структурированные редакторы для text_answer/code_repair (cipher уже есть) — отдельный шаг (долг из 8.18).
- Fallback offer_id из миссии — остаётся долгом (входил в состав 8.20, не реализован).
- per-key цена — реализована в 8.20 (долг из 8.16 закрыт).

### Спринт 8.21–8.26. Иерархия контента — ❌ запланирован

**Зачем:** админ управляет иерархией через каскадный выбор (Сезон → Глава → Сегмент → Миссия), а не вбивает ID вручную. Модель уже готова (Season → Chapter → {Mission, Segment, StoryNode}, FK есть). Миграции не нужны.

**Этапы:**
- 8.21 ❌ Season CRUD (backend admin_seasons.py + frontend вкладка «Сезоны»; права seasons.read/manage; audit; draft→published→archived).
- 8.22 ❌ Chapter CRUD (backend admin_chapters.py + frontend вкладка «Главы»; season_id — dropdown; права chapters.*; audit).
- 8.23 ❌ Каскадный конструктор (Сезон → Глава → Сегмент → Миссия, пошаговый выбор; «создать новый» / «выбрать существующий»).
- 8.24 ❌ Dropdown вместо input: Chapter ID (миссия, сегмент) → dropdown глав; Story node ID (миссия, награда) → dropdown story-нод главы. «Слой» (solo/team/story) и «Разблокируется после» — уже есть, не трогать.
- 8.25 ❌ Связь 1:1: миссия не может существовать без места в иерархии (валидация: либо chapter_id+segment_id, либо командная/индивидуальная с unlock_after). Правило, не сущность.
- 8.26 ❌ StoryNode CRUD (backend admin_story_nodes.py + frontend; chapter_id — dropdown; права story_nodes.*).

**Статусная модель:** draft → published → archived (как у сегментов/мини-игр). Строгая иерархия: глава публикуется только при published сезоне; миссия/сегмент — только при published главе.

**Не трогать:** «3 вкладки» (Слой solo/team/story), «Разблокируется после» (unlock_after_mission_id), «Порядок сортировки» — уже есть.

**Долги после 8.26:** покупка прохождения за ROOT (если игрок не может пройти сюжетную) — отложено.

### Спринт 8.6 — Content UX (закрыт 2026-10-14)

Игровой цикл + UX доведены до рабочего прототипа. Все спринты проверены end-to-end на реальном телефоне в Telegram Mini App.

- **8.6.p** ✅ Стабильный запуск камеры и гео
  - useGeoPosition: единый watchPosition-канал, разрешения не запрашиваются повторно при переключении экранов.
  - useCameraStream: единый кэшированный MediaStream, только задняя камера.
  - Фикс: при перезагрузке Mini App с сохранённой вкладкой 'camera-test' — камера не автозапускается без жеста пользователя.
  - Фикс: 'denied' геолокации не фиксируется навсегда — всегда вызывается watchPosition, который триггерит системный диалог.
  - Фикс: застревание в состоянии accepted=false без таб-бара — при инициализации экран падает на 'briefing'.
  - Таймаут 10 с на getUserMedia: если камера не отвечает, показывается ошибка вместо вечного 'starting'.

- **8.6.q** ✅ Время на выполнение задания
  - БД: Mission.execution_time_limit_seconds (int, nullable, >0), PlayerMission.deadline_at (datetime, nullable).
  - Backend: при первом accept вычисляется deadline_at = started_at + limit; bootstrap отдаёт executionTimeLimitSeconds и deadlineAt.
  - Admin UI: dropdown «Время на выполнение» [без лимита / 5 мин / 15 мин / 1 ч / 6 ч / 24 ч / 7 дней].
  - Client UI: MissionTimer над радаром и в AR-камере, критическая зона <60 с пульсирует, «ВРЕМЯ ВЫШЛО» после истечения.
  - Тесты: 508 (включая 4 на deadline).

- **8.6.r** ✅ Cooldown после провала / одноразовость
  - БД: Mission.reentry_cooldown_seconds (int, default 0, >=0), PlayerMission.available_again_at (datetime, nullable).
  - Backend: авто-expire при истечении deadline в _synchronize_player_missions; авто-возврат из cooldown; проверка в _accept_mission_once (429 «на перезарядке», 409 «одноразовая»); POST /missions/{id}/expire (ручной expire по клику игрока).
  - Admin UI: dropdown «Повторное взятие» [одноразовая / через 5 мин / 1 ч / 6 ч / 24 ч / 7 дней].
  - Client UI: клик по «ВРЕМЯ ВЫШЛО» → миссия уходит в cooldown; в Контуре статус «ПРОВАЛЕНО» + CooldownCountdown формата дд:чч:мм:сс.
  - Тесты: 8 новых, 516 всего.

- **8.6.s** ✅ Архив завершённых и одноразовых провалов
  - В Контуре — сворачиваемая секция «ИСТОРИЯ ЗАДАНИЙ» под основным списком.
  - Фильтр: completed + expired без availableAgainAt (одноразовые) уходят в архив; expired с cooldown остаются в основном списке с живым таймером.
  - Переименование: «АРХИВ / ЗАВЕРШЁННЫЕ» → «ИСТОРИЯ ЗАДАНИЙ» (чтобы не путать с вкладкой «Архив» в таб-баре — это storyNodes).

- **8.6.t** ✅ Цепочки разблокировки
  - БД: Mission.unlock_after_mission_id (nullable self-FK, SET NULL).
  - Backend: в _synchronize_player_missions миссия остаётся 'locked', пока predecessor не в completed.
  - Admin UI: dropdown «Разблокируется после» с валидацией (self-ref, cross-chapter, циклы до 20 шагов → 422).
  - Тесты: 3 новых, 519 всего.

- **8.6.u** ✅ Группировка миссий по слоям в Контуре
  - 3 аккордеон-папки: СЮЖЕТНЫЕ / КОМАНДНЫЕ / ИНДИВИДУАЛЬНЫЕ (по mission_layer: story / team / solo).
  - Иконки 📁/📂, счётчик, авто-открытие первой непустой папки.
  - Цвета: story=красный, team=синий, solo=жёлтый.
  - Ранее (8.6.o.4.d–e): слои уже используются в ScannerScreen (3 кнопки-переключателя) и MapScreen (цвет круга) + правило «≤1 активной миссии на слой» в mission_engine._accept_mission_once.

Связанные документы: docs/geo-team-mission-contract.md, docs/segment-content-contract.md, docs/api-contracts.md.

---

## Этап 9. Экономика ROOT и ledger — ⚠️ в работе

Уже реализовано: Wallet, WalletTransaction, резервы, настройки экономики.

### Шаг 9.1: Фоновая сверка «баланс = сумма проводок»
- **Что**: периодическая задача, которая сверяет кэш баланса с суммой ledger и пишет расхождения в аудит.
- **Файлы**: сервис ledger, фоновые задачи.
- **Проверка**: искусственное расхождение → отчёт в админке.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 9.2: Реестр финансовых операций в админке
- **Что**: страница просмотра всех проводок с фильтрами.
- **Файлы**: роутер админ-финансов.
- **Проверка**: список проводок доступен, фильтры работают.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 9.3: Финансовые тесты
- **Что**: тесты на двойное списание, уход в минус, идемпотентность.
- **Файлы**: папка тестов.
- **Проверка**: pytest зелёный.
- **Зависит от**: 9.1, 9.2
- **Риск**: низкий

---

## Этап 10. Переводы ROOT и комиссия Stars — ❌ не начат

### Шаг 10.1: Модели PlayerTransfer и StarsPayment
- **Что**: заявка на перевод и журнал Stars-платежей.
- **Файлы**: файл моделей.
- **Проверка**: создать записи.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 10.2: Миграция для переводов и Stars-платежей
- **Что**: таблицы переводов и платежей.
- **Файлы**: папка миграций.
- **Проверка**: применить миграцию.
- **Зависит от**: 10.1
- **Риск**: низкий

### Шаг 10.3: Проверка порога выигрыша
- **Что**: игрок может переводить только после достижения подтверждённого выигрыша (порог из system settings).
- **Файлы**: сервис переводов.
- **Проверка**: попытка перевода ниже порога блокируется.
- **Зависит от**: 10.2
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 10.4: Создание Stars-инвойса и webhook
- **Что**: инвойс в Telegram Stars, обработка подтверждения платежа от Telegram.
- **Файлы**: сервис переводов, сервис Telegram.
- **Проверка**: тестовый платёж создаёт запись StarsPayment.
- **Зависит от**: 10.3
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 10.5: Атомарная проводка перевода в ledger
- **Что**: при подтверждении Stars — две проводки (debit/credit) + запись комиссии.
- **Файлы**: сервис переводов, ledger.
- **Проверка**: успешный перевод отражается в ledger, ошибка — откат.
- **Зависит от**: 10.4
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 10.6: Антифрод переводов
- **Что**: лимиты, возраст аккаунта, запрет для ограниченных, ручной review крупных сумм.
- **Файлы**: сервис переводов, аудит.
- **Проверка**: подозрительный перевод уходит в review.
- **Зависит от**: 10.5
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

---

## Этап 11. Вывод ROOT в TON — ❌ не начат

### Шаг 11.1: Модель TonWallet и WithdrawalRequest
- **Что**: TON-адреса игроков и заявки на вывод.
- **Файлы**: файл моделей.
- **Проверка**: создать записи.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 11.2: Миграция для TON-адресов и заявок
- **Что**: таблицы адресов и заявок.
- **Файлы**: папка миграций.
- **Проверка**: применить миграцию.
- **Зависит от**: 11.1
- **Риск**: низкий

### Шаг 11.3: Секрет-хранилище для ключей проекта
- **Что**: ключи проекта не в .env, не в БД, а в отдельном хранилище.
- **Файлы**: инфраструктура.
- **Проверка**: ключи недоступны из кода и БД.
- **Зависит от**: —
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.4: Интеграция с TON SDK
- **Что**: подключение TON SDK, отправка транзакций, отслеживание статуса.
- **Файлы**: сервис TON.
- **Проверка**: тестовая транзакция в testnet.
- **Зависит от**: 11.3
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.5: Логика заявки на вывод
- **Что**: резервирование средств, очередь, подтверждения, откат при ошибке.
- **Файлы**: сервис вывода, ledger.
- **Проверка**: полный цикл от заявки до confirmed.
- **Зависит от**: 11.4
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.6: Админ-панель вывода и ручная сверка
- **Что**: просмотр заявок, approve крупных выводов, история TON-транзакций.
- **Файлы**: роутер админ-финансов.
- **Проверка**: администратор видит и подтверждает заявки.
- **Зависит от**: 11.5
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

---

## Этап 12. Магазин, Stars, операционная экономика — ❌ не начат

### Шаг 12.1: Админ-панель персональных предложений
- **Что**: просмотр открытых предложений игроков, ручное закрытие/продление.
- **Файлы**: роутер админ-магазина.
- **Проверка**: администратор видит и управляет предложениями.
- **Зависит от**: 4.3
- **Риск**: низкий

### Шаг 12.2: Журнал Stars-платежей в админке
- **Что**: страница просмотра всех Stars-платежей с фильтрами.
- **Файлы**: роутер админ-финансов.
- **Проверка**: список платежей доступен.
- **Зависит от**: 10.2
- **Риск**: низкий

---

## Этап 13. Модерация, страны, логи, ошибки — ❌ не начат

### Шаг 13.1: Модель CountryPolicy
- **Что**: политики стран (allowed/restricted/blocked) с ограничениями по функционалу.
- **Файлы**: файл моделей.
- **Проверка**: создать политику.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 13.2: Миграция и админ-роутер CountryPolicy
- **Что**: миграция + CRUD для политик.
- **Файлы**: папка миграций, роутер.
- **Проверка**: изменение политики применяется к игрокам.
- **Зависит от**: 13.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 13.3: Модель PlayerEvent
- **Что**: логи действий игроков (auth.login, mission.accepted, transfer.completed и т.д.).
- **Файлы**: файл моделей.
- **Проверка**: создать событие.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 13.4: Middleware и модель AppError
- **Что**: сбор ошибок приложения с correlation_id, severity, безопасным контекстом.
- **Файлы**: middleware, файл моделей.
- **Проверка**: ошибка сохраняется и отображается в админке.
- **Зависит от**: —
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 13.5: Админ-раздел «Ошибки и события»
- **Что**: просмотр ошибок, событий игроков, фильтры, комментарии оператора.
- **Файлы**: роутер админ-мониторинга.
- **Проверка**: список ошибок доступен.
- **Зависит от**: 13.3, 13.4
- **Риск**: низкий

### Шаг 13.6: Интеграция Sentry или GlitchTip
- **Что**: отправка критичных ошибок во внешнюю систему мониторинга.
- **Файлы**: инфраструктура, middleware.
- **Проверка**: тестовая ошибка появляется в Sentry.
- **Зависит от**: 13.4
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

---

## Этап 14. Frontend и мобильный клиент — ⚠️ в работе

Уже: 5 игровых экранов (архив, брифинг, инвентарь, сканер, терминал), API-клиенты, каркас админки.

### Шаг 14.1: Экран «Карта и геозоны»
- **Что**: карта с доступными зонами и активными AR-объектами.
- **Файлы**: frontend-страницы.
- **Проверка**: зоны отображаются, клик открывает детали.
- **Зависит от**: 3.8, 8.2
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 14.2: Экран «Команда и чат»
- **Что**: интерфейс команды, участников, приглашений, чата.
- **Файлы**: frontend-страницы.
- **Проверка**: список участников, отправка сообщений.
- **Зависит от**: 6.4, 6.6
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 14.3: Экран «Баланс и переводы»
- **Что**: баланс ROOT, история, форма перевода с расчётом комиссии Stars.
- **Файлы**: frontend-страницы.
- **Проверка**: перевод инициируется из UI.
- **Зависит от**: 10.4
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 14.4: Экран «Магазин»
- **Что**: персональные предложения, покупка за ROOT.
- **Файлы**: frontend-страницы.
- **Проверка**: покупка проходит из UI.
- **Зависит от**: 4.4, 12.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 14.5: Админ-разделы Dashboard, Игроки, Экономика, Модерация
- **Что**: целевые разделы админ-панели.
- **Файлы**: frontend-страницы админки.
- **Проверка**: администратор выполняет операции из UI.
- **Зависит от**: 5.3, 9.2, 13.5
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

---

## Этап 15. Тестирование, защита и запуск — ⚠️ в работе

Уже: 9 файлов тестов, Docker, nginx, бэкапы.

### Шаг 15.1: Финансовые тесты
- **Что**: тесты на двойное списание, отрицательный баланс, идемпотентность.
- **Файлы**: папка тестов.
- **Проверка**: pytest зелёный.
- **Зависит от**: 9.3
- **Риск**: низкий

### Шаг 15.2: Security-тесты
- **Что**: rate limiting, SQL injection, IDOR, защита Telegram auth.
- **Файлы**: папка тестов.
- **Проверка**: pytest зелёный.
- **Зависит от**: —
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 15.3: Нагрузочные тесты
- **Что**: проверка под нагрузкой (миссии, ledger, чат).
- **Файлы**: папка тестов.
- **Проверка**: система держит целевую нагрузку.
- **Зависит от**: —
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 15.4: Восстановление БД из бэкапа
- **Что**: репетиция восстановления, документация процедуры.
- **Файлы**: docs, скрипты бэкапа.
- **Проверка**: восстановление из резервной копии проходит успешно.
- **Зависит от**: —
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ
---

## Этап 16. Ежедневки (DailyMissions) — ❌ не начат

Отдельный слой заданий без привязки к сезону/главе. Игрок видит всегда, берёт, проходит через тот же гео-AR пайплайн, потом cooldown N часов до следующей попытки.

### Спринт 16.1. Модель DailyMission — вертикальный срез
- **БД:** модель DailyMission (mission_id FK, cooldown_hours, enabled, sort_order) или флаг is_daily на Mission.
- **Backend:** API POST /api/v1/engine/daily-missions/{id}/accept; проверка cooldown.
- **Admin UI:** раздел «Ежедневки» в админке.
- **Client UI:** экран «Ежедневки» с таймером до разблокировки.
- **Проверка:** игрок проходит ежедневку, потом ждёт N часов.

### Спринт 16.2. Гео-AR для ежедневок
- **Backend:** те же spawn/location-proof/qr-scan, но для daily.
- **Client UI:** тот же интерфейс, что для обычных миссий.
- **Проверка:** ежедневка проходится полностью.

---

## Этап 17. CMS-разделы для GeoZone / ARObject / RewardPool / Players / Teams / Approvals — ❌ не начат

Backend API для всех этих сущностей уже готов (см. аудит 2026-10-12). Не хватает UI-разделов в админке.

### Спринт 17.1. Раздел «Геозоны» в админке
- **Admin UI:** CRUD по образцу Segment.
- **Проверка:** админ создаёт зону через UI.

### Спринт 17.2. Раздел «AR-объекты»
- **Admin UI:** CRUD, привязка к GeoZone, поля discovery_scenario / minigame_config.
- **Проверка:** админ создаёт AR-объект.

### Спринт 17.3. Раздел «Игроки»
- **Admin UI:** list + карточка игрока (кошелёк, инвентарь, миссии, ограничения), кошелёк-корректировки через approval-флоу.
- **Проверка:** админ находит игрока, смотрит карточку.

### Спринт 17.4. Раздел «Команды»
- **Admin UI:** list + карточка + force-disband / force-kick через approval.
- **Проверка:** админ модерирует команды.

### Спринт 17.5. Раздел «Заявки на approval»
- **Admin UI:** список заявок, approve/reject, audit trail.
- **Проверка:** super-admin видит и одобряет заявки.

### Спринт 17.6. Раздел «Пулы наград»
- **Admin UI:** CRUD по образцу KeyRules.
- **Проверка:** админ создаёт пул.
