# Игровые правила

## Реализовано сейчас
Есть prerequisites `mission_completed`, состояния `locked`, `available`,
`completed`, награды ROOT/предметами/сюжетными узлами и защита от повторной
mission reward через уникальность transaction source.

## Целевые правила
Контент: `draft -> published -> archived`.

Типы миссий: `solo`, `team`, `global`.
Базовый лимит: не более 1 active solo + 1 active team + 1 active global
миссии на игрока. Лимиты хранятся в system settings.

Нельзя публиковать self-reference, циклические зависимости, ссылки на
archived/несуществующий контент или недействительные награды.

Целевой default попыток: 3; награда 100% / 50% / 25%.
Ключ и entry fee списываются атомарно при принятии миссии.
