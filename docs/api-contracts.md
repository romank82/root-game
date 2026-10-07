# API-контракты

## Public/game API
- `POST /api/v1/auth/telegram`
- `POST /api/v1/auth/logout`
- `GET /api/v1/engine/bootstrap`
- `POST /api/v1/engine/missions/{mission_id}/submit`
- `GET /api/v1/engine/fallback-offers`
- `POST /api/v1/engine/fallback-offers/{offer_id}/purchases`

`GET /api/v1/engine/bootstrap` returns only public player content. Schema and redaction policy for `Segment.content` and `Mission.content` are defined in `docs/segment-content-contract.md`; validation configuration, answers, and server-side award rules are excluded.

`GET /api/v1/engine/fallback-offers` (4.3b) возвращает только персональные
fallback-предложения вызывающего игрока после первого провала
(`docs/fallback-shop-contract.md`): mission id/slug/title, `entitlementId`
(уникальный адрес предложения в API), offer id, `priceRoot` (цена ключа в ROOT
atomic units, из system_settings), quota/remaining лимиты, presentation status
и предмет-ключ (id/slug/code/title/symbol/category/rarity).
`shop.fallback.enabled=false` → пустой список; item не published / KeyRules
удалён → `status: "disabled"` (derived, без записи в БД). Response никогда не
содержит pool/mode/expiry, policy JSON или server-only метаданные.

`POST /api/v1/engine/fallback-offers/{offer_id}/purchases` (4.4) покупает
fallback-ключ за ROOT в одной атомарной транзакции: debit ROOT
(`WalletTransaction`, `transaction_type="debit"`, amount всегда положительный)
→ выдача ключа (`PlayerItem` upsert + `InventoryEvent("credited")`) →
`consumed_count++`, при достижении quota — `status="exhausted"`. Путевой
параметр исторически назван `offer_id`, но адресует именно `entitlement.id`
(у одного игрока несколько entitlement'ов могут иметь одинаковый `offer_id`,
уникальный адрес — `entitlementId` из GET-ответа). Body отсутствует;
аутентификация — текущая player identity; rate limit 10/minute.
Pre-checks (каждый — HTTP 409 с русским detail): магазин отключён, ключ
недоступен, цена не настроена, предложение недоступно, квота исчерпана,
недостаточно ROOT. Чужой/несуществующий entitlement.id → 404.
Client `Idempotency-Key` не требуется: естественная идемпотентность через
`reference_id = f"{entitlement.id}:{n}"` на unique-индексах `WalletTransaction`
и `InventoryEvent`; повторный POST после успешной покупки возвращает прежний
committed-результат (`purchased: true`).
Response: `{"purchased": true, "entitlementId", "consumedCount",
"remainingQuota", "status", "priceRoot", "rootBalance", "item": {id, slug,
code, title, symbol, category, rarity}}`.

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
- `/api/v1/admin/reward-pools` — list/get/create/update; entries передаются и заменяются целиком в payload (`entries`); статус меняется через PATCH (draft/published); physical DELETE недоступен.
- `/api/v1/admin/geo-zones` — list/get/create/update; типы: radius/polygon/poi/event, cross-field-валидация геометрии в Python-контракте; статус меняется через PATCH (draft/published/archived); physical DELETE недоступен.
- `/api/v1/admin/ar-objects` — list/get/create/update; AR-объекты привязаны к геозонам через `geoZoneId` (FK ondelete=RESTRICT); cross-field-валидация окна доступности `startsAt`/`endsAt`; статус меняется через PATCH (draft/published/archived); physical DELETE недоступен.
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
- `/api/v1/admin/players` — list (search/status/authProvider filters, limit/offset).
- `/api/v1/admin/players/{id}` — player card (wallet, inventory, missions, restrictions, recent transactions, stats).
- `POST /api/v1/admin/players/{id}/wallet-adjustment` — ручное начисление/списание ROOT
  (`direction=credit|debit`, `amount>0`, `reason`, `request_id`). При direct-grant и сумме
  ниже `economy.manual_adjustment_approval_threshold` — прямое исполнение (200), иначе 201 (approval-заявка).
- `POST /api/v1/admin/players/wallet-adjustment-requests/{approval_id}/execute` — исполнение
  approved заявки, только super-admin, только `player.wallet_credit|player.wallet_debit`.
- При direct-grant: сумма ниже порога → 200 (прямое исполнение); сумма ≥ порога
  или approval-grant → 201 (approval-заявка). Super-admin всегда исполняет напрямую
  (по конвенции проекта он не создаёт заявки).
- `POST /api/v1/admin/players/{id}/inventory-item-adjustment` — ручная выдача/отзыв предмета
  (`direction=grant|revoke`, `item_id`, `quantity>0`, `reason`, `request_id`). При direct-grant и
  количестве ниже `gameplay.manual_item_adjustment_approval_threshold` — прямое исполнение (200),
  иначе 201 (approval-заявка). Ответ: ключ `inventoryEvent` (+ `playerItem`, `idempotent`).
- `POST /api/v1/admin/players/inventory-item-adjustment-requests/{approval_id}/execute` — исполнение
  approved заявки, только super-admin, только `player.inventory_grant|player.inventory_revoke`.
- `POST /api/v1/admin/players/{id}/missions/{mission_id}/mission-cancel` — снять/отменить миссию
  (`reason`, `request_id`, `expires_at?`, `invalidate_fallback_entitlement=false`). При
  `players.manage` direct-grant — прямое исполнение (200); при `requires_super_admin_approval`
  — 201 (approval-заявка `player.mission_cancel`). Устанавливает терминальный статус `cancelled`
  из `available`/`in_progress`; `completed`/`cancelled` — 409. Повтор с тем же `request_id` —
  200 `idempotent` (признак — запись в immutable admin_audit_log). Ресурсы при отмене не
  возвращаются (компенсация — 5.4/5.5). Fallback-entitlement отключается (available -> disabled)
  только при `invalidate_fallback_entitlement=true`; exhausted/disabled не трогаются.
- `POST /api/v1/admin/players/mission-cancel-requests/{approval_id}/execute` — исполнение approved
  заявки, только super-admin, только `player.mission_cancel`.
- Grant требует `Item.status == "published"` (иначе 409); revoke статус не проверяет, но требует
  существующий `PlayerItem` и достаточное количество (иначе 409). Ledger:
  `InventoryEvent(event_type=credited|consumed, reference_type=admin_item_grant|admin_item_revoke,
  reference_id=request_id)`; новая строка помечается `obtained_from_type="admin_manual"`,
  `obtained_from_id=request_id`. Player-ограничения (`sale_forbidden`, `transfer_forbidden`,
  `trade_forbidden`, `stack_limit`, `is_consumable`) админ-операции не блокируют.


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

<!-- stage-3-2-runtime-contract-reconciliation -->

## Target solo mission-run API (not implemented)

Every state-changing target route requires authenticated player identity and
a bounded client-generated idempotency key. The exact transport field and
response schemas must be finalized before implementation.

- `POST /api/v1/engine/missions/{mission_id}/runs` — direct atomic solo start.
- `GET /api/v1/engine/mission-runs/{run_id}` — owner-permitted run projection.
- `POST /api/v1/engine/mission-runs/{run_id}/attempts` — issue next attempt.
- `POST /api/v1/engine/mission-attempts/{attempt_id}/submit` — resolve attempt.

Responses expose only caller-permitted state. They never expose accepted
answers, correct sequences, protected challenge snapshots, raw location
proofs, QR material, reservation internals, other players data, audit
metadata, secrets, hashes, tokens, cookies, or Telegram initData.

Target behavior is defined in `docs/mission-run-contract.md`,
`docs/inventory-ledger-contract.md`, and `docs/fallback-shop-contract.md`.

## Solo runtime API v1

Этот раздел определяет transport contract первой версии одиночных runtime-миссий.
Детали CMS policy определены в `docs/solo-mission-runtime-policy-contract.md`.

### Аутентификация и доступ
Все маршруты требуют текущую аутентифицированную player identity через
существующую server-side Telegram session.
Игрок получает доступ только к собственным run и attempt.

### Idempotency-Key
Каждый state-changing route требует HTTP header:
`Idempotency-Key: <client-generated-key>`.
Ключ имеет длину от 16 до 128 ASCII символов и может содержать только
латинские буквы, цифры, дефис и underscore.
Повтор того же committed request возвращает прежний safe public result.
Использование того же ключа с другим request fingerprint возвращает HTTP 409
с безопасным code `idempotency_key_reused_with_different_request`.
Ошибка до commit не создаёт game effect и допускает retry с тем же key.

### Маршруты
- `POST /api/v1/engine/missions/{mission_id}/runs`
  - body: `{}`;
  - атомарно запускает paid solo run;
  - проверяет Mission и runtime policy publication, feature policy,
    prerequisites, repeatability, active-run limits, ROOT и items.
- `GET /api/v1/engine/mission-runs/{run_id}`
  - owner-only safe run projection; Idempotency-Key не требуется.
- `POST /api/v1/engine/mission-runs/{run_id}/attempts`
  - body: `{}`; выдаёт следующую server-side attempt.
- `POST /api/v1/engine/mission-attempts/{attempt_id}/submit`
  - cipher body: `{"selection":["A","C","F","B"]}`;
  - сервер проверяет ownership, state, deadline и protected snapshot.

### Public response boundary
Response может содержать ID, status, timestamps, разрешённое visible challenge
presentation, deadline, номер attempt, safe run state и фактически committed
награды ROOT/items.
Response никогда не содержит accepted answers, correct sequence, protected snapshot,
validation config, policy JSON, raw ledger/inventory metadata, QR/location data,
other players data, audit metadata, tokens, cookies, secrets или Telegram initData.
Fallback purchases (4.4) входят в API v1: `POST /api/v1/engine/fallback-offers/{offer_id}/purchases`
реализован в 4.4; `GET /api/v1/engine/fallback-offers` — отдельный маршрут (4.3b).
Legacy `POST /api/v1/engine/missions/{mission_id}/submit` остаётся отдельным
маршрутом до отдельной reviewed migration/deprecation задачи.
