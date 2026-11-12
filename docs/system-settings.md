# System Settings

## Назначение
`SystemSetting` хранит операционные, не секретные параметры игры и платформы.
PostgreSQL является source of truth. Кэширование разрешено только как оптимизация.

Секреты, пароли, token/hash, bot token, private/signing key, Telegram initData,
TON credentials и иные секретные значения в system settings не хранятся.

## Lifecycle и целостность
Настройка имеет lifecycle `active -> archived`. Физическое удаление запрещено.
Ключ настройки неизменяем. История изменения значения сохраняется в
`admin_audit_log`; audit-записи не переписываются.

В коде допускаются только:
- каталог допустимых ключей;
- schema/type validation;
- bounds и cross-field validation;
- механизм чтения/записи;
- security, approval и state machine.

Значения контента, игровые лимиты, economy parameters и feature flags не должны
быть захардкожены в доменной логике.

## Поля
- `key`: уникальный неизменяемый machine-readable ключ;
- `value_json`: типизированное не секретное значение;
- `value_type`: `integer`, `boolean`, `string`, `json`;
- `category`, `title`, `description`;
- `is_sensitive`: требует approval для изменения;
- `status`: `active` или `archived`;
- `created_by_admin_id`, `updated_by_admin_id`;
- timestamps.

## Начальный каталог

| Key | Type | Default | Sensitive |
|---|---:|---:|---:|
| `missions.max_active_solo` | integer | 1 | no |
| `missions.max_active_team` | integer | 1 | no |
| `missions.max_active_global` | integer | 1 | no |
| `missions.default_max_attempts` | integer | 3 | no |
| `missions.default_attempt_reward_multipliers` | json | `[1.0, 0.5, 0.25]` | no |
| `approvals.default_expiry_seconds` | integer | 86400 | yes |
| `economy.transfer_minimum_earned_root` | integer | 50 | yes |
| `economy.transfer_min_amount` | integer | 1 | yes |
| `economy.transfer_max_amount` | integer | 10000 | yes |
| `economy.daily_transfer_limit` | integer | 50000 | yes |
| `economy.manual_adjustment_approval_threshold` | integer | 1000 | yes |
| `economy.mission_force_complete_approval_threshold` | integer | 5000 | yes |
| `referral.enabled` | boolean | false | no |
| `referral.reward_root` | integer | 25 | yes |
| `telegram.bot_username` | string | "" | no |
| `features.demo_seed_enabled` | boolean | false | yes |
| `features.demo_reset_enabled` | boolean | false | yes |
| `geo.solo_proof_mode` | string | "off" | no |

Значения limits и economy не могут быть отрицательными. `default_max_attempts`
должен быть от 1 до 10. Массив multipliers должен содержать ровно
`default_max_attempts` чисел от 0 до 1, быть не возрастающим, а первое значение
должно равняться `1.0`.

Флаги features.demo_* зарезервированы для development-инструментов вне production
и не включаются до demo cleanup. Публичный reset endpoint удалён (3.11.a).
Backup, аудит и удаление demo-данных — отдельная задача.

### Реферальная программа (Sprint Referral R-2)

`referral.enabled` — рубильник программы. По умолчанию выключена: включение —
осознанное действие через CMS, а не побочный эффект деплоя. Флаг управляет
только начислением награды (и видимостью блока в профиле); привязка реферера
при регистрации от него не зависит.

`referral.reward_root` — сколько ROOT получает пригласивший, когда приглашённый
достигает порога `economy.transfer_minimum_earned_root` (тот же порог, что даёт
доступ к переводам). Ключ sensitive: правка не-суперадмином — только через
approval workflow. Значение попадает в `ReferralReward.amount_root` в момент
привязки, поэтому изменение настройки не переписывает уже созданные награды.

### Имя Telegram-бота (Sprint 8.x-ref-link-cms)

`telegram.bot_username` — username бота без `@` (например,
`HimeraProtocolBot`). Используется для сборки реферальной ссылки
(`https://t.me/<bot_username>?start=ref_<playerId>`).

Приоритет: CMS-first (значение из system_settings) → fallback на env
`TELEGRAM_BOT_USERNAME`. Ведущий `@` нормализуется (обрезается).

Ключ не sensitive (username публичен — он виден в самой ссылке), менять
может любой админ с правом `system_settings.manage`. Пустое значение =
fallback на env (текущее поведение до CMS).

## Permissions и API
- `system_settings.read`: чтение каталога и значений;
- `system_settings.manage`: изменение non-sensitive active settings напрямую;
- super-admin имеет все permissions напрямую.

API:
- `GET /api/v1/admin/system-settings`;
- `GET /api/v1/admin/system-settings/{key}`;
- `PUT /api/v1/admin/system-settings/{key}` — только direct
  `system_settings.manage`, только non-sensitive key;
- `POST /api/v1/admin/system-settings/{key}/approval-requests` — создаёт
  approval request для sensitive key с immutable proposed-value snapshot;
- `POST /api/v1/admin/system-settings/approval-requests/{id}/execute` —
  отдельный domain executor только для approved request типа
  `system_setting.change`.

Инициатор approval не может его approve/reject. Executor не универсален:
он принимает только `system_setting.change`, повторно валидирует ключ, snapshot,
текущий lifecycle и schema, блокирует строки `FOR UPDATE`, идемпотентно меняет
настройку и переводит заявку в final execution state в одной транзакции.

## Audit
Каждая create/archive/update/request/review/execute операция создаёт audit event.
В before/after пишутся ключ, type, status и безопасные значения. Секретные
значения запрещены. Audit содержит permission, request/approval ID, actor ID,
IP и безопасный outcome/error context; free-text reason не дублируется и
фиксируется только безопасным признаком `reasonProvided`.

<!-- stage-3-2-runtime-contract-reconciliation -->

## Mission-runtime configuration boundary

The current catalog provides platform defaults, active-run limits, and feature
flags. Mission-specific entry prices, item requirements, exact attempt policy,
cipher configuration, reward policy, repeatability, fallback product binding,
product price, pool policy, and product lifecycle remain validated versioned
CMS configuration and become part of immutable effective run snapshots.

Future System Settings keys for runtime rollout, fallback/shop feature flags,
or bounded idempotency retention require a separate catalog, validation,
permissions, audit, and approval change before use. Runtime code must not use
an undocumented or hardcoded setting.

Related target contracts: `docs/mission-run-contract.md`,
`docs/inventory-ledger-contract.md`, and `docs/fallback-shop-contract.md`.
