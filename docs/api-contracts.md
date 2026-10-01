# API-контракты

## Public/game API
- `POST /api/v1/auth/telegram`
- `POST /api/v1/auth/logout`
- `GET /api/v1/engine/bootstrap`
- `POST /api/v1/engine/missions/{mission_id}/submit`
- `POST /api/v1/engine/reset-demo-progress` — только вне production.

`GET /api/v1/engine/bootstrap` returns only public player content. Schema and redaction policy for `Segment.content` and `Mission.content` are defined in `docs/segment-content-contract.md`; validation configuration, answers, and server-side award rules are excluded.

## Planned geo/team API (not implemented)

The following target routes require authenticated player identity and an
idempotency key for every mutation:

- `POST /api/v1/engine/missions/{mission_id}/location-proofs`
- `POST /api/v1/engine/missions/{mission_id}/team-sessions/join`
- `POST /api/v1/engine/team-sessions/{session_id}/ready`
- `POST /api/v1/engine/team-sessions/{session_id}/leave`
- `GET /api/v1/engine/team-sessions/{session_id}`
- `POST /api/v1/engine/mission-runs/{run_id}/attempts`
- `POST /api/v1/engine/mission-attempts/{attempt_id}/submit`

Responses expose only caller-permitted state and never raw location proofs,
protected QR data, challenge validation material, other players private data,
or settlement internals. Exact behavior is defined in
`docs/geo-team-mission-contract.md`.

## Admin API
- `POST /api/v1/admin/auth/login`
- `GET /api/v1/admin/auth/me` — текущий admin без credentials/session token.
- `POST /api/v1/admin/auth/logout`
- `/api/v1/admin/missions` — list/get/create/update/publish/unpublish.
- `/api/v1/admin/segments` — list/get/create/update/publish/unpublish/archive;
  physical `DELETE` is unavailable.
  - `GET /api/v1/admin/segments` and `GET /{segment_id}` require direct
    `segments.read`;
  - create/update/publish/unpublish/archive require direct `segments.manage`;
  - create/update accept ordered links as `linkedMissions`, each with
    `missionId` and `sortOrder`;
  - every linked Mission must exist and have the same `chapterId` as Segment;
  - SegmentMission links use lifecycle `active -> archived`; API never
    physically deletes a link;
  - update archives omitted active links, updates `sortOrder` only for active
    links, and creates a new immutable link record when a previously archived
    `(segmentId, missionId)` pair is added again;
  - at most one active link may exist for a `(segmentId, missionId)` pair;
  - publishing requires at least one active linked Mission, and every active
    linked Mission must be `published`;
  - `archived` Segment is final and cannot be published, unpublished, or edited.
- `/api/v1/admin/admins` — list/create/grant/revoke/deactivate/reactivate.
- `/api/v1/admin/approvals` — список собственных заявок (creation unavailable);
  super-admin видит все заявки.
- `POST /api/v1/admin/approvals/{id}/approve` — только другой super-admin.
- `POST /api/v1/admin/approvals/{id}/reject` — только другой super-admin.
- `POST /api/v1/admin/approvals/{id}/cancel` — только инициатор и только для
  заявки в состоянии `pending`.

Approval states: `pending`, `approved`, `rejected`, `expired`, `cancelled`,
`executed`, `execution_failed`. Final states cannot be reused for execution.
- `/api/v1/admin/system-settings` — catalog/list/get/update non-sensitive
  settings; sensitive changes use a dedicated approval workflow.


## System settings
Settings API never returns or stores secrets.

- `GET /api/v1/admin/system-settings` and `GET /{key}` require direct
  `system_settings.read`;
- `PUT /api/v1/admin/system-settings/{key}` requires direct
  `system_settings.manage`, validates the full effective catalog and rejects
  archived or sensitive keys;
- `POST /api/v1/admin/system-settings/{key}/approval-requests` requires an
  ordinary admin with `system_settings.manage` in
  `requires_super_admin_approval` mode. It accepts only active sensitive keys,
  a catalog-validated value, immutable `requestId`, reason and timezone-aware
  future `expiresAt`;
- `POST /api/v1/admin/system-settings/approval-requests/{id}/execute` requires
  super-admin and accepts only an approved `system_setting.change` request.
  The executor revalidates and locks the full active catalog atomically;
- there is no generic approval execute endpoint. A domain validation or catalog
  conflict transitions the request to final `execution_failed`; retry requires
  a new immutable request and approval.
- New approval requests can only be created through domain-specific endpoints
  (e.g., System Settings workflow); generic approval creation is unavailable.

## Approval workflow
New approval requests can only be created through domain-specific endpoints
(e.g., System Settings workflow). Generic `POST /api/v1/admin/approvals` is
unavailable and returns HTTP 410 Gone with an instruction to use domain-specific
endpoints.

Existing approval requests (`pending`, `approved`, `rejected`, `expired`,
`cancelled`, `executed`, `execution_failed`) can be reviewed via
`approve`, `reject`, `cancel` endpoints with appropriate permission checks.

Secrets, hashes, raw tokens и validation answers не возвращаются API.
