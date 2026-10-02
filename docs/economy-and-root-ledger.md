# Экономика ROOT и ledger

## Реализовано сейчас
Есть wallets и wallet_transactions: amount, balance_after, transaction type,
reason, reference, metadata и timestamps. Уникальность
`(wallet_id, reference_type, reference_id)` предотвращает двойную reward
проводку одной миссии.

## Целевой ledger
Каждое изменение ROOT создаёт неизменяемую проводку с:
`amount_root`, `direction`, `balance_before`, `balance_after`,
`transaction_type`, `reference_type`, `reference_id`, `idempotency_key`,
`reason`, `metadata`, `initiated_by_type`, `initiated_by_id`.

Wallet balance является кэшем; ledger — источником истины.
До отдельной миграции запрещены реальные transfers, Stars и TON withdrawals.

<!-- stage-3-2-runtime-contract-reconciliation -->

## Mission-run and fallback economic operations

ROOT is persisted in integer atomic units. Floating-point arithmetic is
forbidden for balances, prices, rewards, multipliers, or ledger calculations.

At paid solo run start, one dedicated executor atomically locks the wallet,
checks sufficient non-negative available balance, writes one immutable entry
debit with a run-specific reference, updates the cached balance, consumes
required items through the inventory ledger, and creates the active run.

All configured attempts are included in that entry price unless a future
separately documented CMS flow explicitly defines another charging model.

Successful settlement derives ROOT reward from immutable run configuration and
attempt multiplier. It writes one settlement/run-specific immutable credit.
A fallback purchase writes one purchase-specific immutable debit atomically
with entitlement consumption, global-pool decrement, and inventory credit.

There is no ordinary post-start refund or fallback-purchase reversal. Any
exceptional compensation is a separately authorized immutable transaction
referencing the original operation; history is never rewritten.

Detailed contracts: `docs/mission-run-contract.md`,
`docs/inventory-ledger-contract.md`, and `docs/fallback-shop-contract.md`.
