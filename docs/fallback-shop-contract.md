# Fallback Shop Contract

## Purpose and scope

This document defines the fallback shop available after a qualifying first
attempt outcome. It is a server-enforced economic flow, not frontend logic.

The fallback feature uses a pre-published CMS shop product. Price, item
binding, limits, lifecycle, pool policy, eligibility policy, and feature flags
are CMS/System Settings configuration. Runtime code performs validation,
locking, idempotency, state transitions, and atomic domain execution.

V1 (Sprint 8.16) is implemented and working end-to-end: entitlements are
per `(player_id, mission_id, item_id)`, one offer per key-reward of the
mission, with an atomic purchase. The full product/global-pool model described
below remains a target contract; it does not authorize a schema change by
itself beyond what V1 already implements.

## Definitions

- **qualifying outcome**: a server-recorded consumptive outcome of the first
  attempt in a run, as allowed by the effective mission policy. The initial
  policy includes failure, timeout, or abandonment when those outcomes consume
  the attempt.
- **personal entitlement**: server-side eligibility for one player and mission
  fallback policy. It is not an item, a wallet credit, or evidence of purchase.
- **fallback product**: a separately published CMS shop product linked by the
  mission effective configuration. It defines item, price, lifecycle, limits,
  and applicable policy.
- **global offer pool**: available count for a fallback product. Each
  qualifying event can add one configured unit; each successful purchase
  removes one configured unit.
- **purchase**: one idempotent atomic ROOT debit, pool decrement, inventory
  credit, and entitlement consumption operation.

## Eligibility creation

Immediately after the first qualifying consumptive outcome of a run, backend
atomically records corresponding personal fallback eligibility. The same domain
operation increments the configured global offer pool exactly once.

Eligibility is limited to the player who owns the run. Under the current
product decision it is available indefinitely after qualification unless a
future validated CMS policy explicitly sets expiry. Its creation is
idempotent: replaying the same outcome, timeout job, submit request, or
transaction retry cannot create another entitlement or increment the pool.

The entitlement must be traceable to qualifying run, attempt, and outcome in
target schema and references. V1 expresses per-key cases via the unique
`(player_id, mission_id, item_id)` constraint (Sprint 8.16). No schema
workaround or overloaded mutable field is permitted without review.

## V1 semantics (implemented in 4.3a)

Until the full product/pool schema is reviewed, 4.3a implements a deliberately
narrow subset of the target contract:

- A **qualifying outcome** is the first failed answer submission
  (`attempt_count_before == 0`) for the owning player. It is eligible whether
  or not the mission has a paid entry policy; a failed answer on a free/legacy
  mission is equally eligible.
- **One entitlement per key-reward**: on the first qualifying outcome every
  key-reward item of the mission gets its own `PlayerFallbackEntitlement` row
  (a separate offer per key): `item_id` = the key's item,
  `offer_id = shop.fallback.default_offer_id`,
  `quota_limit = shop.fallback.default_quota_limit`, `consumed_count = 0` and
  `status = 'available'`.
- The **global offer pool is not touched**: V1 has no pool rows.
- Creation is **idempotent** via the unique `(player_id, mission_id, item_id)`
  constraint and the `attempt_count_before != 0` guard: later failed attempts
  cannot extend, duplicate, or add additional key entitlements.
- The empty-string `offer_id` default means no entitlement is recorded until an
  admin enables a real `shop.fallback.default_offer_id` (and
  `shop.fallback.enabled = true`) through System Settings.
- `shop.fallback.default_available_seconds` is catalog-only in V1: entitlement
  rows have no `expires_at`, so the value is reserved for 4.4+.

### 8.17.13-fix: XOR между заходами (2026-11-09)

Если ключ выдан наградой (успех в новом заходе после провала в прошлом),
невыкупленный депозит закрывается при выдаче награды
(`close_unspent_after_award`): `quota_limit = consumed_count`, `status =
"exhausted"`. Это гарантирует XOR между заходами (нельзя получить ключ
дважды — наградой и покупкой). Уже выкупленное и `disabled` не
затрагиваются.

### Configuration keys (4.3a)

| key | type | default | purpose |
| --- | --- | --- | --- |
| `shop.fallback.enabled` | boolean | `false` | master feature flag for V1 |
| `shop.fallback.default_offer_id` | string | `""` | product reference recorded into entitlement |
| `shop.fallback.default_quota_limit` | integer | `1` | entitlement purchase quota |
| `shop.fallback.default_available_seconds` | integer | `0` | reserved for 4.4+; not persisted in V1 |

Rows are seeded by migration `07131ffe9d13` (append-only data migration;
`downgrade` is intentionally not implemented).

## Product and pool policy

Fallback is a reference to a pre-published product; it is not dynamically
created from a client request or a hardcoded mission branch. The product must
be active/published and pass CMS validation before selection by effective
mission configuration.

The product identifies creditable item and ROOT price in integer atomic units.
Each qualifying first attempt adds one configured unit to its global offer
pool. Purchases decrement the pool by one. Remaining pool units stay
purchasable by eligible players under configured limits.

A player may possess an equivalent item before fallback purchase. Existing
inventory does not suppress availability unless an explicit CMS limit does so.
A purchased item stacks with the same player inventory projection when its item
configuration allows it.

The item may be configured for another mission, repeat entry into the same
mission, both, or neither. Purchasing it never automatically changes an
already active run.

## Purchase transition

A dedicated fallback purchase executor performs, in one transaction:

1. authenticate player and validate idempotency key;
2. lock and validate active/published fallback product and global pool;
3. lock player entitlement, wallet, and target inventory row;
4. validate entitlement status/quota, product policy, player limit, pool, and
   sufficient non-negative ROOT;
5. append immutable ROOT debit with purchase-specific reference;
6. decrement global pool;
7. append immutable inventory `credited` event and update `PlayerItem` balance;
8. increment entitlement consumption or transition it to exhausted where
   configured;
9. persist or return committed idempotent purchase result.

If any check fails, no debit, pool decrement, inventory credit, or entitlement
consumption occurs. Concurrent purchases cannot sell more units than available
pool or debit/credit the same request twice.

Fallback purchase ROOT changes use `WalletTransaction`; item grants use
`InventoryEvent`. Product, entitlement, pool, purchase references, wallet, and
inventory projections must remain mutually consistent.

## Refunds and compensation

There is no ordinary refund after a committed fallback purchase. Exceptional
compensation requires a separate explicitly authorized domain flow, immutable
compensating records, clear reference to the original purchase, and required
audit/approval controls. It never updates or deletes original wallet
transaction, inventory event, entitlement history, or pool history.

## Public boundary and API

The player may receive only currently permitted offer presentation, personal
eligibility state, safe remaining limits, and committed purchase result.
Responses never expose protected mission validation data, raw attempt snapshot,
other players' entitlements, global operational internals beyond permitted
availability, secrets, credentials, or audit metadata.

Future routes and idempotency requirements are recorded in
`docs/api-contracts.md`. Before implementation, product/pool schema and its
SQLite/PostgreSQL migration plan require separate reviewed design, verified
backup where applicable, and rollback plan.
