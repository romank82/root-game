# Inventory Ledger Contract

## Purpose and scope

This document defines inventory integrity for mission entry, rewards, fallback
purchases, and future reservation-based geo/team flows.

`PlayerItem.quantity` is a current balance projection. `InventoryEvent` is the
immutable inventory history for critical grants, reservations, releases, and
consumption. Historical events and associated gameplay records are never
physically deleted or rewritten.

## Source of truth and projections

For each player item:

- `PlayerItem` identifies the player's current item balance projection;
- `PlayerItem.quantity` must never become negative;
- `InventoryEvent.quantity_delta` records immutable balance-affecting history;
- `InventoryReservation` records a future geo/team pre-start hold;
- item lifecycle and permitted mission uses are CMS-owned.

`PlayerItem.quantity` may be optimized as a cached projection, but its changes
must be explainable by immutable inventory history. A critical mutation must
not directly change quantity without the matching event in the same
transaction.

The existing database migration protects `inventory_events` from `UPDATE` and
`DELETE` through dialect-aware SQLite/PostgreSQL triggers. Application code
must also treat the table as append-only.

## Event model

The existing allowed event types are:

- `credited`: items were granted, for example by a mission settlement or a
  fallback purchase;
- `consumed`: items were permanently spent, for example by a paid solo run
  start;
- `reserved`: items were locked for a future geo/team start;
- `released`: a prior reservation was released before start.

Every event includes a player-item reference, signed non-zero quantity delta,
reference type, reference id, optional mission-run reference, safe metadata,
and immutable timestamp.

The event/reference uniqueness constraint is an idempotency guard. A retried
operation must return its existing committed effect rather than add another
event. Reference values identify the exact domain operation, not only a
mission id, so separate runs, attempts, settlements, and purchases cannot
collide.

## Solo mission entry

For a solo paid mission, item requirements are validated and consumed during
the same atomic transaction that starts the run:

1. lock applicable `PlayerItem` rows;
2. validate permitted item type(s), required quantities, item lifecycle, and
   non-negative sufficient quantity;
3. append one or more `consumed` events with run-specific references;
4. decrement matching `PlayerItem.quantity` projections;
5. create the active `MissionRun`.

A failed transaction creates neither a run nor partial item consumption.
Repeated start requests with the same idempotency key do not consume additional
items. Concurrent starts and purchases must not drive quantity below zero.

The player chooses whether and when to obtain missing keys. Start is denied
until all configured entry requirements are present; the start executor does
not silently purchase or substitute items.

## Rewards and fallback purchase credits

A successful settlement may issue items only when the immutable run snapshot
and reward policy permit it for that sequence number and outcome. The executor
appends `credited` events and updates projections atomically with settlement
and any ROOT ledger credit.

A fallback purchase appends a `credited` event with a purchase-specific
reference and updates the same item projection atomically with:

- fallback eligibility validation;
- global pool decrement;
- immutable ROOT debit;
- purchase idempotency recording.

A duplicate settlement or purchase must neither credit a second item nor
increment quantity again.

## Reservations for future geo/team flows

Reservations are not used by the first direct-start solo vertical. For the
future geo/team path:

- a `reserved` event and `InventoryReservation(status="reserved")` represent a
  pre-start hold;
- activation consumes the reserved item once;
- cancellation before start releases it once;
- status changes and event references are idempotent;
- a reservation may never permit a negative unreserved or total balance.

Detailed team transition rules remain in `docs/geo-team-mission-contract.md`.

## Locking, validation and safety

Critical inventory operations use one dedicated domain executor per operation,
not a generic action endpoint. The executor revalidates requirements while
holding relevant rows, writes events and projections transactionally, and
returns a safe idempotent result.

Inventory event metadata must not contain secrets, validation answers,
protected challenge state, Telegram initData, credentials, or unnecessary
private player data. Administrative configuration changes use permission-based
access, domain validation, approval where required, and immutable admin audit.

## Content lifecycle and key use

Items are CMS-managed content. Their compatibility with a mission, repeat
entry, another mission, or multiple purposes is explicit validated
configuration; it is not inferred from a title, slug, or fallback purchase.

Archiving content does not delete historical `PlayerItem`, `InventoryEvent`,
reservation, run, or settlement records. A new future use of archived content
is denied by the relevant executor, while historical references remain intact.
