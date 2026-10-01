# Geo, Team and Cipher Mission Contract

## Scope

This is the target contract for the geo/team mission vertical. Existing
single-submit mission endpoints do not implement it yet.

The MVP assembly mode is `local_matchmaking`: a player joins only a compatible
open session for the same published mission and server-validated geo context.
Invite-only is out of scope.

CMS lifecycle (`draft -> published -> archived`) is distinct from runtime
state. Published content, historical runs, attempts, reservations, ledger and
inventory events, and audit records are never physically deleted.

## CMS-owned configuration

Mission, geo/AR, and shop rules are CMS data, not hardcoded domain behavior.
Code contains only schema/bounds validation, state-machine mechanics, security,
and domain executors.

A published team mission defines or inherits validated configuration for:
- team size/range and `local_matchmaking`;
- entry fee in integer ROOT atomic units;
- required item/key quantities; all requirements use AND semantics;
- maximum attempts and non-increasing reward multipliers;
- geo zone, proof freshness, pairwise proximity rule D, and periodic-check policy;
- AR/QR activation, challenge/deadline policy, rewards, and fallback offer.

Platform defaults and feature flags may come from System Settings. Specific
mission economics, distances, timeouts, item requirements, and rewards remain
versioned CMS configuration. Each run stores an immutable effective
configuration snapshot; later CMS edits never rewrite prior runtime history.

`PlayerMission` remains a current-progress projection, not run history.
Future runtime entities are `MissionRun`, `MissionAttempt`, `TeamSession`,
`TeamSessionMember`, `WalletReservation`, `InventoryReservation`, immutable
inventory events, and a per-player fallback enforcement record.

## Geo eligibility and session state

Client coordinates, browser distance checks, QR scans, and claimed proximity
are untrusted inputs. Before join/reserve and again immediately before start,
backend validates: published mission/geo policy, fresh server-validated
location proof, zone membership, pairwise proximity rule D, capacity, and
non-terminal session state.

Public `safeScanPoint` coordinates are navigation data only. They are not a
LocationProof and never authorize join, reserve, start, progress, or reward.
Raw location evidence, protected QR data, and anti-abuse signals are
server-side; raw private location data is not copied to admin audit.

```text
TeamSession:
collecting -> ready_to_start -> active -> succeeded | failed | expired
collecting | ready_to_start -> cancelled_before_start

MissionRun:
reserved -> accepted -> active -> succeeded | failed | timeout | abandoned
reserved | accepted -> cancelled_before_start

MissionAttempt:
issued -> submitted -> succeeded | failed
issued -> timed_out
```

Members in `collecting` hold active reservations and may leave before start; their reservations are released. A runtime session is never created in `draft`.

The `ready_to_start -> active` transition is atomic: lock the eligible session, memberships, wallets, inventory, and reservations; revalidate team size, readiness, geo/proximity and CMS eligibility; charge reserved entry fees; consume reserved keys; create active runs/attempts; mark the session active. No partial start is valid.

After `active`, explicit exit, wrong answer, or server-side deadline failure of one member produces one idempotent shared `failed` settlement with no rewards for all members. WebApp closure, network loss, or a missing periodic location update is not by itself an immediate exit. Periodic enforcement requires an explicit published policy.

## Cipher, settlement, and security

A `cipher` attempt is created server-side for an active run and stores immutable challenge state, issue time, deadline, and outcome. Backend, not the device clock, decides expiry. Submission is idempotent per attempt and request key.

For the first cipher flow, backend validates AR/QR activation, issues the attempt-specific visible code and deadline, then validates ownership, active run/session, deadline, and submitted combination against the server snapshot. A visible code may be shown to its intended player, but is never trusted back as proof of success. Answers, protected challenge state, QR secrets, and raw activation evidence never enter bootstrap, frontend bundles, audit, or ordinary error logs.

ROOT uses integer atomic units. `WalletTransaction` is the immutable ledger; wallet balances are cached projections and cannot become negative. Before start, a reservation moves no more than the configured entry fee from available to locked. Required keys are also reserved. Charge/consume/release operations are idempotent and cannot make balances or inventory negative.

At start, fee charge and key consumption occur in the same transaction as activation. Before-start cancellation releases both. A post-start refund exists only under an explicit published CMS policy. Rewards are per successful `MissionRun`, use its snapshot and attempt multiplier, and reference the exact settlement event rather than only `mission_id`.

Fallback eligibility and quota are per-player and server-enforced. A purchase is an idempotent atomic ROOT debit plus entitlement creation.

Future geo/AR, team-session, shop, and economy administration require explicit permissions and domain-specific approval flows where policy requires them. Admin audit uses only safe allowlisted metadata and excludes raw coordinates, proofs, QR data, answers, challenge state, private chat content, and secrets. Team chat/moderation/retention requires a separate contract.
