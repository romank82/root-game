# Игровые правила

## Реализовано сейчас
Есть prerequisites `mission_completed`, состояния `locked`, `available`,
`completed`, награды ROOT/предметами/сюжетными узлами и защита от повторной
mission reward через уникальность transaction source.

## Public content boundary
Public CMS-managed Segment/Mission presentation and the protected-state boundary are defined in `docs/segment-content-contract.md`. Reward preview may be displayed but never authorizes progress or an award; actual grants are confirmed only by backend submit response, ledger, and inventory transaction.

## Целевые правила
Контент: `draft -> published -> archived`.

### Сегменты и миссии

Segment управляется CMS и имеет lifecycle `draft -> published -> archived`.
Снятие Segment с публикации переводит его из `published` в `draft`; `archived`
является финальным статусом. Физическое удаление Segment, Mission и их связей
запрещено.

Связь Segment с Mission допускается только если обе сущности принадлежат одной
и той же `chapter_id`. SegmentMission — самостоятельная историческая сущность
с lifecycle `active -> archived`; физическое удаление связей запрещено.

Одновременно может существовать не более одной active-связи одной пары
`(segment_id, mission_id)`. После archive Mission можно повторно связать с тем
же Segment только новой immutable SegmentMission-записью с новым `id`;
предыдущая archived-связь остаётся в истории. `sort_order` изменяется только
у active-связи.

Для публикации Segment обязан иметь хотя бы одну active-связь с Mission в
статусе `published`. Игровой bootstrap возвращает только active-связи с
опубликованными Mission, упорядоченные по `sort_order`.

Типы миссий: `solo`, `team`, `global`.
Базовый лимит: не более 1 active solo + 1 active team + 1 active global
миссии на игрока. Лимиты хранятся в system settings.

Нельзя публиковать self-reference, циклические зависимости, ссылки на
archived/несуществующий контент или недействительные награды.

Целевой default попыток: 3; награда 100% / 50% / 25%.
При принятии mission/team session ROOT и required keys резервируются.
Их окончательное списание происходит атомарно только при server-validated
старте; отмена до старта освобождает резерв. Детальный geo/team/cipher
контракт: `docs/geo-team-mission-contract.md`.
