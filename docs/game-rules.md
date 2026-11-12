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

<!-- stage-3-2-runtime-contract-reconciliation -->

## Solo run, rewards and fallback clarification

A paid solo MissionRun starts through one atomic direct-start operation:
validate published content, prerequisites, repeatability, active-run limits,
feature flags, ROOT and key requirements; lock wallet/inventory rows; debit
ROOT; consume required keys/items; and create `MissionRun(active)` with its
immutable effective configuration snapshot.

Solo runs do not reserve entry resources. Reservations apply only to future
geo/team assembly before shared server-validated activation.

Maximum attempts and non-increasing reward multipliers are validated CMS or
System Settings data. The current default of three attempts and 100/50/25
percent multipliers is not hardcoded runtime behavior.

A qualifying consumptive first-attempt outcome may create personal fallback
eligibility and add one configured unit to a global offer pool exactly once.
Fallback uses a pre-published CMS product. Purchase atomically debits ROOT,
decrements pool, credits inventory, and consumes entitlement capacity; it
never automatically changes an already active run.

Detailed contracts: `docs/mission-run-contract.md`,
`docs/inventory-ledger-contract.md`, `docs/fallback-shop-contract.md`.

## Реферальная программа (Sprint Referral R-8)

Игрок A приглашает игрока B по ссылке `https://t.me/<bot>?start=ref_<player_id_A>`
(текст ссылки собирает backend, игрок только делится ею из профиля).

Правила:

1. B привязывается к A при **регистрации** (start_param `ref_<A>` из
   подписанного Telegram initData). Привязка возможна только для нового
   профиля: существующий игрок не переатрибутируется, повторный вход по чужой
   ссылке ничего не меняет.
2. Когда B накапливает earned ROOT `>= economy.transfer_minimum_earned_root`
   (тот же порог, что открывает игроку переводы), A получает
   `referral.reward_root` ROOT одной immutable-проводкой
   (`reference_type = "referral_reward"`).
3. Earned ROOT считается только по подтверждённым наградам миссий
   (`reference_type = "mission_reward"`): переводы, покупки в магазине,
   админ-корректировки и сам реферальный бонус в зачёт не идут.
   Earned ROOT считается в наноROOT по точной сумме; сравнение с порогом —
   в наноROOT.
4. Один приглашённый B даёт ровно одну награду — `UniqueConstraint` на
   `ReferralReward.referred_player_id` плюс доменный статус
   `pending → credited`; повторное начисление невозможно. Статус
   `cancelled` зарезервирован в схеме (CHECK-ограничение) на будущее, но
   переход в него в текущей реализации не выполняется.
5. Защита от фарма: бонус не выдаётся «за клик по ссылке» — B должен реально
   играть и накопить earned ROOT (обычно это требует прохождения миссий).
   Дополнительно награда не выдаётся при `referral.enabled = false`. При
   несуществующем/неактивном пригласившем (проверка выполняется в момент
   привязки, то есть регистрации приглашённого) и при попытке пригласить
   самого себя запись награды не создаётся; последующая смена статуса
   реферера уже созданную запись не отменяет.
6. Жизненный цикл записи: `ReferralReward` создаётся в `pending` при привязке
   и переходит в `credited` при начислении. Физическое удаление запрещено;
   `GamePlayer.referred_by_player_id` и `referral_rewards` — immutable-история.

Расчёт и состояние: `app/referral_service.py`; начисление инициируется из
награды миссии (`mission_engine._award_mission_rewards`, SAVEPOINT), то есть
реферальный бонус не имеет отдельного «ручного» пути выдачи.

## Переводы ROOT между игроками

**Идемпотентность**: `request_id` уникален в паре `(from_player_id, request_id)`;
повторный запрос возвращает сохранённый результат без второго списания.

**Лимиты** (CMS, целые ROOT): `economy.transfer_min_amount` (default 1; для дробей
< 1 ROOT — 0), `economy.transfer_max_amount` (10000), `economy.daily_transfer_limit`
(50000 ROOT за UTC-сутки; считается по точной nano-сумме).

**Порог earned**: переводить может игрок, заработавший
`>= economy.transfer_minimum_earned_root` (50 ROOT) только наградами миссий
(`mission_reward`); реферальный бонус, покупки, админ-корректировки не в зачёт.

**Дробные суммы**: шаг 1 наноROOT (0.00000001 ROOT); legacy-поле `amount` — floor,
для сумм < 1 ROOT = 0 (точная сумма в `amount_nano`). Для дробей < 1 ROOT
администратор выставляет `economy.transfer_min_amount = 0`.

**Комиссия**: газ (`GasWallet`) — `economy.gas_fee_percent` % от суммы; при
недостатке газа — 402, откат.

**Ограничения**: `blocked` / `suspended` / `transfer_restricted` — 403.

## Подтверждение присутствия (location proof)

Solo-миссии могут требовать подтверждение присутствия: игрок нажимает
«Подтвердить присутствие» в терминале, сервер проверяет зону и accuracy.
Гейт включается CMS-ключом `geo.solo_proof_mode=enforce` (по умолчанию off).
Без свежего verified proof при enforce — сдача миссии отклоняется (409).

