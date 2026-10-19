# API-контракты

## Public/game API
- `POST /api/v1/auth/telegram`
- `POST /api/v1/auth/logout`
- `GET /api/v1/engine/bootstrap`
- `POST /api/v1/engine/missions/{mission_id}/submit`
- `GET /api/v1/engine/missions/{mission_id}/qr-payload` — подписанный QR-payload для миссии в `in_progress`
- `GET /api/v1/engine/fallback-offers`
- `POST /api/v1/engine/fallback-offers/{offer_id}/purchases`
- `GET /api/v1/engine/shop/items` — @deprecated (каталог shop.catalog; не используется основным UI)
- `POST /api/v1/engine/shop/items/{item_id}/purchases` — @deprecated (см. выше)
- `POST /api/v1/engine/teams` — создать команду (201)
- `GET /api/v1/engine/teams/me` — моя команда
- `GET /api/v1/engine/teams/{team_id}` — карточка команды
- `PATCH /api/v1/engine/teams/{team_id}` — обновить профиль (лидер)
- `POST /api/v1/engine/teams/{team_id}/join` — вступить
- `POST /api/v1/engine/teams/{team_id}/leave` — выйти (204)
- `POST /api/v1/engine/teams/{team_id}/members/{player_id}/kick` — исключить (204)
- `POST /api/v1/engine/teams/{team_id}/transfer-leadership` — передать лидерство
- `POST /api/v1/engine/teams/{team_id}/disband` — расформировать (204)
- `POST /api/v1/engine/teams/{team_id}/invitations` — пригласить игрока (201)
- `GET /api/v1/engine/teams/invitations/me` — мои приглашения
- `POST /api/v1/engine/teams/invitations/{invitation_id}/accept` — принять приглашение
- `POST /api/v1/engine/teams/invitations/{invitation_id}/reject` — отклонить приглашение (204)
- `DELETE /api/v1/engine/teams/{team_id}/invitations/{invitation_id}` — отозвать приглашение (204)
- `POST /api/v1/engine/teams/{team_id}/join-requests` — подать заявку (201)
- `GET /api/v1/engine/teams/join-requests/me` — мои заявки
- `DELETE /api/v1/engine/teams/join-requests/{request_id}` — отозвать заявку (204)
- `GET /api/v1/engine/teams/{team_id}/join-requests` — заявки команды (лидер)
- `POST /api/v1/engine/teams/{team_id}/join-requests/{request_id}/approve` — одобрить заявку
- `POST /api/v1/engine/teams/{team_id}/join-requests/{request_id}/reject` — отклонить заявку (204)

`GET /api/v1/engine/bootstrap` returns only public player content. Schema and redaction policy for `Segment.content` and `Mission.content` are defined in `docs/segment-content-contract.md`; validation configuration, answers, and server-side award rules are excluded.

`GET /api/v1/engine/missions/{mission_id}/qr-payload` (8.6.c) выдаёт
вызывающему игроку подписанный QR-payload для собственной миссии в статусе
`in_progress`. Ответ: `missionId`, `payload` (base64url канонического JSON:
`v`, `playerId`, `missionId`, `nonce`, `iat`, `exp`), `hmac` (HMAC-SHA256
base64url от payload через domain-separated ключ `GAME_SESSION_SECRET`),
`expiresAt` (ISO-8601 UTC) и `ttlSeconds` (300 с). Маршрут read-only и
идемпотентен по эффекту: он не создаёт `PlayerMission`, не меняет статусы и
не пишет ledger/audit; повторный вызов выдаёт свежий payload с новым nonce
(предыдущий остаётся валидным до своего `exp`).
Ошибки: 404 — миссии нет или она не `published`; 403 — миссия `locked`;
409 — `available` (не взята), `completed`, `cancelled`; 503 — сервер не
настроен (`GAME_SESSION_SECRET` пуст). Секреты, `validation_config`,
координаты spawn и другие server-only данные в ответ не входят.
Ограничение «responses never expose QR material» из
`docs/mission-run-contract.md` относится к run/attempt-маршрутам target solo
API, где QR — protected challenge snapshot; здесь QR является разрешённой
видимой презентацией задачи для её владельца (`playerId` входит в подпись,
поэтому скриншот чужого QR не пройдёт проверку в 8.8).
Проверка подписи, принадлежности, свежести и запуск мини-игры —
отдельный маршрут 8.8.

`GET /api/v1/engine/fallback-offers` (4.3b) возвращает только персональные
fallback-предложения вызывающего игрока после первого провала
(`docs/fallback-shop-contract.md`). Каждый ключ-награда миссии — отдельный
оффер (entitlement per (player, mission, item)); оффер содержит: mission
id/slug/title, `entitlementId` (уникальный адрес предложения в API), offer id,
`priceRoot` (цена ключа в ROOT atomic units, из system_settings), quota/remaining
лимиты, presentation status и предмет-ключ
(id/slug/code/title/symbol/category/rarity).
`shop.fallback.enabled=false` → пустой список; item не published / KeyRules
удалён → `status: "disabled"` (derived, без записи в БД). Response никогда не
содержит pool/mode/expiry, policy JSON или server-only метаданные (в т.ч.
`run_entry_count` — номер захода, server-only, в ответ не экспонируется).

Примечание (Sprint 8.17, шаг 8): для многоразовой миссии (repeatability
policy) каждый новый заход переармирует fallback-entitlement: при провале
в новом заходе `status` → `available`, `consumed_count` → `0`,
`run_entry_count` → номер текущего захода. Оффер снова доступен к покупке;
`reference_id` покупки учитывает `run_entry_count` (ниже).

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
`reference_id = f"{entitlement.id}:{run_entry_count}:{n}"` (Sprint 8.17,
шаг 8: run_entry_count — номер захода, к которому привязан entitlement)
на unique-индексах `WalletTransaction` и `InventoryEvent`; повторный POST
после успешной покупки возвращает прежний committed-результат
(`purchased: true`).
Response: `{"purchased": true, "entitlementId", "consumedCount",
"remainingQuota", "status", "priceRoot", "rootBalance", "item": {id, slug,
code, title, symbol, category, rarity}}`.

`GET /api/v1/engine/shop/items` и
`POST /api/v1/engine/shop/items/{item_id}/purchases` — @deprecated: каталог
`shop.catalog` (Sprint 8.16) реализован как альтернатива и не используется
основным UI; основной flow продажи ключей — fallback-offers (4.3b/4.4) выше.

## Teams API (этап 6.4)

Постоянные команды — сущность `Team` (НЕ `TeamSession` из этапа 3/7).
Player-facing endpoints; admin-модерация команд — этап 6.7. Все мутации —
`@limiter.limit("10/minute")` + player identity; тело и ответы — публичные
данные (без приглашений/заявок — шаг 6.5, без чата — шаг 6.6).

- `POST /api/v1/engine/teams` (201) — создать команду. Body:
  `{"name" (1..128), "description"?, "emblemUrl"?, "joinPolicy"?
  (open|by_request|invite_only, default "by_request"), "maxMembers"? >=1}`.
  Создаёт `Team(status="active")` + `TeamMember(role="leader")` + history
  `joined`. Если игрок уже в активной команде → 409.
- `GET /api/v1/engine/teams/me` — активная команда игрока либо 404
  «Вы не состоите в команде».
- `GET /api/v1/engine/teams/{team_id}` — карточка (только `status="active"`;
  расформированные → 404). Смотрит любой игрок.
- `PATCH /api/v1/engine/teams/{team_id}` (200) — только лидер; изменяет
  только переданные поля. Ответ — сериализованная команда.
- `POST /api/v1/engine/teams/{team_id}/join` (200) — вступить. Guard'ы (409):
  уже в активной команде; `joinPolicy != "open"` (заявки/приглашения — 6.5);
  `maxMembers` достигнут. Повторное вступление после выхода реактивирует
  прежнюю запись `TeamMember` (а не создаёт дубль).
- `POST /api/v1/engine/teams/{team_id}/leave` (204) — выйти. Guard 5.3 (409):
  игрок в активной командной миссии (`team_sessions.status` in
  collecting/ready_to_start/active). Лидер не может выйти (409) — только
  передать лидерство или расформировать.
- `POST /api/v1/engine/teams/{team_id}/members/{player_id}/kick` (204) —
  исключить (только лидер; не себя, не не-участника). History `kicked`
  с `actor_player_id=лидер`.
- `POST /api/v1/engine/teams/{team_id}/transfer-leadership` (200) — передать
  лидерство активному участнику. Атомарно: `team.leader_id`, roles старого
  и нового членства, history `leadership_transferred` (`newLeaderId`).
  Ответ — сериализованная команда.
- `POST /api/v1/engine/teams/{team_id}/disband` (204) — расформировать
  (только лидер). Guard 5.3 для всех участников (409 при активной миссии
  хотя бы у одного). `Team.status="disbanded"`, все active-члены →
  `left`, history `disbanded` для каждого.

Общий ответ карточки команды (create/get/update/join):
`{"id", "name", "description", "emblemUrl", "status", "joinPolicy",
"maxMembers", "memberCount", "leader": {"id", "displayName"},
"members": [{"id", "role", "joinedAt"}]}` — только active-состав, без
приватных данных участников. Idempotency-Key не требуется: уникальные
индексы `uq_team_members_team_player` / `uq_team_members_active_player` +
статус-машина дают естественную идемпотентность вступления.
Физического удаления нет: lifecycle active → disbanded, история состава
(`team_membership_history`) immutable.

## Teams API (этап 6.5)

Приглашения и заявки на вступление. Player-facing, все — `@limiter.limit("10/minute")`
+ player identity. Статус-машины соответствуют `CheckConstraint` моделей (6.2);
«одна pending на пару» страхуется partial-unique индексами
`uq_team_invitations_pending` / `uq_team_join_requests_pending`. Ленивый expire:
просроченное приглашение (`expires_at < now`) помечается `expired` при первом
обращении к accept/reject/cancel/list и не показывается игроку.

Способы вступления по `joinPolicy`:
- `open` → `POST /teams/{id}/join` (6.4);
- `by_request` → `POST /teams/{id}/join-requests` (лидер решает approve/reject);
- `invite_only` → только по приглашению лидера (`POST /teams/{id}/invitations`).

Приглашения (инициирует лидер):

- `POST /api/v1/engine/teams/{team_id}/invitations` (201) — пригласить игрока.
  Body: `{"invitedPlayerId"(1..64), "message"? (<=2000), "ttlHours"? (>=1)}`.
  TTL по умолчанию — system setting `invite.ttl_hours` (дефолт 72 часа).
  Guard'ы (409): не лидер — 403; приглашение самого себя; цель уже в активной
  команде; уже есть pending-приглашение этой паре; команда заполнена
  (`maxMembers` достигнут). Ответ — сериализованное приглашение (см. ниже).
- `GET /api/v1/engine/teams/invitations/me` (200) — список pending-приглашений
  игрока (просроченные исключаются после ленивого expire), новые первыми.
- `POST /api/v1/engine/teams/invitations/{invitation_id}/accept` (200) — принять:
  реактивация/INSERT `TeamMember` (как в 6.4, без дублей), history `joined`
  (`metadata.via="invitation"`), статус → `accepted`, `respondedAt`.
  Guard'ы (409): игрок уже в активной команде; команда заполнена;
  приглашение уже обработано/просрочено; чужое/несуществующее — 404.
- `POST /api/v1/engine/teams/invitations/{invitation_id}/reject` (204) — статус →
  `rejected`, `respondedAt`.
- `DELETE /api/v1/engine/teams/{team_id}/invitations/{invitation_id}` (204) —
  отозвать приглашение (только лидер этой команды): статус → `cancelled`.

Заявки (инициирует игрок):

- `POST /api/v1/engine/teams/{team_id}/join-requests` (201) — подать заявку.
  Body: `{"message"? (<=2000)}`. Guard'ы (409): игрок уже в активной команде;
  `joinPolicy == "open"` («вступайте напрямую через POST /teams/{id}/join»);
  `joinPolicy == "invite_only"` («только по приглашению»);
  уже есть pending-заявка этой паре. Ответ — сериализованная заявка.
- `GET /api/v1/engine/teams/join-requests/me` (200) — список pending-заявок игрока.
- `DELETE /api/v1/engine/teams/join-requests/{request_id}` (204) — отозвать свою
  заявку (только автор): статус → `cancelled`.
- `GET /api/v1/engine/teams/{team_id}/join-requests` (200) — заявки команды
  (только лидер; не-лидер-участник — 403, не-участник — 404). Query `?status=`
  (default `pending`, можно `accepted`/`rejected`/`cancelled`).
- `POST /api/v1/engine/teams/{team_id}/join-requests/{request_id}/approve`
  (200) — одобрить (только лидер): реактивация/INSERT `TeamMember`, history
  `joined` (`metadata.via="join_request"`), статус → `accepted`,
  `respondedByPlayerId`=лидер. Guard'ы (409): заявитель уже в активной команде;
  команда заполнена; заявка уже обработана.
- `POST /api/v1/engine/teams/{team_id}/join-requests/{request_id}/reject`
  (204) — отклонить (только лидер): статус → `rejected`,
  `respondedByPlayerId`, `respondedAt`.

Ответ приглашения: `{"id", "teamId", "invitedPlayerId", "invitedByPlayerId",
"status", "message", "expiresAt", "respondedAt"}`.
Ответ заявки: `{"id", "teamId", "playerId", "status", "message",
"respondedByPlayerId", "respondedAt"}`.
Ответ accept/approve — карточка команды (та же схема, что в 6.4).
2020+ статусов нет: никакого физического удаления, неизменяемые записи
(`TeamMembershipHistory`, `respondedAt`/статусы — только переход вперёд).

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
- `POST /api/v1/admin/players/{id}/missions/{mission_id}/mission-force-complete` — принудительно
  завершить миссию (`reason`, `request_id`, `expires_at?`, `award_rewards=true`). Прямое исполнение
  при direct-grant (super-admin или суммарные ROOT-награды < `economy.mission_force_complete_approval_threshold`),
  иначе 201 (approval-заявка `player.mission_force_complete`). Статус `completed` из
  `available`/`in_progress`/`locked`; `completed`/`cancelled` — 409. Повтор с тем же `request_id` — 200
  `idempotent` (replay из immutable admin_audit_log). Entry-ресурсы не возвращаются.
- `POST /api/v1/admin/players/mission-force-complete-requests/{approval_id}/execute` — исполнение
  approved заявки, только super-admin, только `player.mission_force_complete`.
- `POST /api/v1/admin/players/{id}/missions/{mission_id}/attempts-adjustment` — абсолютная ручная
  корректировка `attempt_count` (`new_attempt_count` в `[0, 1000]`, НЕ дельта). Прямое исполнение при
  direct-grant (super-admin в direct-режиме исполняет сразу, порога-магнитуды нет); approval-grant —
  201 (заявка `player.mission_attempts_adjust`). Статусы `completed`/`cancelled` — 409
  (`mission_already_terminated`); повтор с тем же `request_id` — 200 `idempotent` (replay из immutable
  admin_audit_log). `new == old` — 200 `changed: false`, аудит пишется. `status`/`started_at`/`progress`
  не трогаются. Fallback-семантика: установка `new_attempt_count=0` без активного entitlement — следующий
  неверный submit может создать новое fallback-предложение (guard `attempt_count_before == 0`);
  при существующем entitlement эффекта нет (unique `(player_id, mission_id)`).
- `POST /api/v1/admin/players/attempts-adjustment-requests/{approval_id}/execute` — исполнение approved
  заявки, только super-admin, только `player.mission_attempts_adjust`.
- `POST /api/v1/admin/players/{id}/restrictions` — создание ограничения
  (`restriction_type` из каталога: chat/transfer/team/mission/payment/withdrawal_restricted,
  suspended, blocked; `reason`, `request_id`, `starts_at?`, `expires_at?`, `evidence?`). Permission —
  от типа: `blocked`/`suspended` → `players.block`, остальные → `players.restrict`. При direct-grant —
  200 (прямое исполнение, `GamePlayer.status` синхронизируется всегда); при
  `requires_super_admin_approval` — 201 (заявка `player.restriction_create`; `expiresAt` становится
  и дедлайном одобрения). Активное ограничение того же типа — 409; повтор с тем же `request_id` —
  200 `idempotent` (replay из immutable admin_audit_log).
- `POST /api/v1/admin/players/restriction-requests/{approval_id}/execute` — исполнение approved
  заявки, только super-admin, только `player.restriction_create`.
- `POST /api/v1/admin/players/{id}/restrictions/{restriction_id}/revoke` — снятие ограничения
  (active → revoked; `reason`, `request_id`, `expires_at?` — дедлайн одобрения). Снятие уже
  снятого/истёкшего: тот же `request_id` — 200 `idempotent`, иной — 409. Статус игрока
  пересчитывается всегда (возврат в `active`/понижение `blocked` → `suspended`).
- `POST /api/v1/admin/players/restriction-revoke-requests/{approval_id}/execute` — исполнение approved
  заявки, только super-admin, только `player.restriction_revoke`.
- Истёкшие по `expires_at` ограничения лениво переводятся в `expired` при любом обращении
  (recompute в admin-операциях и auth-гейтах), без фоновых джобов.
- Grant требует `Item.status == "published"` (иначе 409); revoke статус не проверяет, но требует
  существующий `PlayerItem` и достаточное количество (иначе 409). Ledger:
  `InventoryEvent(event_type=credited|consumed, reference_type=admin_item_grant|admin_item_revoke,
  reference_id=request_id)`; новая строка помечается `obtained_from_type="admin_manual"`,
  `obtained_from_id=request_id`. Player-ограничения (`sale_forbidden`, `transfer_forbidden`,
  `trade_forbidden`, `stack_limit`, `is_consumable`) админ-операции не блокируют.

---

## Admin Key Rules API (раздел «Ключи»)

Управление каталогом ключей и их правилами. Каждый ключ = Item
(category=KEY) + KeyRules (правила использования).

### Endpoints
- `GET /api/v1/admin/key-rules` — список правил ключей
  (включает метаданные Item: itemTitle, itemCode, itemSymbol, itemStatus).
- `GET /api/v1/admin/key-rules/{key_rule_id}` — карточка правила.
- `POST /api/v1/admin/key-rules` — создать правило для существующего
  Item(category=KEY).
- `PATCH /api/v1/admin/key-rules/{key_rule_id}` — обновить правила
  (item_id не меняется).
- `GET /api/v1/admin/key-rules/items?status=published|draft|archived|all`
  — список ключей (Item category=KEY) для dropdown в редакторе миссии.
- `POST /api/v1/admin/key-rules/items` — создать новый ключ одним
  запросом: создаёт Item(category=KEY, status=published) + KeyRules.

### Permissions
- `key_rules.read` — все GET.
- `key_rules.manage` — POST/PATCH.

### Payload (create key item)
```json
{
  "title": "КЛЮЧ B-02",
  "code": "KEY_B02",
  "symbol": "🔑",
  "is_consumable": true,
  "stack_limit": 1,
  "transfer_forbidden": true,
  "sale_forbidden": true,
  "trade_forbidden": true
}
```

---

## Admin Teams API (этап 6.7.a)

Модерация команд: просмотр, состав, история, принудительное
расформирование и исключение. Все эндпоинты под префиксом
`/api/v1/admin/teams`. Чат-модерация (6.7.b) — не реализована.

### Permissions
- `teams.read` — все GET-эндпоинты.
- `teams.manage` — мутации (force-disband, force-kick).
  execution_mode выбирается супер-админом: `direct` или
  `requires_super_admin_approval`.

### Read
- `GET /api/v1/admin/teams` — список.
  Query: `status=active|disbanded|all` (default `active`),
  `join_policy`, `leader_id`, `q` (поиск по name),
  `limit` (default 50, max 200), `offset`.
  Ошибка 422 при невалидном `status`.
- `GET /api/v1/admin/teams/{team_id}` — карточка (disbanded тоже).
- `GET /api/v1/admin/teams/{team_id}/members` — состав.
  Query: `status=active|left|all` (default `active`).
- `GET /api/v1/admin/teams/{team_id}/history` — immutable-история состава.
  Query: `limit`, `offset`.
- `GET /api/v1/admin/teams/{team_id}/invitations` — приглашения.
  Query: `status` (default `pending`).
- `GET /api/v1/admin/teams/{team_id}/join-requests` — заявки.
  Query: `status` (default `pending`).

### Mutations (permission `teams.manage`)
- `POST /api/v1/admin/teams/{team_id}/force-disband`
  Body: `{reason}`. Прямое исполнение: 200 + `{teamId, disbanded, team}`.
  Approval-режим: 202 + `{approvalRequestId, approval, idempotent}`.
  Guard 5.3: 409, если любой участник в активной командной миссии.
- `POST /api/v1/admin/teams/{team_id}/members/{player_id}/force-kick`
  Body: `{reason}`. Прямое исполнение: 200 + `{teamId, playerId, kicked}`.
  Approval-режим: 202 + `{approvalRequestId, approval, idempotent}`.
  Guard: 409 для лидера; guard 5.3 для участника в активной миссии.

**Validation-правило.** И в direct, и в approval-режиме цель
проверяется ДО создания заявки: 404 на несуществующую команду,
409 на не-disbanded команду, 404 на отсутствующее членство.

### Dedicated executors (только супер-админ)
- `POST /api/v1/admin/teams/force-disband-requests/{approval_id}/execute`
- `POST /api/v1/admin/teams/force-kick-requests/{approval_id}/execute`

Только `approved` заявки своего action_type (иначе 409 / 422).
При ошибке исполнения заявка переходит в `execution_failed` (409).

**Idempotent replay.** Если заявка уже `executed` — ответ
`{"approval": ..., "idempotent": true}` БЕЗ top-level полей
результата. Это осознанный паттерн проекта (согласован с
`admin_player_mission` 5.x).



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
