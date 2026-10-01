# Public Segment and Mission Content Contract

## Purpose

This document defines CMS-managed public presentation data that backend may return to an authenticated player through `GET /api/v1/engine/bootstrap`.

Frontend displays only permitted public data. It never decides mission availability, success, progress, or rewards. Backend validates player actions against server-only data and performs ROOT, inventory, progress, and status changes atomically.

## Public bootstrap boundary

Bootstrap returns only published Segment and Mission content allowed to the current player. Segment returns active `linkedMissions` with published Mission records in `sortOrder` order.

Public Segment fields are `id`, `slug`, `title`, `description`, `status`, `sortOrder`, validated `content`, and `linkedMissions` (`id`, `slug`, `title`). Public Mission fields are identifiers, title/description, mission type, player progress fields, and validated presentation-only `content`.

## Segment.content schemaVersion 1

```json
{
  "schemaVersion": 1,
  "presentation": {"code": "SEGMENT_PUBLIC_CODE", "type": "ARCHIVE_SEGMENT"},
  "location": {
    "searchRadiusMeters": 250,
    "safeScanRadiusMeters": 15,
    "safeScanPoint": {"latitude": 54.0, "longitude": 82.0}
  },
  "arScene": {"scenePreset": "archive_cube_v1", "scanHoldDurationMs": 1800}
}
```

Coordinates above are illustrative, not a real game point. Version 1 requires integer `schemaVersion: 1`; non-empty public code/type and scene preset; positive bounded radii with `searchRadiusMeters >= safeScanRadiusMeters`; valid latitude (`-90..90`) and longitude (`-180..180`); and a positive bounded `scanHoldDurationMs`.

Exact `safeScanPoint` coordinates may be returned to an authenticated player for a published Segment when required for navigation and UX. Client-side distance checks are UX only: they never authorize a reward, progress change, or protected operation.

## Mission.content schemaVersion 1

Mission content is public UI/presentation data only and is schema-validated by `missionType`.

For `text_answer`, `ui` may contain `label`, `question`, `inputPlaceholder`, `successTitle`, `successText`, and optional `rewardPreview.text`.

For `code_repair`, `ui` may contain `label`, `instruction`, public selectable `blocks`, `maxBlocks`, `lineNumber`, `placeholder`, `wrongAnswerText`, and optional `rewardPreview.text`. Public blocks do not disclose their valid order.

For `team`, `ui` may contain `label`, `instruction`, `joinTitle`, `joinText`, `waitingText`, `readyText`, `activeText`, `successTitle`, `failureText`, and optional `rewardPreview.text`. These fields are presentation-only. Team size, matching policy, entry fee, item requirements, geo rules, QR mode, deadlines, fallback policy, challenge state, and settlement rules remain server-only.

`rewardPreview` may include exact ROOT amounts and public item names when game design requires it. It is informational only; it is not an entitlement, accounting record, or instruction to issue a reward.

## Server-only data and prohibited keys

Public bootstrap, `Segment.content`, and `Mission.content` must never include validation configuration, validator identifiers/details, accepted answers, correct sequences, answer hashes, solution keys, hidden puzzle state, client-controlled award amounts, wallet balance-after, inventory mutations, completion flags, entry-fee execution data, server-side limits, approval/audit/admin metadata, secrets, tokens, credentials, cookies, Telegram initData, or private keys.

For geo/team missions, public navigation coordinates are not a server-validated
LocationProof. Raw location evidence, proximity decisions, protected QR data,
attempt identifiers/challenge snapshots, deadlines, reservations, and
settlement state are server-only. Their target contract is
`docs/geo-team-mission-contract.md`.

The client sends only the player action required by the mission endpoint. Backend validates it against server-only configuration, locks and updates protected rows where required, records ROOT only through immutable `WalletTransaction`, updates inventory/progress atomically, and returns the actual result.

## Reward display and source of truth

A client may display `rewardPreview` before an attempt. After submission it must use `awarded` from `POST /api/v1/engine/missions/{mission_id}/submit` to confirm what was actually granted.

Source of truth: ROOT is immutable `WalletTransaction`; wallet balance is a backend-maintained cache; inventory, mission completion, and player status are backend transactional state. Changing browser requests, local state, rendered text, or DevTools values must not grant ROOT, items, mission completion, or status changes.
