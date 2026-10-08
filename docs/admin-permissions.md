# Административные полномочия

## Текущая модель
Super-admin имеет все permissions напрямую. Обычный admin получает
индивидуальный grant с `direct` или `requires_super_admin_approval`.

Текущий каталог:
`admins.read`, `admins.manage`, `admin_permissions.manage`,
`admin_approvals.read`, `admin_approvals.review`, `audit.read`,
`missions.read`, `missions.manage`, `segments.read`, `segments.manage`,
`players.read`, `players.manage`, `players.restrict`, `players.block`.

`players.manage` — игрок-ориентированные ручные операции, требующие админ-вмешательства:
кошелёк (5.4, `player.wallet_credit/debit`), инвентарь (5.5,
`player.inventory_grant/revoke`), миссии (5.6, `player.mission_cancel/...`).
Разрешённые action_type для каждого поддомена — в каталоге action_type соответствующих модулей.

`players.restrict` (5.7) — создание и снятие гранулярных ограничений:
`chat_restricted`, `transfer_restricted`, `team_restricted`,
`mission_restricted`, `payment_restricted`, `withdrawal_restricted`
(action_type `player.restriction_create` / `player.restriction_revoke`).
Эти типы не запирают вход и не меняют `GamePlayer.status`.

`players.block` (5.7) — те же операции для запирающих типов ограничений:
`blocked` и `suspended`. Они переводят `GamePlayer.status` в не-active
(вход запрещён), поэтому требуют отдельного, более чувствительного гранта.
При create/revoke статус синхронизируется всегда; истёкшие ограничения
лениво снимаются (lazy expiry) и не блокируют вход навсегда.

Mission runtime policies (`mission_runtime_policies`) управляются тем же
правом `missions.manage` — это конфигурация правил входа конкретной миссии,
не отдельный домен.

## Защиты
Нельзя деактивировать себя или последнего active super-admin.
Деактивация отзывает все server-side sessions target admin.
Изменения прав и админ-аккаунтов аудитируются.

## Целевое расширение
Добавляются permissions для content, players, teams, wallets, transfers,
withdrawals, geo, shop, economy, countries, system settings и errors.
Инициатор не может выдать себе право или одобрить собственную заявку.
