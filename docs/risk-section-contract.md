# Risk Section Contract

## Purpose and scope

This document defines the infrastructure for the "Risk" section: a gated game
area inside the Telegram Mini App where wager-style minigames will live.

**This contract covers the container only.** The minigames themselves are not
part of this work: the section ships with a placeholder and no playable game.
Their economics are defined separately in `docs/risk-bonus-minigame-contract.md`
and remain unimplemented.

Scope of this document:

- one-time gas-paid unlock, permanent per player;
- admin configuration of unlock cost and section visibility;
- the player-facing states of the section;
- the API surface and data model that hold the above.

## Definitions

- **risk section**: the screen reachable from the "More" sheet in the mobile
  navigation. It hosts wager minigames once they exist.
- **unlock grant**: a permanent, immutable record that a player has paid the
  gas cost once and may enter the risk section forever. One grant per player.
- **access mode**: admin-controlled visibility of the section for all players.
  Three values: `hidden`, `locked`, `open`.
- **gas**: the existing premium currency (`GasWallet`, `GasTransaction`), bought
  with Telegram Stars. Not ROOT. See `docs/economy-and-root-ledger.md` for why
  ROOT is never used for this charge.

## Access modes

`risk.access_mode` is CMS data, not code. Exactly one value is active.

| Mode | Player sees | Section reachable |
|---|---|---|
| `hidden` | nothing — the entry does not exist in "More" | no, for everyone, even granted players |
| `locked` | the entry is visible; inside: lock screen with price and pay/decline | only after a grant exists |
| `open` | the entry is visible; inside: the section itself | yes, no payment required |

Rules that hold in every mode:

- `hidden` overrides a grant. A player who paid earlier sees nothing while the
  admin keeps the section hidden, and sees the section again (still unlocked,
  without paying twice) when the admin switches back to `locked` or `open`.
- A grant is never revoked, expired, or refunded by changing the mode.
- `open` does not create grants. If the admin switches from `open` back to
  `locked`, players without a grant must pay; players with a grant enter free.

## Player-facing states

Resolved by the backend, never computed on the client:

| State | Condition | Screen content |
|---|---|---|
| `hidden` | mode is `hidden` | section not rendered at all |
| `locked` | mode is `locked` and no grant | "Игры заблокированы. Стоимость разблокировки N газа." + «Оплатить» / «Отказаться» |
| `unlocked` | grant exists, or mode is `open` | the section itself |

The lock screen must always show, before any payment is attempted:

- the exact gas cost **and** the player's current gas balance;
- an explicit notice that pressing «Оплатить» **will debit gas** permanently;
- the fact that the unlock is permanent and charged once;
- a «Отказаться» action that returns to the previous screen without any
  state change and without any gas movement.

Payment is never automatic, never triggered by opening the section, and never
performed without the player pressing «Оплатить» on a screen that states the
amount.

## Unlock operation

One atomic, idempotent operation:

```text
POST /api/v1/risk/unlock
  |
  +-- validate: mode allows payment (locked), grant does not exist
  |             (if a grant already exists -> return success, no debit)
  +-- validate: gas wallet exists and balance >= cost
  |             (otherwise 402, nothing changes)
  +-- lock gas wallet row
  +-- debit gas         -> immutable GasTransaction,
  |                        transaction_type='debit',
  |                        reference_type='risk_unlock',
  |                        reference_id=<grant id>
  +-- create grant      -> risk_access_grants row
  +-- commit            (one transaction; any failure rolls back both writes)
```

Guarantees:

- **At most one grant per player.** Enforced by a unique constraint on
  `player_id`, not by application logic alone.
- **At most one debit per grant.** The existing gas idempotency key
  `(gas_wallet_id, reference_type, reference_id)` makes a replayed request
  unable to debit twice.
- **No negative balance.** `gas_wallets.balance >= 0` is already enforced by a
  DB check constraint.
- **No partial state.** Gas debit and grant creation share one transaction.

A replayed request after success returns the unlocked state without moving gas.

## Data model

### `risk_access_grants`

| Column | Type | Notes |
|---|---|---|
| `id` | `String(64)` PK | `risk-grant-<hex>` |
| `player_id` | FK `game_players.id`, unique | one row per player, forever |
| `gas_cost_paid` | `Numeric(18,4)` | snapshot of the price at purchase |
| `granted_at` | timestamp | immutable |
| created/updated timestamps | from `TimestampMixin` | |

Constraints:

- unique `(player_id)` — the hard guarantee of "once, permanently";
- `gas_cost_paid >= 0`.

No physical delete. History is immutable.

### Ledger

The debit is recorded in the existing `gas_transactions` table. No new ledger is
introduced, and ROOT is never touched by this flow.

## Configuration (System Settings)

New keys in the approved catalog (`backend/app/system_settings_catalog.py`):

| Key | Type | Default | Category | Meaning |
|---|---|---|---|---|
| `risk.access_mode` | `string` | `hidden` | `risk` | `hidden` / `locked` / `open` |
| `risk.unlock_gas_cost` | `integer` | `100` | `risk` | gas debited once per player |

Both are validated on write against the catalog definition. `access_mode` only
accepts the three enumerated values; `unlock_gas_cost` must be a positive
integer.

A future "when does the section become available" policy (for example, only
after N completed missions) is deliberately **not** implemented. The
`risk.access_mode` switch already lets the admin open or hide the section at any
moment, which covers that decision until it is made. Adding an eligibility
policy later must extend this document first.

## API

### `GET /api/v1/risk/state`

Returns the resolved state for the authenticated player:

```json
{
  "state": "locked",
  "unlocked": false,
  "gasCost": 100,
  "gasBalance": "250.0000"
}
```

- `state`: `hidden` | `locked` | `unlocked`
- `gasBalance` is a string because gas is `Numeric(18,4)`.
- When `state` is `hidden`, the client must not render the entry at all, even
  though the API still answers.

### `POST /api/v1/risk/unlock`

No body. Returns the unlocked state on success:

```json
{ "state": "unlocked", "unlocked": true }
```

Errors:

| Status | When |
|---|---|
| `402` | insufficient gas; nothing is debited |
| `403` | mode is `hidden`; payment is not permitted |
| `409` | mode is `open` and no payment is needed (client should refresh state) |

Existing bootstrap `gasBalance` remains the single source for the balance; the
risk state endpoint repeats it only so the lock screen can render without an
extra request.

## Frontend

- The entry lives in the **"More" sheet**, not in the bottom tab bar: the bar
  already holds five items and a sixth would overcrowd it.
- A new `Screen` value `'risk'` and a new `RiskScreen`.
- The sheet item is rendered only when the state is not `hidden`.
- The screen renders three states as described above.
- Every payment attempt goes through an explicit confirmation that restates the
  cost and the resulting balance.
- No game is rendered. The unlocked view shows a placeholder.

## Explicitly out of scope

- Any playable minigame, its rules, its payout math, or its server-side
  verification.
- ROOT wagering.
- Eligibility conditions beyond the three-state mode switch.
- Localization for `en` and `zh` beyond adding the keys (texts are not final).

## Open decisions (do not block the container)

1. **When the section becomes available.** Currently the only control is the
   admin mode switch. A mission-count or level-based policy is a future
   extension.
2. **Default gas cost.** The catalog default is a placeholder to be set by the
   product owner.
3. **Final lock-screen copy.** The wording above is functional, not final.