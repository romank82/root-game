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

## Вывод ROOT в TON (внешние выплаты)

Реализовано: ручная оплата батча из кошелька владельца через TON Connect.
Подробности — `withdrawal-external-payout.md`.

Две проводки на жизненный цикл заявки:

| Событие | `transaction_type` | `reference_type` | Когда |
|---|---|---|---|
| Заявка создана | `debit` | `withdrawal_hold` | ROOT уходит в холд |
| Выплата не состоялась | `credit` | `withdrawal_refund` | холд возвращается |

Ключевое: **подтверждение выплаты (`confirmed`) не создаёт проводку**. Деньги
списаны ещё в холд при создании заявки, выплата лишь подтверждает, что они
дошли до игрока. Возврат возможен только до подтверждения — после того как
перевод найден в блокчейне, откат запрещён, иначе ledger зафиксирует двойную
трату.

Приватный ключ кошелька выплат на сервере отсутствует: сервер формирует
`query_id`, проверяет подписанный BOC и сверяет блокчейн, но отправить перевод
сам не может.


## Mission-run and fallback economic operations

ROOT is persisted in integer atomic units, which since Sprint 11.8 are
nanoROOT (1 ROOT = 10^8 nanoROOT). All balances, prices, rewards, multipliers
and ledger calculations use integer nanoROOT (`*_nano` BigInteger). Floating-point
arithmetic is forbidden. Legacy `*_root` (Integer) fields are derived:
`*_root = *_nano // 10^8` (floor), may be 0 for fractions < 1 ROOT.

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
  дополнительно доменный статус `pending → credited` исключает повторное
  начисление (статус `cancelled` зарезервирован в схеме — CHECK-ограничение,
  но переход в него в текущей реализации не выполняется);
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

## Переводы и пороги в наноROOT (Sprint 8.x-fractional-transfer)

`earned` (`transfer_service.transfer_root` шаг 4 + `referral_service._earned_nano`):
`SUM(coalesce(amount_nano, CAST(amount AS BIGINT) * 10^8))` по credit-проводкам
`reference_type = "mission_reward"`; сравнение с
`economy.transfer_minimum_earned_root * 10^8`.

`daily`-лимит: `SUM(PlayerTransfer.amount_nano)` за UTC-сутки (fallback на
`CAST(amount AS BIGINT) * 10^8`), сравнение с `economy.daily_transfer_limit * 10^8`.

`audit` балансов (`/admin/economy/audit`): credit/debit `SUM` по
`coalesce(amount_nano, CAST(amount AS BIGINT) * 10^8)`; сравнение с
`available_balance_nano`; mismatch-поля `expectedNano`/`actualNano`/`differenceNano`.

`stats` профиля (`admin_players`): `totalRootEarned`/`totalRootSpent` (floor) +
`totalRootEarnedNano`/`totalRootSpentNano` (точные).

legacy `player_transfers.amount`: `floor(amount_nano / 10^8)`, для дробей < 1 ROOT = 0
(`CHECK amount >= 0`, миграция `f06ca2ff1b61`).
