# Контракт политики одиночной runtime-миссии

## Назначение
Документ определяет первую версию server-side одиночных runtime-миссий.
Он применяется вместе с mission-run, inventory-ledger, ROOT-ledger,
system-settings и API contracts.

## Границы первой версии
Включено: прямой атомарный start solo run, выдача cipher attempt,
server-side submit/resolve, settlement успеха/неуспеха/таймаута,
награды ROOT и предметами.
Не включено: team sessions, geo/location proof, AR/QR, reservations,
fallback offers/purchases, entitlement creation, TON, Stars, transfers,
withdrawals и story_node reward через runtime settlement.
Legacy POST /api/v1/engine/missions/{mission_id}/submit остаётся отдельным
совместимым API и не использует новый executor для ledger-операций.

## Lifecycle MissionRuntimePolicy
Policy разрешена только для Mission с mission_type=solo.
Lifecycle: draft -> published -> archived.
Для одной Mission разрешена только одна published policy.
Published policy неизменна: изменение требует новой policy с увеличенным version,
её публикации и archive предыдущей policy.
Archive запрещает новые starts, но не меняет historical run, attempt,
settlement, wallet transaction или inventory event.
При старте сохраняются runtime_policy_id, runtime_policy_version и полный
immutable effective_config_snapshot.

## Скалярные правила policy
entry_root_atomic: целое число >= 0.
max_attempts: целое число от 1 до 10.
attempt_deadline_seconds: целое число от 1 до 86400.
repeatability_policy: только one_time, after_terminal, after_failure_only.
fallback_policy_json: в первой версии только null.
feature_flags_json: только валидированная не-секретная feature policy.

## Повторное прохождение
one_time: новый run запрещён после успешного terminal run этой Mission.
after_terminal: новый run разрешён после любого terminal run.
after_failure_only: новый run разрешён после failed, timeout или abandoned,
но запрещён после succeeded.
Active run всегда блокирует новый start той же Mission.
Executor также проверяет missions.max_active_solo из System Settings.

## Entry items
required_items_json имеет schemaVersion=1 и массив items.
Каждый item содержит уникальный itemId и quantity от 1 до 2147483647.
Массив содержит от 0 до 100 требований; требования имеют AND-семантику.
При публикации и при start Item должен быть published.
Списание происходит в одной транзакции со start и создаёт immutable
InventoryEvent с reference точного MissionRun.

## Cipher
challenge_policy_json имеет schemaVersion=1 и challengeType=cipher.
drumCount: от 1 до 12; alphabet: от 2 до 64 уникальных display strings;
falseChoicesPerDrum: от 0 до 16.
Сервер генерирует правильную комбинацию при issue attempt и сохраняет её
только в protected_challenge_snapshot.
Игрок получает только видимые варианты, длину комбинации и deadline.

## Награды
reward_policy_json имеет schemaVersion=1, attemptMultipliers и rewards.
Количество multipliers равно max_attempts; первый равен 1.0,
значения находятся в диапазоне 0..1 и не возрастают.
Допустимы только root с положительным amountAtomic и item с published itemId
и положительным quantity. story_node reward запрещён в первой версии.
Успешный settlement применяет multiplier по sequence_number.
ROOT рассчитывается детерминированной целочисленной арифметикой.
ROOT credit и item credit ссылаются на точный MissionSettlement.id.
Повторный submit/settlement не создаёт вторую награду.

## Целостность и snapshot
Все ROOT значения — integer atomic units; float для финансов запрещён.
WalletTransaction и InventoryEvent append-only; balance и quantity не могут
стать отрицательными.
Snapshot включает policy ID/version, entry requirements, attempt/deadline,
repeatability, challenge, reward policy и разрешившее start feature decision.
Snapshot не содержит initData, tokens, cookies, client answers, audit metadata,
raw coordinates или другие private данные.
Изменения CMS или System Settings после старта не меняют уже созданный run.

## Runtime lifecycle
no run -> active -> succeeded | failed | timeout | abandoned.
Solo flow не использует reserved или accepted.
Новая attempt не выдаётся при существующей unresolved issued attempt.
Terminal attempt и terminal run повторно не изменяются.
Success создаёт один settlement с reward; terminal failure/timeout/abandonment
создаёт один settlement без success reward.
