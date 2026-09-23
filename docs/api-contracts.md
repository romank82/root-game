# API-контракты

## Public/game API
- `POST /api/v1/auth/telegram`
- `POST /api/v1/auth/logout`
- `GET /api/v1/engine/bootstrap`
- `POST /api/v1/engine/missions/{mission_id}/submit`
- `POST /api/v1/engine/reset-demo-progress` — только вне production.

## Admin API
- `POST /api/v1/admin/auth/login`
- `POST /api/v1/admin/auth/logout`
- `/api/v1/admin/missions` — list/get/create/update/publish/unpublish.
- `/api/v1/admin/admins` — list/create/grant/revoke/deactivate/reactivate.

## Известное расхождение
Frontend вызывает `GET /api/v1/admin/auth/me`, но этот route не найден среди
зарегистрированных backend routes. Контракт нужно согласовать до UI-расширений.

Secrets, hashes, raw tokens и validation answers не возвращаются API.
