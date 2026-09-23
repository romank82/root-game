# Состояния миссий и заявок

## Текущие player mission states
`locked`, `available`, `completed`.

## Целевой mission run
`locked -> available -> accepted -> active`
`active -> completed | failed | cancelled | expired`

Переходы выполняются транзакционно и соблюдают system limits.

## Team mission
`team_run: draft -> collecting_presence -> activated -> closed`
`member_run: accepted -> active -> completed | failed | cancelled | expired`

## Approval request
`pending -> approved | rejected | cancelled | expired`
`approved -> executed | execution_failed`

Нельзя approve собственную заявку; execution использует snapshot и
выполняется идемпотентно.
