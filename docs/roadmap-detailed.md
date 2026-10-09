# Детальный план реализации ROOT Game

Нумерация шагов соответствует этапам дорожной карты. Статусы взяты из `docs/audit-2026-10-04.md`.

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
  дефолт 100 atomic units). Идемпотентность — `reference_id = "{entitlement.id}:{n}"`
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

## Этап 8. Геолокация, карта, AR, античит — ❌ не начат

Модели GeoZone и ARObject создаются в шагах 3.7–3.10. Здесь — работа с проверками и античитом.

### Шаг 8.1: Расширение LocationProof и API подтверждения присутствия.
- **Что**: доказательства присутствия игрока в зоне (координаты, точность, время).
- **Файлы**: файл моделей.
- **Проверка**: LocationProof создаётся с привязкой к существующей geo_zone по slug.
- **Зависит от**: 3.7
- **Риск**: низкий

### Шаг 8.2: API подтверждения присутствия в геозоне
- **Что**: эндпоинт проверки, что игрок в зоне заданное время с корректной точностью.
- **Файлы**: роутер геозон, сервис геозон.
- **Проверка**: корректная и некорректная геопозиция.
- **Зависит от**: 8.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 8.3: Античит-проверки
- **Что**: скорость перемещения, устаревшие координаты, частота обновлений, флаги для модерации.
- **Файлы**: сервис геозон.
- **Проверка**: имитация подмены геолокации → флаг в админке.
- **Зависит от**: 8.2
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 8.4: Политики хранения геоданных
- **Что**: сроки хранения, минимизация, обезличивание, доступ только у ограниченного круга админов.
- **Файлы**: сервис геозон, аудит.
- **Проверка**: ревизия гео-истории показывает только обезличенные данные.
- **Зависит от**: 8.2
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

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
