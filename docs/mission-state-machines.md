# Состояния миссий и заявок

## Текущие player mission states
`locked`, `available`, `in_progress`, `completed`, `cancelled`.

`cancelled` — admin-only terminal status (шаг 5.6.a). Устанавливается через
`POST /api/v1/admin/players/{id}/missions/{mission_id}/mission-cancel`.
Ресурсы при отмене не возвращаются; компенсация при необходимости — ручными
операциями 5.4/5.5. Отменённая миссия не удовлетворяет `MissionRequirement`
зависимых миссий и не реактивируется движком: `_synchronize_player_missions`
пропускает терминальные статусы, `_submit_mission_once` отвечает 409.
Fallback-entitlement независим от статуса миссии; отключается только при
`invalidate_fallback_entitlement=true` (available -> disabled).

`completed` — достижим игровым движком (submit) и админ-операцией force-complete
(шаг 5.6.b): `POST .../missions/{mission_id}/mission-force-complete` из
`available`/`in_progress`/`locked`. Награды выдаются опционально (`awardRewards`;
ROOT — ledger-idempotent), entry-ресурсы не возвращаются, entitlement не трогается.
Повтор операции на `completed`/`cancelled` — 409; повтор с тем же `request_id` — 200 idempotent.

`attempt_count` — исторический счётчик попыток, отдельно корректируется админ-операцией (шаг 5.6.c):
`POST .../missions/{mission_id}/attempts-adjustment` устанавливает значение абсолютно
(`new_attempt_count` в `[0, 1000]`, не дельта). Изменяется только `attempt_count` —
`status`/`started_at`/`progress` не трогаются; терминальные статусы недоступны (409, кроме
идемпотентного replay 200 из admin_audit_log). Установка `0` при отсутствии активного
fallback-entitlement означает: следующий неверный submit может создать новое fallback-предложение
(guard `attempt_count_before == 0`); при существующем entitlement эффекта нет.

## Целевой mission run
`PlayerMission` остаётся current-progress projection. Исторический runtime
использует отдельные `MissionRun` и `MissionAttempt`.

`MissionRun: reserved -> accepted -> active`
`active -> succeeded | failed | timeout | abandoned`
`reserved | accepted -> cancelled_before_start`

`MissionAttempt: issued -> submitted -> succeeded | failed`
`issued -> timed_out`

Детали: `docs/geo-team-mission-contract.md`.

Переходы выполняются транзакционно и соблюдают system limits.

## Team mission
CMS lifecycle не является runtime state team session.

`TeamSession: collecting -> ready_to_start -> active`
`active -> succeeded | failed | expired`
`collecting | ready_to_start -> cancelled_before_start`

В `collecting` взнос ROOT и required items уже списаны при accept:
создание сессии (create) и вступление (join). Переход
`ready_to_start -> active` атомарно повторно проверяет team size, readiness и
fresh geo/proximity rule D, затем активирует member runs; повторного списания
entry fee/keys на старте нет. Окно отказа с возвратом — 3 минуты от
`TeamSession.created_at`; после окна выход до `active` разрешён, но без
возврата. Wrong answer, explicit exit или timeout одного active member
завершают всю session как `failed`. Детали:
`docs/geo-team-mission-contract.md`.

## Approval request
`pending -> approved | rejected | cancelled | expired`
`approved -> executed | execution_failed`

Нельзя approve собственную заявку; execution использует snapshot и
выполняется идемпотентно.

<!-- stage-3-2-runtime-contract-reconciliation -->

## Solo and team runtime clarification

`PlayerMission` is a current-progress projection, not historical runtime
history. `MissionRun` and `MissionAttempt` are the shared runtime records;
one terminal `MissionRun` has at most one `MissionSettlement`.

For the first paid solo vertical, start is direct and atomic: validate player,
published/effective mission policy, prerequisites, active-run limits,
repeatability, ROOT and item requirements; lock applicable rows; debit ROOT,
consume required items, snapshot configuration, and create `MissionRun(active)`
in one transaction. Solo start does not use a reservation phase.

The existing `reserved -> accepted -> active` MissionRun path remains a target
for future pre-start assembly; current paid solo and team verticals charge
directly at accept/start without a reservation phase. It must not be imposed
on solo runs.

Target solo attempt lifecycle:

```text
no attempt -> issued -> submitted -> succeeded | failed
issued -> timed_out
```

Attempt sequence numbers are positive and unique within a run. The backend
decides deadline and outcome. Technical failures without a committed outcome
do not consume an attempt; committed retries return the previous result for
the same idempotency key.

Details: `docs/mission-run-contract.md`,
`docs/inventory-ledger-contract.md`, and `docs/fallback-shop-contract.md`.
