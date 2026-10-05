Telegram AR-игра (аналог Pokémon Go)

Стек: Python/FastAPI, SQLAlchemy, PostgreSQL, SQLite (локальный dev), Alembic, Docker, Telegram Bot API, TON SDK, frontend Telegram Mini App.

Формат работы
Работаем пошагово через терминал пользователя. Не считать команды выполненными, пока пользователь не прислал их вывод. Сначала диагностика/read-only, затем backup, затем изменение, затем валидация. Не применять destructive DB-операции, alembic stamp, ручное изменение alembic_version или удаление данных без отдельного обоснования, проверенного backup и плана отката. Не просить и не выводить пароли, DATABASE_URL, токены, Telegram initData, private keys, хэши паролей или иные секреты. Для конфигов показывать только безопасные метаданные/redacted values. Не использовать set -e в диагностических блоках, если это может закрыть терминал и скрыть ошибку.

Contracts First
Любая новая фича сверяется с docs/: architecture.md, game-rules.md, api-contracts.md, security-and-audit.md, admin-permissions.md и будущими профильными документами. Если документация не показана — сначала запросить/проверить релевантные документы и текущий код.

CMS-first / No Hardcoded Logic
Миссии, награды, ключи, предметы, зоны, AR-объекты, лимиты, экономические параметры и feature flags управляются через CMS/system settings. В коде — механизмы, валидация, state machine, security и domain executors, но не захардкоженные игровые правила.

Финансовая целостность
ROOT меняется только immutable-проводками WalletTransaction. Balance — кэш, ledger — source of truth. Финансовые, инвентарные и статусные операции атомарны, идемпотентны, с блокировками где нужно, и не допускают отрицательный баланс.

Безопасность, аудит, данные
Permission-based admin access. Опасные действия требуют approval super-admin. Никакого универсального execute(action_type): исполнение только отдельными domain-executor’ами с повторной validation, row locks, idempotency, транзакцией и audit.
Все admin-действия пишутся в immutable admin_audit_log. В audit/logs запрещены пароли, password hashes, токены, cookies, API keys, bot token, секреты, private keys, Telegram initData и избыточные private data.
Физическое удаление игровых сущностей, прогресса и связанных данных запрещено. Lifecycle: draft → published → archived. History, ledger и audit не перезаписываются.

DB changes
Любая схема меняется только Alembic migrations. Перед destructive migration обязателен проверенный backup. Миграции должны учитывать поддерживаемые окружения: локальный SQLite dev и Docker PostgreSQL. PostgreSQL-specific SQL — только dialect-aware либо при явно ограниченной поддержке окружений.

Уже реализовано
Docker/PostgreSQL/Alembic; базовые Telegram/admin auth; super-admin, admin accounts, individual permissions; direct/requires_super_admin_approval permissions; создание admin, grant/revoke, deactivate/reactivate; защита от деактивации себя/последнего active super-admin.
AdminApprovalRequest: immutable заявки, idempotency, approve/reject другим super-admin, expiry, audit; DB unique constraint (requested_by_admin_id, request_id); approval API не исполняет опасные действия generic endpoint’ом.
Добавлены System Settings foundation и approval execution state migration.

Audit foundation — выполнено локально
Создан централизованный backend/app/admin_audit.py с write_admin_audit(). Прямые AdminAuditLog writer’ы в admin-модулях заменены helper’ом. Реализованы recursive redaction sensitive keys, allowlist error_context (code/category/retryable), correlation_id, username snapshot, user-agent, safe outcome/error metadata.
Добавлена migration 4e3a8a28f363_harden_admin_audit_trail.py: correlation_id NOT NULL с legacy backfill, username snapshot, user_agent, error_context_json, индекс correlation_id, DB triggers, запрещающие UPDATE/DELETE audit records. Migration dialect-aware для PostgreSQL и SQLite.
Исправлена SQLite-совместимость migration d19f7a3e8b62: unique constraint approval idempotency через batch_alter_table.
Рабочая SQLite backend/chimera.
## Правила разработки (обязательно для агента)

### Ничего не ломать
- Перед любым изменением агент обязан проверить, какие модули зависят от редактируемого файла.
- Если изменение может затронуть существующие механики (миссии, ledger, аудит, approvals) — сначала остановиться и предупредить меня.
- Запрещено удалять или переписывать работающий код без явного указания.

### Согласование глобальных изменений
- Любое изменение, затрагивающее больше одного модуля, требует моего письменного подтверждения в чате.
- Агент обязан объяснить простыми словами: что меняется, зачем, какие риски, как откатить.
- Не начинать реализацию, пока я не напишу «согласен» или «подтверждаю».

### Связь с существующим кодом
- Создавая новый файл, функцию или скрипт, агент обязан сначала:
  1. Показать, какие существующие модули уже решают похожую задачу.
  2. Объяснить, почему нельзя переиспользовать или расширить их.
  3. Убедиться, что новое не дублирует функциональность.
- Все новые сущности должны быть согласованы с docs/ (contracts-first).

### Тестирование после каждого шага
- Каждый шаг завершается запуском релевантных тестов.
- Если тестов нет — агент пишет минимальный тест или сценарий ручной проверки.
- При ошибке: агент сам диагностирует, исправляет и повторяет тест до зелёного результата.
- Результат теста прикладывается в отчёте о выполненном шаге.

### Формат отчёта о выполненном шаге
Агент обязан после каждой завершённой задачи выдать:
1. Что сделано (2–3 предложения простыми словами).
2. Какие файлы изменены/созданы.
3. Какие тесты запущены и их результат.
4. Что дальше (следующий шаг из дорожной карты).
5. Нужно ли моё подтверждение для продолжения.
