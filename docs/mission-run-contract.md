# Mission Run and Attempt Contract

## Purpose and scope

This document defines the shared runtime contract for player mission runs and attempts. It applies to the first solo mission vertical and provides shared concepts used by future geo/team flows.

The current direct-submit endpoint does not implement this contract yet. `PlayerMission` remains a current-progress projection; `MissionRun` and `MissionAttempt` are historical runtime records. Runtime history is never physically deleted or rewritten because content is archived or later edited.

This contract is read together with:

- `docs/economy-and-root-ledger.md`;
- `docs/inventory-ledger-contract.md`;
- `docs/fallback-shop-contract.md`;
- `docs/geo-team-mission-contract.md` for geo/team-specific behavior;
- `docs/system-settings.md`;
- `docs/segment-content-contract.md`.

## Authority and configuration

Mission economics, required item types and quantities, maximum attempts, challenge parameters, reward policies, fallback product binding, repeatability, and feature enablement are CMS/System Settings data. Runtime code may contain only schema and bounds validation, state-machine mechanics, authorization, idempotency, locking, transactions, and domain executors.

Each `MissionRun` stores an immutable `effective_config_snapshot`. The snapshot represents the validated effective configuration at start. Subsequent CMS or System Settings changes never modify prior run, attempt, settlement, ledger, inventory-event, or entitlement history.

The frontend is not authoritative for availability, entry payment, timer, attempt outcome, reward eligibility, multiplier, inventory, ROOT, progress, or fallback eligibility.

## Roles of persistent entities

- `PlayerMission` is a current-progress projection for one `(player, mission`). It supports bootstrap and prerequisite evaluation; it is not the run ledger.
- `MissionRun` is one historical execution of a mission by a player.
- `MissionAttempt` is one ordered, server-issued challenge within a run.
- `MissionSettlement` records at most one terminal settlement for a run.
- `WalletTransaction` is the immutable ROOT ledger.
- `InventoryEvent` is the immutable inventory event ledger.
- `PlayerFallbackEntitlement` is server-enforced player eligibility; it is not itself a purchase, item credit, or wallet transaction.

## Solo run lifecycle

For the first paid solo vertical, creation and activation are one atomic operation. A solo run does not use a reservation phase.

```text
no run
  -> active
  -> succeeded | failed | timeout | abandoned
```

`active`, `succeeded`, `failed`, `timeout`, and `abandoned` use the existing `MissionRun.status` values. Terminal states cannot transition to another state. A terminal run has one terminal timestamp and at most one `MissionSettlement`.

The existing `reserved -> accepted -> active` path is reserved for future geo/team pre-start flows. It must not be imposed on a solo flow solely because the shared schema supports it. Geo/team reservation behavior is defined in `docs/geo-team-mission-contract.md`.

## Solo start transition

A dedicated `start_mission_run` domain executor performs the following in one transaction:

1. authenticate and validate the active player;
2. lock and validate the Mission and its published/effective policy;
2. validate prerequisites, active-run limits, repeatability, feature flags, and all CMS-owned entry requirements;
2. acquire the wallet and applicable inventory rows with the required locking semantics for the database dialect;
5. verify non-negative sufficient ROOT and item quantities;
6. create immutable ROOT entry-debit and inventory consumption records;
7. update cached wallet/item projections consistently with their ledgers;
8. create `MissionRun(status="active")` with its effective configuration snapshot and activation timestamp;
9. return a caller-permitted public run representation.

Failure of any step rolls back all steps. A start request with the same idempotency key returns its previously committed result and must not debit ROOT, consume an item, or create another run again.

There is no ordinary refund after a successful solo start. Any compensation is a separate explicitly authorized compensating transaction with immutable references; it never rewrites the original debit, event, run, or settlement.

## Repeatability and current progress

Whether another run may start after a prior success, failure, timeout, or abandonment is a validated mission-level CMS policy. There is no global hardcoded one-time or replay rule.

Start is denied when the configured repeatability policy, an active-run limit, a prerequisite, content lifecycle, feature flag, or entry requirement denies it. `PlayerMission` is updated only as the current projection required by the documented progression policy; it does not replace historical runs.

## Attempt lifecycle

```text
no attempt
  -> issued
  -> submitted
  -> succeeded | failed

issued
  -> timed_out```

`submitted` is a short processing state. A persisted terminal outcome is exactly one of `succeeded`, `failed`, or `timed_out`. A terminal attempt cannot be submitted, resolved, or rewarded again.

`sequence_number` starts at 1 and is unique within a run. The maximum number of attempts comes from the run snapshot, not a Python constant. Attempt issuance is denied when the run is not active, an unresolved attempt already exists, or no configured attempts remain.

## Begin attempt

A dedicated executor issues an attempt only for the run owner and only while the run is active. It creates:

- the next sequence number;
- a server-generated protected challenge snapshot;
- challenge type;
- server-authoritative issue and deadline timestamps.

The response contains only player-permitted visible challenge presentation and deadline data. It never contains accepted answers, correct sequences, hashes, solution keys, protected validation configuration, internal settlement data, or other players private data.

Repeated begin requests use a documented idempotency key. A retry returns the same issued attempt or its already committed outcome rather than creating an additional attempt.

## Submit and resolve attempt

A dedicated executor validates player ownership, active run state, attempt state, server deadline, challenge snapshot, and idempotency key. The backend, not browser time or a client-supplied outcome, determines success, failure, and expiry.

A technical request failure without a committed server-side outcome does not consume an attempt. If the server has committed an outcome but the response is lost, a request retry with the same idempotency key returns that outcome without performing settlement again.

An explicitly server-recorded `failed`, `timed_out`, or configured `abandoned` outcome consumes an attempt. A successful outcome also consumes its attempt and triggers one atomic success settlement. A server-side timeout mechanism must be idempotent and must not resolve a previously terminal attempt again.

## Run terminal outcomes and settlement

- Successful attempt: run becomes `succeeded`; one settlement is created; the reward policy is evaluated from the immutable run snapshot.
- Failed attempt with remaining attempts: run remains `active`; no terminal settlement is written.
- Failed/timed-out/abandoned final allowed attempt: run becomes the matching terminal state and receives one terminal settlement without success rewards, unless an explicit CMS policy defines a permitted terminal grant.
- No outcome may create two settlements for the same run.

All run, attempt, wallet, inventory, entitlement, and settlement effects of a single resolved action are atomic. Concurrent requests must be serialized by row locks and unique references where required.

## Cipher and protected validation data

For the first `cipher` mechanic, backend generates the correct combination when it issues an attempt and stores the protected state server-side. CMS controls bounded presentation and difficulty values such as number of drums, false choices, and deadline policy.

The frontend may render visible letters/options and submit its selected combination. It may not receive or decide the correct sequence, validator details, hidden challenge state, award policy, or final outcome. Client timers are UX only; the backend deadline is authoritative.

## Public API requirements

Every future state-changing run or attempt endpoint requires authenticated player identity and a request idempotency key. Responses contain only caller-permitted public state and the committed result. They never expose protected snapshots, raw validation answers, reservation internals, private location evidence, audit metadata, secrets, credentials, cookies, or Telegram initData.

Exact route names and request/response contracts are recorded in `docs/api-contracts.md` before implementation.
