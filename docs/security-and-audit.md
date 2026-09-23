# Безопасность и аудит

## Реализовано
Telegram initData проверяется на backend по HMAC и сроку действия.
Не доверяются standalone Telegram ID и `initDataUnsafe`.
Используются HttpOnly/SameSite=Lax cookies; secure включён в production.

Admin passwords хэшируются Argon2id. Admin sessions server-side; logout и
deactivation отзывают сессии.

## Audit
Аудит содержит actor, permission, action, entity, before/after, reason,
request ID, approval request ID, IP и outcome.

Никогда не логируются passwords, password hashes, session tokens, API keys,
bot tokens, signing secrets, private keys, полный Telegram initData или
секретные validation answers.

Перед destructive migration обязателен проверенный backup.
