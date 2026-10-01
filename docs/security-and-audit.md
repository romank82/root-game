# Безопасность и аудит

## Реализовано
Telegram initData проверяется на backend по HMAC и сроку действия.
Не доверяются standalone Telegram ID и `initDataUnsafe`.
Используются HttpOnly/SameSite=Lax cookies; secure включён в production.

Admin passwords хэшируются Argon2id. Admin sessions server-side; logout и
deactivation отзывают сессии.

## Audit
Аудит содержит actor, username snapshot, permission, action, entity,
request ID, approval request ID, server-generated correlation ID, direct-peer
IP, user-agent, outcome и ограниченный error context (`code`, `category`,
`retryable`).

`admin_audit_log` immutable: application не выполняет update/delete, а DB
triggers запрещают изменение и удаление audit records. Для approval workflow
audit хранит allowlisted state/identity projection и безопасные признаки
наличия payload/reason/comments; arbitrary payload snapshots, свободный текст
reason/comments, raw execution details и free-text domain reasons в audit не
дублируются. Для новых событий legacy-column `reason` всегда записывается
как `NULL`.

Generic approval creation endpoint intentionally unavailable: `POST /api/v1/admin/approvals`
returns HTTP 410 Gone to prevent arbitrary `actionType`, `target`, `requestId`
and `payloadSnapshot` from being persisted into approval/audit domain.
AdminApprovalRequest создаётся только domain-specific endpoints/services
с domain-валидацией.

Никогда не логируются passwords, password hashes, session tokens, API keys,
bot tokens, signing secrets, private keys, полный Telegram initData,
секретные validation answers, cookies, arbitrary request headers, exception
messages или tracebacks.

Public CMS content follows `docs/segment-content-contract.md`: validation configuration, accepted answers, correct sequences, server-side award rules, and protected state never enter public bootstrap or the frontend bundle. A reward preview is informational; only backend transactions grant ROOT, items, progress, or status changes.

Перед destructive migration обязателен проверенный backup.
