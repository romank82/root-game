# Административные полномочия

## Текущая модель
Super-admin имеет все permissions напрямую. Обычный admin получает
индивидуальный grant с `direct` или `requires_super_admin_approval`.

Текущий каталог:
`admins.read`, `admins.manage`, `admin_permissions.manage`,
`admin_approvals.read`, `admin_approvals.review`, `audit.read`,
`missions.read`, `missions.manage`.

## Защиты
Нельзя деактивировать себя или последнего active super-admin.
Деактивация отзывает все server-side sessions target admin.
Изменения прав и админ-аккаунтов аудитируются.

## Целевое расширение
Добавляются permissions для content, players, teams, wallets, transfers,
withdrawals, geo, shop, economy, countries, system settings и errors.
Инициатор не может выдать себе право или одобрить собственную заявку.
