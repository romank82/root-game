# Risk Bonus Minigame Contract

## Purpose and scope

This document defines the optional "risk bonus" flow: after a mission reward is
settled, the player may wager that reward in a skill minigame ladder to increase
it. It is a server-enforced economic flow. It is not a second reward channel and
not a frontend game with a client-side outcome.

Status: **design proposal only**. Nothing in this document is implemented. No
schema, API, or admin surface exists yet. Per `AGENTS.md`, implementation starts
only after the open decisions in the last section are closed in writing.

Related contracts:

- `docs/economy-and-root-ledger.md` — immutable ledger, ROOT rules;
- `docs/mission-run-contract.md` — run/attempt lifecycle, settlement;
- `docs/minigame-cipher.md` — existing minigame handler registry;
- `docs/fallback-shop-contract.md` — precedent for an optional post-outcome
  economic offer;
- `docs/admin-permissions.md`, `docs/system-settings.md`.

## Definitions

- **base reward**: the ROOT amount a completed mission run would grant under
  existing rules, including attempt multipliers. Items and story nodes are
  never part of a risk offer.
- **risk offer**: an optional, server-issued proposal to wager some or all of
  the base reward on a ladder of skill levels. Created at most once per settled
  run.
- **ladder**: an ordered list of levels with per-level difficulty parameters and
  a per-level payout ratio. Configured in CMS, not in code.
- **cash out**: player-initiated stop after clearing level *k*. Payout is the
  base reward plus the configured ladder bonus for *k*.
- **bust**: the player fails a level, or the offer expires, or the player
  abandons the ladder. What is lost is defined by the risk mode below.

## Why the "lose the whole reward" model is rejected

The originally proposed model — each cleared level adds +10% of the stake, one
failed level loses the entire reward — has negative expected value for the
player at every realistic skill level:

| Chance to clear one level | Best player strategy | Expected result on a 10 ROOT reward |
|---|---|---|
| 70% | do not play | −9.44 ROOT if forced to level 10 |
| 80% | do not play | −7.85 ROOT |
| 85% | do not play | −6.06 ROOT |
| 90% | do not play | ≈ 0 |
| 95% | play to level 10 | +1.97 ROOT |

Break-even requires **≥ 90.9% clear chance on every single level**. A 10-level
difficulty ladder cannot provide that on its upper levels.

The general rule: linear bonus growth (+10% per level) is slower than the
compounding survival probability `p^k`. A ladder only has positive player
expectancy when the payout ratio grows **geometrically at least as fast as
`1/p` per level**:

| Chance to clear one level | Break-even payout ratio per level |
|---|---|
| 70% | ×1.43 |
| 75% | ×1.33 |
| 80% | ×1.25 |
| 85% | ×1.18 |
| 90% | ×1.11 |

Consequences for the contract:

1. Ladder bonus per level is a **multiplier**, not an additive percentage, and it
   is CMS data validated against the configured per-level clear chance.
2. A fixed "+10% per level" ladder is not publishable unless the configured
   clear chances support it.
3. Because ROOT is withdrawable to TON, a ladder with negative player
   expectancy is a wagering product with real-money payouts. That is a product
   and legal decision, not an engineering default.

## Risk modes

Exactly one mode is active per offer. The mode is CMS configuration, validated
as a bound set, and frozen into the offer snapshot at issuance.

### Mode A — bonus only (default, recommended)

Clearing level *k* and cashing out grants `base * ratio_k` on top of the base
reward. A bust forfeits the accumulated bonus only; the base reward is credited
unchanged. Player expectancy is never negative, the product is not wagering,
and no player can end worse off than declining the offer.

### Mode B — partial stake (opt-in, requires written product approval)

A bust forfeits a configured fraction of the base reward (for example one half).
The other fraction is credited. This mode must be gated behind an explicit
feature flag and a named product approval record.

### Mode C — full stake (selected by product decision, 2026-11-26)

The product owner has decided (in writing, this chat) that the risk must be
real: a bust forfeits the **entire base reward**, not only the bonus. Mode C is
the selected default.

Consequences that the schema and runtime MUST enforce:

- The full base reward is **held, not credited**, from the moment the player
  accepts the offer until the ladder resolves. This follows the existing
  `withdrawal_hold` pattern: one `debit` with
  `transaction_type='risk_hold'` at accept; on cash out the hold converts to
  `base + bonus` credit; on bust the hold is **finalized as a real debit**
  (no refund transaction); on expiry the hold is released back in full.
- Because a player can end worse off than declining the offer, the accept
  screen must show the exact amount at risk before the first level starts.
- Payout ratios remain bound by the geometric rule above, so the ladder is
  still CMS-validated. Mode C does not remove the bound; it only changes what
  is lost on a bust.
- Mode C is a wagering product on a withdrawable currency. Its publication
  requires super-admin approval per the payout precedent.

## Reward flow

The existing flow credits ROOT inside the mission submit transaction
(`_award_mission_rewards` writes a `mission_reward` credit). The risk flow must
not break that invariant, and must not credit twice.

```text
mission run settles
        |
        +-- base reward computed under existing rules
        |
        +-- if risk feature enabled for mission and player eligible:
        |       create RiskOffer(status=offered) snapshotting ladder + mode
        |       NO ledger entry yet — nothing granted, nothing held
        |
        +-- player refuses or offer expires
        |       -> credit base reward via the existing path, unchanged
        |
        +-- player accepts -> RiskLadderRun(active) bound to the offer
        |       Mode A: credit base via existing path at accept (it can no
        |               longer be lost); bonus is a separate credit on cash out
        |       Mode B/C: debit base into a hold (risk_hold) at accept;
        |               cash out -> credit base * payout_k;
        |               bust     -> hold finalized as a real debit (C) or the
        |                           forfeited fraction returned (B);
        |               expiry   -> hold released in full (decline semantics)
        |
        +-- each level: server-issued challenge, server-verified outcome
```

Key points:

- **Decline/expire must be economically identical to the pre-feature flow**:
  the player receives exactly the base reward they would have received without
  the risk feature. This invariant is what keeps the feature optional.
- The base reward is credited exactly once, either by the existing path (Modes
  A and decline/expiry) or as part of the cash-out credit (Modes B/C).
- In Mode C, at no point between accept and resolution may the held amount be
  spendable: wallet `locked_balance` increases at accept, and the resolution
  writes the final ledger entries atomically with the lock update.
- The **bonus is part of the cash-out credit**, not a separate entry in Modes
  B/C. In Mode A the bonus is a separate credit with its own `reference_type`.
- The existing `mission_reward` idempotency stays intact: the risk flow never
  writes a `mission_reward` reference.

## Ledger transaction types

New types, all immutable, all with `reference_type = 'risk_bonus'` and
`reference_id = <risk_ladder_run_id>`:

| Event | `transaction_type` | Direction | When |
|---|---|---|---|
| stake held | `risk_hold` | debit | Modes B/C, at accept: base moves into lock |
| cash out | `credit` | credit | Modes B/C: `base * payout_k` replaces the hold |
| bust (full) | `risk_bust` | — | Mode C: hold finalized as a real debit, no refund |
| bust (partial) | `risk_bust` + `credit` | — | Mode B: forfeited fraction debit, remainder released |
| hold released | `credit` | credit | Modes B/C expiry: hold returns in full |
| bonus paid | `credit` | credit | Mode A only: separate bonus on cash out |

Uniqueness: at most one resolving entry set per
`(wallet_id, 'risk_bonus', run_id)`. A repeated settlement, retried request, or
replayed cash-out cannot pay twice. `risk_hold` and its resolution are linked by
`reference_id = <risk_ladder_run_id>` so every hold has exactly one terminal
state: cashed out, busted, or released.

## Server authority and anti-cheat

The existing minigame handler contract is `generate_session(settings)` and
`validate_submission(session_data, sequence)`; handlers do not touch the ledger.
The risk ladder follows the same shape and the same rule.

A browser-based Tetris is trivially cheatable: the client owns the game loop and
can report any result. Therefore:

- the server issues a **seeded** challenge per level and keeps the seed;
- the client submits **the input sequence, not the score**;
- the server replays the sequence deterministically against the same seed and
  derives the outcome itself;
- a submission whose replay disagrees with the claimed result is rejected and
  recorded as an anticheat event;
- per-level time limits are enforced server-side against the attempt deadline.

A ladder that cannot be replayed deterministically server-side must not be
published as a risk offer.

## Configuration (CMS / System Settings)

Per-ladder CMS entity, not code constants:

- `levels[]`: `level`, `challengeSettingsJson`, `payoutRatioScaled`,
  `timeLimitSeconds`;
- `riskMode`: `full_stake` (default) | `bonus_only` | `partial_stake`;
- `partialStakeFractionScaled` (Mode B only);
- `offerTtlSeconds` — how long an offer stays open;
- `minBaseRewardRoot` — offers below this amount are not issued;
- `enabled` feature flag, per mission and globally.

Validation rules enforced on publish:

- `payoutRatioScaled` must be non-decreasing and must satisfy the geometric
  bound implied by the configured clear chance of that level;
- at least one level must be publishable;
- Mode B requires a non-zero `partialStakeFractionScaled` below `1.0`;
- archiving a ladder never rewrites already-issued offers — each
  `RiskLadderRun` stores its immutable effective snapshot.

## Player-facing rules

- The offer is optional and always declines safely.
- The player sees the payout for every level before starting, and the exact
  amount at risk.
- Cash out is available after each cleared level; there is no forced march to
  the top.
- The offer is single-use per settled run and expires.

## Open decisions (blocking implementation)

1. ~~**Risk mode.**~~ **Resolved 2026-11-26**: Mode C (`full_stake`) is the
   product default, selected by the product owner in writing. Modes A and B
   remain in the schema as alternatives the CMS can publish per ladder.
2. **Wagering status.** With Mode C as default, this IS a wagering product on a
   withdrawable currency. The product owner has accepted this; the remaining
   question is jurisdiction/legal review before public launch, owned by the
   product owner, not engineering.
3. **Game type for the first vertical.** A deterministic, replayable challenge is
   required; a falling-block game qualifies only if the server can replay it.
4. **Ladder size and ratios.** The actual numbers are CMS data, but the first
   published ladder needs a proposed table for review.
5. **Admin approval requirement.** Publishing a full-stake ladder that can void
   a settled reward requires super-admin approval, following the payout
   precedent.

No code, schema, migration, API, or admin surface is created until decisions 3,
4, and 5 are answered in writing.
