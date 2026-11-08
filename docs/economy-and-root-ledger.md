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

## Реферальная награда (Sprint Referral R-4 / R-6)

ROOT пригласившему начисляется отдельной immutable-проводкой:

- `transaction_type = "credit"`, `reference_type = "referral_reward"`,
  `reference_id = ReferralReward.id`, `amount = ReferralReward.amount_root`,
  `balance_after` — баланс кошелька пригласившего после начисления;
- идемпотентность — тот же unique-индекс
  `(wallet_id, reference_type, reference_id)`: одна запись `ReferralReward`
  даёт не более одной проводки даже при гонке двух параллельных submit;
  дополнительно доменный статус `pending → credited | cancelled` исключает
  повторное начисление;
- сумма фиксируется в `ReferralReward.amount_root` в момент привязки
  (значение CMS `referral.reward_root` на тот момент) — настройка не
  переписывает историю задним числом;
- `referral_reward` **не входит** в «earned ROOT»: порог
  `economy.transfer_minimum_earned_root` и `transfer_root` считают только
  кредиты с `reference_type = "mission_reward"`. Реферальный бонус не даёт
  доступа к переводам;
- начисление выполняется в транзакции награды миссии, но в отдельном
  SAVEPOINT: провал реферального бонуса откатывает только бонус и не ломает
  выданную награду миссии (никаких «полу-начисленных» состояний).
