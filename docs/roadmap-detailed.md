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

### ✅ Шаг 5.1: Модель PlayerRestriction
- **Что**: ограничения игрока (suspended, transfer_restricted, mission_restricted и др.) с reason, admin_id, expires_at.
- **Файлы**: файл моделей.
- **Проверка**: создать ограничение через ORM.
- **Зависит от**: —
- **Риск**: низкий

### ✅ Шаг 5.2: Миграция для PlayerRestriction
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

## Этап 6. Команды, приглашения, состав, чат — 🔄 в работе (6.1–6.6 ✅; 6.7.a ✅; 6.7.b 🔲)

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

### ✅ Шаг 6.6: Модель командного сообщения и логика чата — закрыт (2026-11-01)

**MVP 6.6-a/b (чат внутри TeamSession).** Постоянной команды в игровом чате
нет: чат существует только внутри командной сессии миссии.

- Модель `team_session_messages` (`TeamSessionMessage`): id, team_session_id,
  player_id, text (≤1000), status (`visible`|`hidden`, hidden заложен под
  6.7.b), created_at/updated_at.
- `GET /api/v1/engine/team-missions/sessions/{id}/messages` — последние
  visible-сообщения, новые сверху; `limit` (default 50, max 200) + курсор
  `before` (ISO-8601 по created_at), `hasMore`.
- `POST /api/v1/engine/team-missions/sessions/{id}/messages` — отправка
  сообщения; только активные участники (`joined`/`ready`), только пока сессия
  в `collecting`/`ready_to_start`/`active`. После финала — 409, история
  остаётся в БД, в UI «Чат закрыт».
- `displayName` автора в выдаче; polling 3 сек; чат в `TeamSessionScreen` с
  кнопкой «Показать ещё» (cursor `before`); hidden-сообщения не отдаются.
- Коммиты: `e2ad80b`, `3a538da`. Тесты: chat service покрыт в backend suite.

#### 🔲 Шаг 6.6-c: Модерация чата (жалобы, мут, скрытие) — не начат
- **Что**: жалобы на сообщения, мут участника, скрытие сообщения
  (`status='hidden'`), журнал модерации.
- **Зависит от**: 6.6.
- **Риск**: средний.

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

#### 🔲 Шаг 6.7.b: Модерация чата — не начат (зависит от 6.6)
- **Что**: admin-просмотр сообщений, скрытие/удаление, мут, жалобы,
  журнал модерации.
- **Зависит от**: 6.6 (MVP чата закрыт 2026-11-01).
- **Риск**: средний.

---

## Этап 7. Командные задания и совместная геоактивация — ⚠️ в работе

Уже: сессии команд, проверка присутствия, попытки, расчёты наград, политики runtime, тесты.
Оплата entry — при accept (create/join); refund — 3 мин от created_at; гео —
только после сбора команды (`ready_to_start`). См. обновление 2026-11-01 ниже.

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

## Этап 8. Гео-AR пайплайн — ⚠️ в работе (8.6 ✅ 2026-10-14, 8.13 ✅ 2026-10-16, 8.14 ✅ 2026-10-16, 8.15–8.26 ✅, 8.5/8.9/8.10 открыты)

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

### Спринт 8.19. Декомпозиция AdminApp.tsx — ✅ закрыт (2026-10-21)

**Что сделано (5 блоков вынесены в компоненты):**
- Settings → `SettingsSection.tsx` (06e27bf).
- Admins → `AdminsSection.tsx` (e58f64a).
- Keys → `KeysSection.tsx` (44ac1e3).
- Content → `ContentSection.tsx` + `SegmentsEditor.tsx` + `GeoZonesEditor.tsx` + `ARObjectsEditor.tsx` (07478fb).
- Missions → `MissionsSection.tsx` (fad518b).
- `AdminApp.tsx`: 5336 → 808 строк (в 6.6 раза меньше).
- Общие стейты (`keyItems`, `geoZones`, `arObjects`, `minigameProfiles`) остались в AdminApp, переданы пропсами в секции.
- Ручной тест: миссии (сохранение, публикация), Content (3 вкладки: Сегменты, Геозоны, AR), dropdown в миссиях (Геозона, AR, Профиль мини-игры, Ключ) — работают. Build EXIT=0.

**Долги после 8.19:**
- `adminApi.ts` (~1030 строк) — разбить по доменам (опционально, низкий риск) — отложено.
- `MissionsSection.tsx` (1911 строк) — можно разбить дальше (награды, политика) — отложено.

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

### Спринт 8.21–8.26. Иерархия контента — ⏳ в работе (8.21/8.22/8.23/8.23.1/8.23.3/8.23.4/8.23.5/8.24/8.25.1/8.26 закрыты, 8.25 открыт; 8.23.2 — в очереди)

**Зачем:** админ управляет иерархией через каскадный выбор (Сезон → Глава → Сегмент → Миссия), а не вбивает ID вручную. Модель уже готова (Season → Chapter → {Mission, Segment, StoryNode}, FK есть). Миграции не нужны.

**Этапы:**
- 8.21 ✅ Season CRUD — закрыт (2026-10-21).
  - Backend: `admin_seasons.py` (CRUD list/get/create/update/publish/archive; права `seasons.read/manage`; audit; slug-нормализация, транслитерация кириллицы).
  - Frontend: `SeasonsSection.tsx` (вкладка «Сезоны», sidebar + форма), `adminApi.ts` (типы + 6 функций + PERMISSION_CATALOG).
  - Миграция-сид прав: `26f3a9c1d5e7`.
  - Тесты: 15 (`test_admin_seasons.py`). Всего 646 OK.
  - Ручной тест: создать/опубликовать сезон — работает.
- 8.22 ✅ Chapter CRUD — закрыт (2026-10-21).
  - Backend: `admin_chapters.py` (CRUD; season_id — FK валидация; строгая иерархия: publish только при published-сезоне, create в archived-сезон → 422, смена season_id у published → 409, повторный publish → 422; права `chapters.read/manage`; audit; slug).
  - Frontend: `ChaptersSection.tsx` (вкладка «Главы», season_id — dropdown из Season), `adminApi.ts` (типы + 6 функций + PERMISSION_CATALOG).
  - Миграция-сид прав: `a3f9c18e42b7`.
  - Тесты: 15 (`test_admin_chapters.py`). Всего 661 OK.
  - Ручной тест: создать/опубликовать главу (dropdown сезона) — работает.

**Долги после 8.21+8.22:**
- Визуальная группировка «Сезоны/Главы/Мини-игры» в «Контент» (вкладки внутри `ContentSection`) — код остаётся разнесённым (`SeasonsSection`/`ChaptersSection`/`MinigameProfilesSection` — отдельные файлы), только UI-группировка. Долг 8.27+ (после 8.26).
- `MinigameProfiles` — инлайн-блок в `AdminApp` (долг 8.19, не вынесен) — вынести в отдельный компонент.
- 8.22: запретить PATCH draft-главы в archived-сезон (симметрия с D3а) — мини-долг.
- 8.23 ✅ Каскадный конструктор (Сезон → Глава → Сегмент → Миссия, пошаговый выбор; «создать новый» / «выбрать существующий») — закрыт (2026-10-21). Реализовано: бэкенд-фильтры (chapters?season_id, segments?chapter_id, missions?chapter_id), CascadeSection.tsx, вкладка «Конструктор» в AdminApp. CRUD в каскаде — отложен (Этап 3+).
- 8.23.1 ✅ Умная выпадашка миссий — закрыт (2026-10-21). Реализовано: (1) фильтр по главе в SegmentsEditor (e49d573) — миссии только выбранной главы, сброс привязок при смене главы; (2) подсветка занятых миссий в выпадашке (2abc93f) — суффикс «— уже в: Сегмент X» для миссий, привязанных к другим сегментам; (3) фильтр по главе в MissionsSection для «Разблокируется после» + очистка зависимости при смене главы (de4ee02). Нативные <select> (цвет/иконки — отдельная задача 8.23.2).
- 8.23.2 ❌ Кастомный dropdown для выпадашек миссий (цвет/иконки/пояснение при выборе) — сейчас нативные <select> дают только текстовую пометку. Отдельный примитив в src/, требует согласования.
- 8.23.3 ✅ Авторефреш карты занятости в SegmentsEditor — закрыт (2026-10-22). Добавлен helper reloadSegments() (listSegments → setSegments), вызывается с await после успеха всех 5 мутаций (create/save/publish/unpublish/archive) после notice. missionUsage (reduce в рендере) пересчитывается автоматически. Кнопка «↻ Обновить список» оставлена как есть (loadingSegments не ломаем). Проверено вручную через save: после сохранения сегмента карта занятости в выпадашке миссий другого сегмента обновляется. Публикация test-segment-02 падает с «content не соответствует контракту» — это НЕ связано с 8.23.3 (известный долг: пустой content {}), см. audit.
- 8.23.4 ✅ Story node ID в MissionsSection — закрыт (2026-10-21). Бэкенд-валидация: story_node_id миссии и story_node_id в наградах проверяются на совпадение главы (StoryNode.chapter_id == mission.chapter_id) → 422, симметрично сегмент↔миссия (_validate_link_payload) и unlock_after (_validate_unlock_chain). Затронуты _validate_references, _validate_rewards (+3 вызова), 2 новых теста (cross → 422, same → OK), 3 assert'а в test_admin_content_validation. Замечание: если в проде есть cross-chapter story_node (через API), publish начнёт падать 422 — данные неконсистентны, требует внимания при деплое (для dev не проблема: через UI не воспроизводится).
- 8.23.5 ✅ Фронт-защита от дубля миссии в одном сегменте — закрыт (2026-10-21). Реализовано в changeSegmentMissionLink (5174e21): early-return для пустых missionId, проверка дубля по missionId с установкой segmentError «Эта миссия уже добавлена в текущий сегмент.», сброс segmentError при успешном выборе. Не регрессия — проверки никогда не было (подтверждено git-историей).
- 8.24 ✅ Chapter ID dropdown — закрыт (2026-10-21).
  - Frontend: `MissionsSection.tsx` + `SegmentsEditor.tsx` — Chapter ID (текстовый input) → dropdown из `listChapters()` (фильтр `status !== 'archived'`).
  - Story node ID — отложен (8.26, нет CRUD).
  - Payload не изменился (`chapter_id` уходит как раньше).
  - Build EXIT=0. Ручной тест: dropdown виден, сохранение работает.
  - 8.24-доп ✅ Story node dropdown — закрыт (2026-10-21). Story node ID (в форме миссии и в награде) → dropdown из story-nodes выбранной главы. При смене главы — перезагрузка списка. Payload не изменён. Build EXIT=0. Ручной тест: dropdown виден, сохранение работает.

**Долги после 8.24:**
- Story node dropdown → после 8.26 (StoryNode CRUD).
- Сегмент `test-segment-02`: content не соответствует контракту — проверить (не блокер 8.24).
- Сегменты параллельно (`chapter_id` → nullable) → 8.27+ (отдельный спринт, миграция).
- Визуальная группировка «Сезоны/Главы/Мини-игры» в «Контент» → 8.27+.
- `MinigameProfiles` — инлайн в `AdminApp` → долг 8.19.
- 8.22: запрет PATCH draft-главы в archived-сезон → мини-долг.
- 8.25 ❌ Связь 1:1: миссия не может существовать без места в иерархии (валидация: либо chapter_id+segment_id, либо командная/индивидуальная с unlock_after). Правило, не сущность.
- 8.25.1 ✅ Slug: вынос хелперов + автогенерация для Segment/Mission + read-only на фронте — закрыт (2026-10-22). Реализовано: (1) вынос SLUG_PATTERN/_normalize_slug/_slugify_title в backend/app/slug_utils.py из 8 копий (b700fce, 5455e8d, a4e3723); (2) автогенерация slug из title для Segment/Mission + unique_slug (суффикс -2/-3 при коллизии) (4014a62); (3) фронт: slug read-only в 5 секциях (Seasons/Chapters/Segments/Missions/StoryNodes), не отправляется в payload (22af10f, 8272cb3); типы выровнены (slug?: string в CreateSegmentPayload и AdminMissionPayload). Существующие ручные slug'и не меняются, новые генерируются.
- 8.26 ✅ StoryNode CRUD — закрыт (2026-10-21).
  - Backend: `admin_story_nodes.py` (CRUD list/get/create/update/publish/archive; chapter_id — FK валидация; строгая иерархия: publish только при published главе, повторный publish → 422, archived → 409; права `story_nodes.read/manage`; audit; slug).
  - Frontend: `StoryNodesSection.tsx` (вкладка «Story Nodes», chapter_id — dropdown; поля: title, slug, body (textarea), presentation_type (input), content (JSON textarea), sort_order), `adminApi.ts` (типы + 6 функций + PERMISSION_CATALOG).
  - Миграция-сид прав: `90de6dad12b`.
  - Тесты: 17 (`test_admin_story_nodes.py`). Всего 678 OK.
  - Ручной тест: создать/опубликовать story-node (dropdown главы, body, presentation_type, content) — работает.

**Статусная модель:** draft → published → archived (как у сегментов/мини-игр). Строгая иерархия: глава публикуется только при published сезоне; миссия/сегмент — только при published главе.

**Не трогать:** «3 вкладки» (Слой solo/team/story), «Разблокируется после» (unlock_after_mission_id), «Порядок сортировки» — уже есть.

**Долги после 8.26:**
- Сегменты параллельно (chapter_id → nullable) → 8.27+.
- Визуальная группировка «Сезоны/Главы/Story Nodes/Мини-игры» в «Контент» → 8.27+.
- MinigameProfiles — инлайн в AdminApp → долг 8.19.
- 8.22: запрет PATCH draft-главы в archived-сезон → мини-долг.
- Сегмент test-segment-02: content не соответствует контракту — проверить.
- Покупка прохождения за ROOT (если игрок не может пройти сюжетную) — отложено.
- Лог ошибок (сбор ошибок приложения: middleware, AppError, CorrelationID, админ-раздел «Ошибки и события») — Этап 13.4/13.5; отдельным долгом не записан. При создании спринта 8.27+ — включить в него.
- 9.3.1 ✅ Реальный параллелизм финансовых тестов (PostgreSQL + потоки) — закрыт (2026-10-23). Инфраструктура: docker-compose сервис db-test (postgres:17-alpine, 5433, chimera_test), PG-тест мягкий к отсутствию PG (skip), схема через alembic upgrade head. Сценарии: (b) shop-гонка — тест нашёл реальную дыру (IntegrityError uq_player_items_player_item при конкурентной первой покупке), фикс (A): begin_nested + except IntegrityError + re-read в shop_service; (c) fallback-идемпотентность — 2 потока на один entitlement quota_limit=1, оба success, debit=1. Коммиты a6ed809, f75a613, 95cc04a. SQLite-регрессия цела (test_economy_9_3 3/3, test_admin_economy 7/7).
- 10.0 ✅ Уникальный читаемый ник игрока (nickname, например Roman#123-456-789) — для переводов (Этап 10). Закрыт (2026-10-23): миграция 884a02f1a72d (nickname/nickname_lower + backfill существующих), генерация при регистрации и для существующих без ника (generate_nickname), латиница (ASCII): латиница для поиска/уникальности, кириллица — только display_name для отображения (SQLite lower() не нормализует кириллицу; индексы; сортировка; мультиязычность — см. 9.2.1). Коммиты 04aae0a, 8ad23f3. Тесты: test_nickname.py.
- 10.0.1 ✅ Игровой поиск игроков по нику — закрыт (2026-10-23). Бэк: GET /api/v1/players/search?q= (min 3 символа, status='active', сам игрок исключён, выдача только id/nickname/country, rate limit 10/min, limit clamp 1..50 default 20). Фронт: метод searchPlayers в engineApi (URLSearchParams); экран поиска НЕ создавали — пойдёт вместе с переводами 10.1+. Коммиты 5646a71, 59dccf3. Тест на телефоне не требуется (экрана нет; проверим в 10.1+).
- 10.0.2 ✅ Карточка игрока в админке (бэк): миграция country/gender/age (249852dee5af), сериализация nickname/country/gender/age в _serialize_player_summary и _serialize_player_card, конфиг PROFILE_FIELDS (4 поля), эндпоинт GET /api/v1/admin/players/profile-fields. Закрыт (2026-10-23). Коммиты 4150c9b, b8acf5d. Тесты: 12/12 (test_admin_players) + регрессия test_admin_economy 7/7. Проверено через браузер: {"fields":[...]} (4 поля).
- 10.0.3 ✅ Фронт карточки игрока в админке — закрыт (2026-10-23). adminApi (listPlayers/getPlayer/getProfileFields), PlayersSection (список + фильтры + пагинация + карточка из PROFILE_FIELDS), вкладка «Игроки» в AdminApp. Коммиты 63391fa, 3410a80, 09dc0c2; поиск в админке (по нику) — отдельный фикс a462321 (nickname_lower в search). Проверено в браузере: список (ник, имя, баланс, статус), фильтры, пагинация, карточка (ник read-only, страна/пол/возраст, баланс 60 ROOT + locked 0). Форма из конфига (PROFILE_FIELDS).
- 10.0.4 ✅ PATCH профиля игрока — закрыт (2026-10-23). PATCH /api/v1/admin/players/{player_id} (country/gender/age, extra=forbid). Валидация: gender ∈ VALID_GENDERS, age 0..120, country ISO-2. Аудит (before/after, changedFields). Row-lock (_lock_player). Фронт: draft-state, «Сохранить»/«Отмена», валидация. Коммиты 5f0c941, 570d77e. Тесты: 4 новых (test_admin_players) + регрессия 7/7.
- 10.0.5 ✅ Автоопределение страны по координатам — закрыт (2026-10-23). При взятии миссии (solo accept + team location) страна определяется офлайн по фактическим координатам игрока (geo-intel-offline, порог confidence 0.7); океан/низкая уверенность — не затираем. Ручной ввод (анкета) — стартовое значение, не приоритет: фактическая страна перебивает его. Коммиты cbfa23a (deps), 320ed36 (auto-detect). Тест на телефоне — отложен (заказчик проверит позже).
- 10.0.5-b ✅ Блокировка ручного ввода country после автоопределения — закрыт (2026-10-23). Колонка country_source ('manual'|'auto'|NULL; миграция 1dd561da2c34). Автоопределение (10.0.5) ставит 'auto'; PATCH /api/v1/engine/me/profile не даёт менять country при 'auto' (422; gender/age — можно) и ставит 'manual' при ручной правке; админский PATCH не блокируется, ставит 'manual'; GET/PATCH отдают country_source. Фронт ProfileScreen: при 'auto' select disabled + подсказка, country не шлётся в payload. Backfill не делали (старые записи — NULL, редактируемы до следующей миссии). Коммиты c247b21, e96228f. Тест на телефоне пройден.
- 10.0.6 ✅ Анкета игрока (фронт в игре) — закрыт (2026-10-23). Экран ProfileScreen (вкладка «Профиль» в MobileNavigation), форма: страна (выпадашка ISO 3166-1 alpha-2, 249 стран — защита от мусора), пол (select male/female/other/unspecified), возраст (number 0..120); nickname read-only. Бэк: GET/PATCH /api/v1/engine/me/profile (свой игрок из куки, валидация 1-в-1 с 10.0.4, без админ-аудита). Коммиты 25524ee, e2ea635, aea2ee8, e93600d. Тест на телефоне пройден.
- 13.7 ✅ Профиль игрока (регион, пол, возраст) — для модерации (Этап 13), антифрода, аналитики. Закрыт (2026-10-24). **Расширен по требованиям заказчика: экономика игрока (ROOT/ГАЗ), график, блокировка, статистика, удаление вкладки «Экономика».**
  - a — read-only карточка игрока (страна/пол/возраст; PATCH-эндпоинт на бэке оставлен, UI не использует). Коммит c04950d.
  - b — last_seen_at: модель + миграция 39b50b607533; обновление в get_current_player_id при каждом запросе. Коммит 39b50b607533.
  - c — PATCH /admin/players/{id}/root (начислить/списать ROOT; row-lock; аудит) + 5 тестов. Коммиты 05a558e, 3407c7b.
  - d — UI «Экономика игрока»: модалка ROOT/ГАЗ (начислить/списать). Коммит 3d9ccf4.
  - e — GET /admin/players/{id}/root-transactions (пагинация) + 5 тестов + таблица истории ROOT в карточке. Коммиты 8366bda, e19e37d.
  - f — график активности (recharts: credit/debit по дням). Коммиты b9ff8f2, 9ee3f82.
  - g — бейдж онлайн/офлайн (lastSeenAt < 5 мин). Коммиты f8cf6b1, 30d2d28.
  - h — block/unblock: POST /admin/players/{id}/block и /unblock; PlayerRestriction blocked; аудит; write-through recompute + 4 теста + UI (модалка с reason). Коммиты 6d80efc, 8ceca86.
  - i — статистика всех игроков: GET /admin/players/stats (total/online/active; period day/week/month) + 4 теста + блок над списком. Коммиты b4b5761, c0b8bf8.
  - j — удалена вкладка «Экономика» + удалён EconomySection.tsx. Коммит 81bc896.
  - Тесты: test_admin_players 45/45, test_admin_economy 7/7, PG 7/7, stars 5/5, webhook 6/6. Frontend build зелёный. Тест в браузере пройден.
- 15.5 ❌ Восстановление аккаунта — привязка Telegram (уже есть external_id), email/телефон, сценарий восстановления при потере доступа. Этап 15 «Тестирование, защита и запуск» (смежно с 15.4 — там восстановление БД, здесь — доступ игрока).

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

### Сделано (командные миссии)

Командный вертикальный срез доведён до играбельного состояния:

- **Бэкенд:** модели Team / TeamSession — сессии без лидера, авто-старт,
  join-session. Тесты: 44/44.
- **Фронтенд:** экран TeamSessionScreen, API-обёртки командных миссий,
  папка «Командные» в Терминале.
- **Админка:** создание командных миссий из дерева, настройка состава,
  зона из геозоны, challenge из профиля.

Базовый флоу «взял → собрал → отказался» (7.1):
- Взятие командной миссии как обычной: accept создаёт командную сессию
  (TeamSession + MissionRun + TeamSessionMember) вместо solo-MissionRun.
- Счётчик состава X/Y в карточке активной миссии (sessionMemberCount /
  maxMembers) + статус сессии (sessionStatus: collecting / ready_to_start /
  active).
- Таймер на отказ (3 минуты) и кнопка «Отказаться» для командной сессии
  (окно от created_at + 3 мин; до «активной» игры).
- Отказ от командной сессии (leave_team_session: POST
  /api/v1/engine/team-missions/sessions/{session_id}/leave) с возвратом платы
  в течение 3 минут от `TeamSession.created_at` (credit-проводка ledger с тем
  же reference_id, что и debit при accept/create/join; после выхода последнего
  участника сессия закрывается).

### Обновление 2026-11-01: оплата при accept, refund от created_at, гео после сбора

- **Оплата при accept:** создание сессии (`create`) и вступление (`join`)
  списывают `entryFeeRootAtomic` + `requiredItems` атомарно, как solo
  (accept = оплата). Ready больше не списывает entry. Коммит `6e9103b`.
- **Refund:** окно 3 минуты считается от `TeamSession.created_at`, не от
  `ready_at`. После окна выход до `active` разрешён без возврата. Коммит
  `1d7c1da`.
- **Гео:** frontend отправляет proof только в `ready_to_start` (не в
  `collecting`); «вне зоны» показывается только после сбора команды.
- **Таймер:** frontend считает окно отказа от `sessionCreatedAt`, не от
  `myReadyAt`. Коммит `25b1802`.

### Новые задачи

1. **Переделать карточку миссии:** убрать тестовые поля («Введите ответ»,
   «Проверить»), добавить «Просмотр» — модальное окно с полным описанием —
   и кнопку «Взять миссию» внутри этого окна.
2. **Таймер на отказ (3 минуты) на любом типе миссий:** после взятия
   списывается плата, 3 минуты на отказ с возвратом, после — провал.
3. **Мини-игра для командных миссий:** 3 попытки, провал одного = провал всех.
   - ✅ Бэкенд готов (2026-10-29, 8.x-2a/2b-1/2b-2a/2b-2b): cipher-волны на
     TeamSession (current_wave/max_waves/wave_status/wave_played_members/
     current_cipher_session), эндпоинт submit-wave, «провал одного = провал
     всех» (переход волны, сброс сыгравших), «ждём остальных» (волна 'playing',
     пока не сыграли ВСЕ активные члены), финализация (passed+succeeded / failed),
     row-lock на TeamSession, hotfix 400 на мусорный sequence, тесты
     test_team_wave_flow.py (8 новых). Файлы: backend/app/team_missions_service.py.
   - ✅ Фронт готов (2026-10-29, 8.x-3/4a/4b-1/4b-2a/4b-2b): CipherGame вынесен
     из CipherScreen (переиспользуется solo и team), мини-игра в
     TeamSessionScreen, счётчик ПОПЫТКА N/M, polling 3 сек, игровые поля волн
     в _serialize_team_session, плашки «Ждём других» / «Член команды провалил
     попытку» (3 сек), финальные экраны «МИССИЯ ПРОЙДЕНА» (с наградами из
     ответа submit-wave) / «МИССИЯ ПРОВАЛЕНА», блокировка повторного сабмита
     (myWavePlayed). Коммиты d3e8ef7, 9b7eeb4, bb5dbc4, ee12391. Файлы:
     src/components/CipherGame.tsx, src/components/screens/TeamSessionScreen.tsx,
     src/api/engineApi.ts.
   - ✅ Навигация: кнопка «ОТКРЫТЬ СЕССИЮ» в TerminalScreen (TeamSessionScreen
     был недостижим из UI).
   - ✅ Авто-гео (8.x-4-ux-fix + fix 2026-11-01): proof отправляется
     автоматически один раз в `ready_to_start` (после сбора команды), не в
     `collecting`; «вне зоны» показывается только после сбора. Кнопка
     «ОТМЕТИТЬ ПРИСУТСТВИЕ» удалена (костыль dev-проверки).
   - ✅ Отказ (8.x-4-refuse-fix + ux-fix + fix 2026-11-01): «ОТКАЗАТЬСЯ» в
     collecting и ready_to_start, 3 мин от `TeamSession.created_at` с
     возвратом, после дедлайна — без возврата (кнопка остаётся); в active —
     «Игра идёт». sessionId в bootstrap (mission.sessionId) → leave_team_session
     (mission.id туда передавать нельзя — 404). Коммиты 10e4791, 1d7c1da,
     25b1802.
   - ✅ Dev-bot (временный, проверка без 2-го аккаунта) — удалён (142b4ac):
     dev_bot.py, 6 dev-эндпоинтов main.py, dev-обёртки engineApi, dev-панель
     UI, dev-стили. Механика волн/провала/успеха подтверждена на dev до
     удаления.
   - ✅ 8.x-4-final-status (2026-10-29): awarded_snapshot в TeamSessionMember
     (d048d4e) + GET /sessions/last (771d086) — финал с наградами видят ВСЕ
     члены команды, включая тех, кто прошёл волны, но команда провалилась
     (награды остаются). Фронт: при sessionEnded — один запрос /last, показ
     «МИССИЯ ПРОЙДЕНА/ПРОВАЛЕНА» с наградами.
   - ✅ Гео-ограничение при сборе команды (2026-11-01, 8.x-4-join-gps): GPS
     при create/join (TeamSessionCreatePayload/JoinPayload); страна —
     geo_intel_offline (join_country всех участников == страна игрока),
     расстояние ≤50 км до ВСЕХ участников (haversine, calculate_distance_km),
     город — reverse_geocoder (169 MB, сервер). Проверки ДО списания entry
     fee (отказ — 409, без дебета). join_latitude/longitude/country/city/
     location_at в TeamSessionMember (миграция 8b1c7d4e6f20, append-only).
     Коммит 889201c. Тесты: 6 новых (страна/расстояние/отказ/maxMembers/без GPS).
   - ✅ Подвкладка «Активные» (2026-11-01, 8.x-4-active-lobbies): GET
     /sessions/active — чужие лобби в сборе со свободными местами, одной
     страной и ≤50 км до всех (freeSlots, maxMembers, description,
     distanceKm = max до участников). TerminalScreen: табы «МОИ СЕССИИ» /
     «АКТИВНЫЕ» в папке «Командные», GPS при открытии (кэш на экран),
     вступление из карточки (join с GPS, без ручного ввода ID; UI-поле ID
     из TeamSessionScreen убрано). Коммит c4f5949. Тесты: 6 новых
     (чужие/свои/полные/далёкие/другая страна/сортировка).
   - ⚠️ ОСТАЛОСЬ (в долг): проверка на 2 реальных телефонах (2 Telegram-аккаунта,
     без dev-бота) — НЕ сделана: реальная синхронизация polling, «ждём других»,
     «член команды провалил попытку», race-условия, финальный экран у всех,
     гео-ограничение при сборе (страна/расстояние/вступление из «Активные»)
     (по коду всё готово, на телефонах не проверено). Без этого 8.x не закрыт
     полностью.
   - ✅ «АКТИВНЫЕ» вне условия папок (2026-11-01, 33f2de7): если у игрока нет
     своих активных миссий, папки не рендерятся — подвкладки «МОИ СЕССИИ» /
     «АКТИВНЫЕ» вынесены в helper renderTeamTabs и показаны отдельным блоком
     под «НЕТ ДОСТУПНЫХ ТЕКСТОВЫХ ПАКЕТОВ»; загрузка чужих лобби срабатывает
     и без открытой папки (openLayer === 'team' || activeMissions пуст).
     В этой же серии закрыты: перезагрузка списка при каждом клике по
     «АКТИВНЫЕ» (f7927f1, без кэша) и myReadyAt в EngineMission (785b5bd,
     bootstrap-поле). Файлы: src/components/screens/TerminalScreen.tsx,
     src/api/engineApi.ts, backend/app/mission_engine.py.
   - ✅ joinProximityMeters CMS (2026-11-02, 1282294): CMS-поле
     validation_config.geo.joinProximityMeters (optional, default 50000);
     runtime — из config (fallback 50000, DEFAULT_JOIN_PROXIMITY_METERS);
     админка — поле (1000…100000, default 50000); старые миссии — fallback
     50000. Тесты +4 (855 OK, skipped=10).
   - ⚠️ ОСТАЛОСЬ (2026-11-02): проверка на 2 реальных телефонах (пункт выше —
     по коду всё готово); pairwiseProximityMeters (40) — CMS-поле миссии
     (сейчас в админке MissionsSection хардкод 40, в рантайме — константа
     50 км; долг, поле — после решения семантики);
     proofFreshnessSeconds/deadlineSeconds/maxAttempts — хардкод (долг);
     UI-полировка интерфейса — 14.6.

---

## Этап 9. Экономика ROOT и ledger — ✅ закрыт (2026-10-23)

Уже реализовано: Wallet, WalletTransaction, резервы, настройки экономики.

### Шаг 9.1 ✅ Фоновая сверка «баланс = сумма проводок» — закрыт (2026-10-22)
- **Что**: Сверка баланса: эндпоинт GET /api/v1/admin/economy/audit + право economy.read + 3 теста (happy-path, mismatch, 403). Коммиты 1f5d878, d1fd18c. Проверено в браузере: {"ok": true, "total": 2, "mismatches": []} (в dev расхождений нет).
- **Файлы**: сервис ledger, фоновые задачи.
- **Проверка**: искусственное расхождение → отчёт в админке.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 9.1.1 ✅ Row-lock кошелька в mission_engine — закрыт (2026-10-22). Добавлена функция _get_root_wallet_for_update (with_for_update) в mission_engine.py; используется в _award_mission_rewards и _apply_entry_debit (мутирующие пути). Bootstrap — без лока (read-only). На PostgreSQL — защита от lost-update; SQLite — no-op (тесты зелёные). Коммит e616fda. Регрессия: 81/81 (mission) + 52/52 (shop/fallback).

### Шаг 9.2 ✅ Реестр финансовых операций в админке — закрыт (2026-10-22)
- **Что**: Реестр операций: эндпоинт GET /api/v1/admin/economy/transactions (фильтры player_id, type, from, to; пагинация limit/offset; join Wallet→GamePlayer) + 2 индекса (created_at, transaction_type+created_at) + фронт-вкладка «Экономика» (таблица + фильтры + пагинация) + 3 теста. Коммиты 16f44d6, 7d8fbfc. Проверено в браузере: таблица транзакций, фильтр type работает; Player ID — по техническому id (не по имени), записан долг 9.2.1 (поиск по имени).
- **Файлы**: роутер админ-финансов.
- **Проверка**: список проводок доступен, фильтры работают.
- **Зависит от**: —
- **Риск**: низкий
### Шаг 9.2.1 ✅ Поиск в реестре по имени — закрыт (2026-10-23)
- **Что**: search по display_name (LIKE case-sensitive: «Роман» найдёт «Роман», но не «роман») ИЛИ по точному player_id. Поле фронта переименовано: «Player ID» → «Игрок (ID или имя)». Коммит 1339251 (search: бэкенд + фронт + тест); фикс SQLite/кириллица (убран func.lower — SQLite lower() не нормализует кириллицу) — case-sensitive LIKE на SQLite и PostgreSQL (коммит 8cbf6b2). Проверено в браузере: «Роман» находит, «роман» — нет (регистр), uuid — находит.
- **Тесты**: test_transactions_filters_by_search (поиск по имени, по player_id, контроль пересечения имён); регрессия 7/7 test_admin_economy.
- **Замечание**: на PostgreSQL возможна регистронезависимость (ILIKE), отложено. Для мультиязычности — латиница для поиска/уникальных идентификаторов (см. 10.0).
- **Зависит от**: 9.2
- **Риск**: низкий

### Шаг 9.3 ✅ Финансовые тесты — закрыт (2026-10-22)
- **Что**: 3 теста (`backend/tests/test_economy_9_3.py`): (1) интеграция аудита после реальных покупок — mission reward (100) + shop purchase (40) → balance 60, `audit_balances` ok=True, mismatches=[]; (2) семантика fallback-повтора — в fallback_shop committed-guard стоит ДО проверки баланса (как в shop_service), повтор успешной покупки при просевшем балансе возвращает успех, а не 409, баг 9.3.2 не существует; (3) team entry-debit идемпотентность — повторный ready → 409 (state-машина), вторая проводка не создаётся.
- **Файлы**: backend/tests/test_economy_9_3.py.
- **Проверка**: 3/3 новых теста. Регрессия: 58/58 (test_admin_economy + test_fallback_shop + test_shop_service) + 3 новых. Коммит e2739bb.
- **Зависит от**: 9.1, 9.2
- **Риск**: низкий

---

## Этап 10. Переводы ROOT и комиссия Stars — ⚠️ в работе (10.0 — ник, 10.0.1 — поиск игроков, 10.0.2 — карточка бэк, 10.0.3 — карточка фронт, 10.0.4 — PATCH профиля, 10.0.5 — автоопределение страны по координатам, 10.0.5-b — блокировка ручного ввода country, 10.0.6 — анкета игрока — все 10.0.x ✅ закрыты (2026-10-23); 10.1, 10.2, 10.5, 10.1-b (роутер), 10.1-d (фронт) — ✅ закрыты (2026-10-23); 10.3 и 10.6 — ✅ частично (лимиты min/max/daily/earned в сервисе; возраст аккаунта и ручной review — не вводили); 10.4 (газ) — ✅ закрыт (код) (2026-10-24): админка газа (10.4-a…e), CMS (10.4-f), StarsPayment + stars_service (10.4-g), webhook (10.4-h), газ в переводе (10.4-i), фронт игры (10.4-j); долг 10.4-fix — код готов, ждёт постоянного сервера (оплата Android не проходит: trycloudflare — Vite :5173 вместо uvicorn :8000; URL меняется))

### Шаг 10.1 ✅ Модель PlayerTransfer — закрыт (2026-10-23)
- **Что**: модель PlayerTransfer (заявка на перевод ROOT). Модель StarsPayment — в 10.4 (не начат).
- **Файлы**: backend/app/models.py (PlayerTransfer).
- **Проверка**: таблица player_transfers; поля id/from_player_id/to_player_id/amount/status/reference_id/created_at; unique (from_player_id, reference_id) — uq_player_transfers_from_reference; check amount > 0; check status IN ('completed','rejected'); FK RESTRICT; физическое удаление запрещено (статусы completed/rejected). Коммит a8dbfce.
- **Зависит от**: —
- **Риск**: низкий

### Шаг 10.2 ✅ Миграция для переводов — закрыт (2026-10-23)
- **Что**: таблица player_transfers (миграция 74d3bb612729). Таблицы Stars-платежей — в 10.4 (не начат).
- **Файлы**: backend/alembic/versions/74d3bb612729_*.
- **Проверка**: миграция применена (PG + SQLite), схема совпадает с моделью PlayerTransfer. Коммит a8dbfce (тем же коммитом, что и 10.1).
- **Зависит от**: 10.1
- **Риск**: низкий

### Шаг 10.3 ✅ Проверка порога выигрыша — закрыт частично (2026-10-23)
- **Что**: игрок может переводить только после достижения подтверждённого выигрыша (порог из system settings).
- **Файлы**: сервис переводов.
- **Проверка**: лимит minimum_earned_root из CMS (economy.transfer_min/max/daily/minimum_earned_root) читается и проверяется в transfer_root; earned — только mission_reward-кредиты (WalletTransaction). Возраст аккаунта — НЕ вводили (отдельное решение; настройки в каталоге нет).
- **Зависит от**: 10.2
- **Риск**: средний

### Шаг 10.4 ✅ Газ — закрыт (код) (2026-10-24)
- **Что**: отдельная игровая валюта «газ» целиком — админка газа (10.4-a…e), CMS газа (10.4-f), StarsPayment + stars_service (10.4-g), webhook Telegram Stars (10.4-h), газ в переводе (10.4-i), фронт игры — покупка/баланс газа (10.4-j). Отдельный блок.
- **Коммиты**:
  - 10.4-a…e админка газа: 1385876 (модель), 3d36ab0 (карточка gasBalance), 89cb0a1 (PATCH /gas), 8b566a7 (тесты PATCH), 56abde5 (GET /gas-transactions), d5b3c9e (тесты GET), e974fc4 (adminApi), 42a460a (PlayersSection);
  - 10.4-f CMS газа: 51d43f1;
  - 10.4-g StarsPayment + stars_service: 676a0a1, c2b6b2f;
  - 10.4-h webhook: 2fee56c (тесты), 2ca11df;
  - 10.4-i газ в переводе: 2843123;
  - 10.4-j фронт игры: da6f0c5 (10.4-j-1).
- **Проверка**: backend/tests/test_stars_service 5/5, test_webhook_telegram 6/6, test_transfer_pg_10_5 7/7 (PG), test_admin_players 27/27, test_admin_economy 7/7; frontend npm run build (tsc + vite) — OK.
- **Долг 10.4-fix ❌ (код готов, ждёт постоянного сервера)**: sendInvoice + webhook + тесты готовы; оплата не проходит из-за trycloudflare (Vite :5173 вместо uvicorn :8000; URL меняется). Коммиты 97ab958, 1623bce, b649688, cec7d67. Тесты 3/3, 5/5, 45/45.
- **Зависит от**: 10.3
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 10.4-a…e ✅ Админка газа (бэк + админ-фронт) — закрыт (2026-10-23)
- **Что**: отдельная от ROOT игровая валюта «газ» с дробными значениями. Модель GasWallet/GasTransaction (сумма — Numeric(18,4), ledger-проводки g_gas_*), gasBalance в админской карточке игрока (строка, точность Decimal), PATCH /admin/players/{id}/gas (начислить/списать, row-lock, идемпотентность, аудит), GET /admin/players/{id}/gas-transactions (пагинация, limit clamp 1..200), PlayersSection (баланс газа, форма изменения, история последних 50 транзакций).
- **Коммиты**: 1385876 (модель), 3d36ab0 (карточка gasBalance), 89cb0a1 (PATCH /gas), 8b566a7 (тесты PATCH), 56abde5 (GET /gas-transactions), d5b3c9e (тесты GET), e974fc4 (adminApi), 42a460a (PlayersSection).
- **Проверка**: тест в браузере пройден; тесты backend/tests/test_admin_players 27/27, backend/tests/test_admin_economy 7/7, backend/tests/test_transfer_pg_10_5 5/5 (PG).
- **Не сделано (долги, ❌ не начато)**: Stars-инвойс/webhook (10.4); газ в transfer_root; фронт игры (покупка/расход газа).
- **Зависит от**: —
- **Риск**: средний

### Шаг 10.5 ✅ Атомарная проводка перевода в ledger — закрыт (2026-10-23)
- **Что**: две проводки (debit/credit) при переводе ROOT; запись комиссии — в 10.4 (Stars, не начат).
- **Файлы**: backend/app/transfer_service.py (transfer_root + transfer_root_entrypoint), ledger.
- **Проверка**: идемпотентность по (from_player_id, request_id); лимиты из CMS (economy.transfer_min/max/daily/minimum_earned_root); daily — UTC-сутки; блокировка двух кошельков детерминированно (sorted по player_id, без deadlock); debit/credit с reference_type player_transfer_debit/player_transfer_credit; ошибка — полный откат. PG-тесты 5/5 (успех, идемпотентность, ошибки 422/404/403/409/429, daily, параллелизм без overspend) — backend/tests/test_transfer_pg_10_5.py. Коммит 8563cb1.
- **Зависит от**: 10.4 — в исходном плане; фактически ROOT-перевод реализован и закрыт без Stars (10.4 не требуется для перевода ROOT)
- **Риск**: высокий

### Шаг 10.6 ✅ Антифрод переводов — закрыт частично (2026-10-23)
- **Что**: лимиты, возраст аккаунта, запрет для ограниченных, ручной review крупных сумм.
- **Файлы**: сервис переводов, аудит.
- **Проверка**: лимиты min/max/daily из CMS; transfer_restricted — отправитель; blocked/suspended — обе стороны; earned-порог — в transfer_root (в сервисе). Ручной review крупных сумм — НЕ делали (отложено); возраст аккаунта — НЕ вводили.
- **Зависит от**: 10.5
- **Риск**: средний

### Под-шаги 10.1-b и 10.1-d (ROOT-перевод: роутер и фронт) — ✅ закрыты (2026-10-23)
- 10.1-b ✅ Роутер POST /api/v1/players/transfer — коммит 2e40e76. Тонкая обёртка: payload → transfer_root_entrypoint → MissionEngineError → HTTPException (без SessionLocal.begin — транзакция в entrypoint); rate limit 10/min; Depends(get_current_player_id); TransferPayload (to_player_id/amount/request_id). Отдельный тест на роутер не нужен (сервис покрыт 5/5 PG).
- 10.1-d ✅ Фронт — коммиты 729059e (engineApi.transferRoot + типы TransferPayload/TransferResponse: тело snake_case, ответ camelCase) и eaabde8 (TransferScreen + кнопка «Перевод» в MobileNavigation). Экран: поиск через searchPlayers (min 3 символа), выбор получателя, сумма, идемпотентный request_id (генерируется при открытии экрана, не меняется до успешной отправки). Тест на телефоне пройден.

---

## Этап 11. Вывод ROOT в TON — ✅ код закрыт (11.1–11.7-b; 11.8 — долг)

> План 11.0–11.8 утверждён с заказчиком (2026-10-26). Ключевые решения:
> 4-й кошелёк — «спец» payout: адрес в CMS (ton.payout_wallet),
> мнемоника в .env (TON_PAYOUT_MNEMONIC), сеть TON_NETWORK=testnet.
> Вывод — только целый ROOT (1:1), минимум 10. Валидация TON-адреса —
> через pytoniq, не regex. Жизненный цикл заявки: pending →
> approved/rejected → processing → confirmed/failed.
>
> **Примечание (2026-10-26):** код закрыт (коммиты до e5a7e7f).
> Остался реальный testnet transfer (требует ключей в .env).

### Шаг 11.0: TON-адрес игрока (кошелёк игрока)
- **Что**: игрок привязывает единственный TON-адрес для вывода
  (ton_wallets, one player — one address). Четвёртый кошелёк — «спец»
  payout: адрес в CMS (ton.payout_wallet), мнемоника — в .env
  (TON_PAYOUT_MNEMONIC), TON_NETWORK=testnet.
- **Файлы**: backend/app/models.py (TonWallet — готово), ton_service, CMS.
- **Проверка**: привязка/замена/удаление адреса; спец-адрес payout
  читается из CMS, мнемоника — из .env (не в БД, не в коде).
- **Зависит от**: 11.1, 11.3, 11.3-b
- **Статус**: ⏳ (модель готова в 11.1; логика привязки — впереди)
- **Риск**: средний (секреты, адреса)

### Шаг 11.1: Модель TonWallet и WithdrawalRequest
- **Что**: модели TON-адресов и заявок на вывод. amount_root — BigInteger
  (пометка 11.8: сейчас 1:1 целый ROOT, позже — NanoROOT 10^8).
- **Файлы**: backend/app/models.py (TonWallet, WithdrawalRequest).
- **Проверка**: создать записи (адрес, заявку).
- **Зависит от**: —
- **Статус**: ✅ готово
- **Риск**: низкий

### Шаг 11.2: Миграция для TON-адресов и заявок
- **Что**: таблицы ton_wallets и withdrawal_requests: FK ON DELETE
  RESTRICT, unique (player_id), unique (address), check-констрейнты
  статусов и amount_root > 0, индексы (player_id, status, ton_tx_hash,
  batch_id). downgrade — NotImplementedError (immutable-журнал).
- **Файлы**: backend/migrations/versions/3a1eaf8079e4_...py
- **Проверка**: alembic upgrade head на свежей SQLite (SQLite +
  Postgres); тесты 45/45, 5/5.
- **Зависит от**: 11.1
- **Статус**: ✅ готово
- **Риск**: низкий

### Шаг 11.3: CMS — параметры вывода
- **Что**: через System Settings: ton.payout_wallet (адрес «спец»
  payout-кошелька), ton.min_amount_root (минимум 10, целый ROOT),
  комиссия, статус фичи (вкл/выкл), лимиты.
- **Файлы**: SystemSettings (CMS), сервис вывода.
- **Проверка**: параметры читаются из CMS и применяются в сервисе.
- **Зависит от**: —
- **Статус**: ✅ готово
- **Риск**: низкий

### Шаг 11.3-b: Секреты — мнемоника в .env
- **Что**: мнемоника спец-кошелька — TON_PAYOUT_MNEMONIC в .env,
  TON_NETWORK=testnet. Секреты не в БД, не в коде, не в логах;
  в конфигах — только redacted-значения.
- **Файлы**: .env, config (pydantic settings).
- **Проверка**: секреты доступны только из окружения.
- **Зависит от**: 11.3
- **Статус**: ⏳
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.4: Интеграция с TON SDK + pytoniq
- **Что**: подключение TON SDK, отправка транзакций, отслеживание
  статуса. Валидация TON-адреса — через pytoniq, НЕ regex.
- **Файлы**: сервис TON (ton_service).
- **Проверка**: тестовая транзакция в testnet; невалидные адреса
  отклоняются библиотекой pytoniq.
- **Зависит от**: 11.3-b
- **Статус**: ✅ готово
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.5-a: Логика заявки на вывод
- **Что**: вывод — только 1:1 целый ROOT, минимум 10; резервирование,
  атомарность, идемпотентность, row-lock; проводки — только immutable
  WalletTransaction (ledger — source of truth). Жизненный цикл заявки:
  pending → approved/rejected → processing → confirmed/failed.
- **Файлы**: сервис вывода, ledger, роутер.
- **Проверка**: полный цикл от заявки до confirmed; отказ при
  недостаточном балансе и при сумме < минимума/не кратной 1 ROOT.
- **Зависит от**: 11.4, 11.2
- **Статус**: ✅ готово
- **Риск**: высокий ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.5-b: Батч-вывод и повторы
- **Что**: пакетная отправка по batch_id, обработка зависших
  processing-заявок, повторные попытки без двойных списаний.
- **Файлы**: сервис вывода, фоновые задачи.
- **Проверка**: заявки в батче получают общий batch_id; повтор не
  создаёт двойных списаний.
- **Зависит от**: 11.5-a
- **Статус**: ✅ готово
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 11.6: Админ-панель вывода и ручная сверка
- **Что**: просмотр заявок, approve/reject (крупные — с approval
  super-admin), сверка по ton_tx_hash (processing → confirmed), reason,
  аудит в admin_audit_log.
- **Файлы**: роутер админ-финансов, adminApi.
- **Проверка**: администратор видит и подтверждает заявки; каждая
  операция — в аудите.
- **Зависит от**: 11.5-a, 11.5-b
- **Статус**: ✅ готово
- **Риск**: средний

### Шаг 11.6-b: Админ-фронт «Заявки на вывод»
- **Что**: фронт админки (adminApi): список заявок на вывод,
  батч-выплата (POST /api/v1/admin/withdrawals/batch), отклонение
  с причиной (POST /api/v1/admin/withdrawals/{id}/reject), отображение
  статусов и ton_tx_hash.
- **Файлы**: frontend админки, adminApi.
- **Проверка**: админ видит заявки (включая seed-тестовые), проводит
  батч и отклонение с reason; каждая операция — в аудите.
- **Зависит от**: 11.6
- **Статус**: ✅ готово
- **Риск**: низкий

### Шаг 11.7: Фронт — привязка адреса и экран вывода
- **Что**: привязка TON-адреса игроком, экран заявки на вывод (сумма
  кратна 1 ROOT, мин. 10), история заявок со статусами.
- **Файлы**: frontend (Telegram Mini App), engineApi.
- **Проверка**: игрок подаёт заявку; статусы обновляются.
- **Зависит от**: 11.5-a, 11.6
- **Статус**: ✅ готово
- **Риск**: средний

### Шаг 11.7-a: Бэкенд /api/v1/me/withdrawals (GET/POST)
- **Что**: GET — список своих заявок (limit/offset); POST — создание
  заявки. Ответ игрока: withdrawalId, amountRoot, toAddress, status,
  tonTxHash, reason, createdAt, updatedAt. POST-тело — snake_case:
  {amount_root, to_address}.
- **Файлы**: backend/app/main.py (роутер игрока), engineApi.ts
  (createWithdrawal, listMyWithdrawals).
- **Проверка**: игрок создаёт заявку и видит её в своём списке.
- **Зависит от**: 11.5-a, 11.6
- **Статус**: ✅ готово
- **Риск**: низкий

### Шаг 11.7-b: Фронт игрока — блок «Вывод ROOT → TON»
- **Что**: в ProfileScreen блок «Вывод ROOT → TON»: форма заявки
  (сумма ROOT, адрес из сохранённого TON-кошелька), список «Мои
  заявки» со статусами (pending/confirmed/rejected/failed) и reason.
- **Файлы**: src/components/screens/ProfileScreen.tsx, engineApi.ts.
- **Проверка**: игрок подаёт заявку; статусы обновляются;
  npm run build — OK.
- **Зависит от**: 11.7-a
- **Статус**: ✅ готово
- **Риск**: низкий

### Шаг 11.8: NANO-ROOT (дробный ROOT) — ❌ долг, отложено
- **Что**: NanoROOT — дробный ROOT с 8 знаками (10^8). Отложено.
  amount_root уже BigInteger (готов) — миграция схемы при вводе
  NanoROOT не понадобится.
- **Файлы**: — (модель готова, миграция применена)
- **Проверка**: — (при реализации: дробные суммы, вывод/отображение).
- **Зависит от**: 11.7
- **Статус**: ❌ долг
- **Риск**: низкий (схема готова)

> ⚠️ **Известный технический долг (2026-10-26):** требуется тестирование
> в реальной сети (testnet): проверить реальный вывод ROOT в TON
> с реальным кошельком (ключи в .env) и убедиться в работоспособности
> send_jetton_transfer_sync без моков.

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

## Этап 13. Модерация, страны, логи, ошибки — 13.1–13.5 ✅, 13.6 — ❌ долг

### ✅ Шаг 13.1: Модель CountryPolicy
- **Что**: политики стран (allowed/restricted/blocked) с ограничениями по функционалу.
- **Файлы**: файл моделей.
- **Проверка**: создать политику.
- **Зависит от**: —
- **Риск**: низкий
- **Статус**: ✅ 2026-10-24 — модель CountryPolicy + миграция 0c18f7c8ed6a. Коммит 39e730a.

### ✅ Шаг 13.2: Миграция и админ-роутер CountryPolicy
- **Что**: миграция + CRUD для политик.
- **Файлы**: папка миграций, роутер.
- **Проверка**: изменение политики применяется к игрокам.
- **Зависит от**: 13.1
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ
- **Статус**: ✅ 2026-10-24 — CRUD политик + применение: blocked на входе, restricted в transfer/mission/team. Коммиты 83622cb, d625399, 855fe67, aa57637 (helper-тесты), 9b26f40 (integration). Тесты 5/5, 3/3, 4/4.

### ✅ Шаг 13.3: Модель PlayerEvent
- **Что**: логи действий игроков (auth.login, mission.accepted, transfer.completed и т.д.).
- **Файлы**: файл моделей.
- **Проверка**: создать событие.
- **Зависит от**: —
- **Риск**: низкий
- **Статус**: ✅ 2026-10-24 — модель PlayerEvent + миграция 6b6ae360eebc + 5 точек эмиссии. Коммиты c496c17, 2b3c1bf, 2a39146, f0fd165, c89b31d. Тесты 6/6.

### ✅ Шаг 13.4: Middleware и модель AppError
- **Что**: сбор ошибок приложения с correlation_id, severity, безопасным контекстом.
- **Файлы**: middleware, файл моделей.
- **Проверка**: ошибка сохраняется и отображается в админке.
- **Зависит от**: —
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ
- **Статус**: ✅ 2026-10-24 — модель AppError + миграция 50178ee857c8 + middleware (correlation_id, severity, безопасный контекст). Коммиты 183ddfc, 76e3fbb, 7d1589a. Тесты 4/4.

### ✅ Шаг 13.5: Админ-раздел «Ошибки и события»
- **Что**: просмотр ошибок, событий игроков, фильтры, комментарии оператора.
- **Файлы**: роутер админ-мониторинга.
- **Проверка**: список ошибок доступен.
- **Зависит от**: 13.3, 13.4
- **Риск**: низкий
- **Статус**: ✅ 2026-10-24 — админ-раздел «Мониторинг» (Ошибки + События, фильтры, пагинация): эндпоинты + adminApi + фронт MonitoringSection + вкладка. Коммиты 07dd893, 170ee7f, c5a1e30. Тесты 5/5. Тест в браузере пройден.

### ❌ Шаг 13.6: Интеграция Sentry или GlitchTip
- **Что**: отправка критичных ошибок во внешнюю систему мониторинга.
- **Файлы**: инфраструктура, middleware.
- **Проверка**: тестовая ошибка появляется в Sentry.
- **Зависит от**: 13.4
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ
- **Статус**: ❌ долг (2026-10-24) — Sentry/GlitchTip; отложено. Зависит от 13.4.

---

## Этап 14. Frontend и мобильный клиент — ⚠️ в работе

Уже: 5 игровых экранов (архив, брифинг, инвентарь, сканер, терминал), API-клиенты, каркас админки.

### Шаг 14.1: Экран «Карта и геозоны»
- **Что**: карта с доступными зонами и активными AR-объектами.
- **Файлы**: frontend-страницы.
- **Проверка**: зоны отображаются, клик открывает детали.
- **Зависит от**: 3.8, 8.2
- **Риск**: средний ⚠️ ТРЕБУЕТ СОГЛАСОВАНИЯ

### Шаг 14.2: Экран «Команда и чат» — 🔲 не начат
- **Что**: отдельный интерфейс постоянной команды, участников, приглашений и
  чата команды.
- **Файлы**: frontend-страницы.
- **Проверка**: список участников, отправка сообщений.
- **Статус**: 🔲 не начат (2026-11-01). MVP чата уже живёт в
  `TeamSessionScreen` (чат внутри командной сессии, 6.6); отдельный экран
  постоянной команды — позже.
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

### Шаг 14.6: UI-полировка (дизайн интерфейса) — 🔲 не начат
- **Что**: обновление UI командных сессий (чат, мини-игра, плашки, финальные
  экраны), единый дизайн интерфейса; делать после функционала, отдельным
  этапом.
- **Файлы**: frontend-компоненты и стили.
- **Проверка**: визуальная согласованность и ручная проверка на телефоне.
- **Статус**: 🔲 не начат (2026-11-01) — долг: функционал важнее дизайна.
- **Зависит от**: 8.x (командные миссии), 6.6
- **Риск**: низкий

---

## Этап 15. Тестирование, защита и запуск — ⚠️ в работе

Уже: 9 файлов тестов, Docker, nginx, бэкапы.

- **Регрессия backend (2026-11-01)**: ✅ 839 unittest-тестов OK, skipped=10 (PG-тесты без локального Postgres). Фикстуры `test_economy_9_3` и `test_team_wave_flow` обновлены под оплату при accept (ROOT/items до create/join). Детали — `docs/audit-2026-10-04.md`.
- **Регрессия backend (2026-10-31)**: ✅ 818 unittest-тестов OK, skipped=10 (PG-тесты без локального Postgres). Предсуществующих падений нет: `test_admin_system_settings` закрыт seed-миграцией `dde2038a44d9` (8 ключей каталога system_settings, коммит `28aa656` — CMS admin PUT больше не отдаёт 422), `test_team_entry_debit_idempotent` приведён к флоу join-session (коммит `2452b6d`). Детали — `docs/audit-2026-10-04.md`.

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
