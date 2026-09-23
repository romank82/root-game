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
