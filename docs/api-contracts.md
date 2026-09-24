# API-контракты

## Public/game API
- `POST /api/v1/auth/telegram`
- `POST /api/v1/auth/logout`
- `GET /api/v1/engine/bootstrap`
- `POST /api/v1/engine/missions/{mission_id}/submit`
- `POST /api/v1/engine/reset-demo-progress` — только вне production.

## Admin API
- `POST /api/v1/admin/auth/login`
- `GET /api/v1/admin/auth/me` — текущий admin без credentials/session token.
- `POST /api/v1/admin/auth/logout`
- `/api/v1/admin/missions` — list/get/create/update/publish/unpublish.
- `/api/v1/admin/admins` — list/create/grant/revoke/deactivate/reactivate.
- `/api/v1/admin/approvals` — создать заявку, список собственных заявок;
  super-admin видит все заявки.
- `POST /api/v1/admin/approvals/{id}/approve` — только другой super-admin.
- `POST /api/v1/admin/approvals/{id}/reject` — только другой super-admin.
- `/api/v1/admin/system-settings` — catalog/list/get/update non-sensitive
  settings; sensitive changes use a dedicated approval workflow.


## System settings
Settings API never returns or stores secrets. `PUT /api/v1/admin/system-settings/{key}`
requires direct `system_settings.manage` and rejects sensitive keys. Sensitive
settings use a dedicated `system_setting.change` approval request and a dedicated
executor; there is no generic approval execute endpoint.

## Approval workflow
`POST /api/v1/admin/approvals` доступен только обычному admin с активным
grant режима `requires_super_admin_approval`. Поля `payloadSnapshot`,
`actionType`, target и reason становятся неизменяемым snapshot заявки.

`requestId` обязателен и идемпотентен в пределах инициатора: повтор того же
requestId с тем же содержимым возвращает исходную заявку, с другим — `409`.

Approval API не исполняет операции. Каждая опасная операция подключается
отдельным executor'ом с повторной бизнес-валидацией, блокировкой записи,
идемпотентностью и транзакцией.

Secrets, hashes, raw tokens и validation answers не возвращаются API.
