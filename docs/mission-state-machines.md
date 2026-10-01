# Состояния миссий и заявок

## Текущие player mission states
`locked`, `available`, `completed`.

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

В `collecting` участники имеют резерв ROOT/keys. Переход
`ready_to_start -> active` атомарно повторно проверяет team size, readiness,
fresh geo/proximity rule D, списывает entry fee/keys и активирует member runs.
Wrong answer, explicit exit или timeout одного active member завершают всю
session как `failed`. Детали: `docs/geo-team-mission-contract.md`.

## Approval request
`pending -> approved | rejected | cancelled | expired`
`approved -> executed | execution_failed`

Нельзя approve собственную заявку; execution использует snapshot и
выполняется идемпотентно.
