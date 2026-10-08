from __future__ import annotations

from datetime import datetime, timezone
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.fallback_shop import create_first_failure_entitlement
from app.player_restrictions_engine import recompute_player_status
from app.models import (
    GamePlayer,
    InventoryEvent,
    Item,
    KeyRules,
    Mission,
    MissionRequirement,
    MissionReward,
    MissionRuntimePolicy,
    PlayerItem,
    PlayerMission,
    Segment,
    StoryNode,
    Wallet,
    WalletTransaction,
)

ROOT_CURRENCY = "ROOT"

# Reference-типы входа в миссию (шаг 4.1). Значения — по контракту ledger:
# уникальные ключи идемпотентности = (wallet_id, reference_type, reference_id)
# и (player_item_id, event_type, reference_type, reference_id).
ENTRY_DEBIT_REFERENCE_TYPE = "mission_entry_debit"
ENTRY_ITEM_REFERENCE_TYPE = "mission_entry"
ENTRY_ITEM_EVENT_TYPE = "consumed"


class MissionEngineError(Exception):
    """Ожидаемая ошибка нового игрового API."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_player(session: Session, player_id: str) -> GamePlayer:
    player = session.get(GamePlayer, player_id)

    if player is None:
        raise MissionEngineError(404, "Игрок не найден.")

    if player.status != "active":
        # Lazy-рикавери (шаг 5.7): истёкшие/снятые ограничения не должны
        # навсегда запирать игрока вне входа. PlayerRestriction — источник
        # истины, GamePlayer.status — синхронизируемый кэш.
        recompute_player_status(session, player)
        if player.status != "active":
            raise MissionEngineError(403, "Игровой профиль неактивен.")

    return player


def _get_or_create_root_wallet(session: Session, player_id: str) -> Wallet:
    wallet = session.scalar(
        select(Wallet).where(
            Wallet.player_id == player_id,
            Wallet.currency == ROOT_CURRENCY,
        )
    )

    if wallet is None:
        wallet = Wallet(
            id=_new_id("wallet"),
            player_id=player_id,
            currency=ROOT_CURRENCY,
            available_balance=0,
            locked_balance=0,
        )
        session.add(wallet)
        session.flush()

    return wallet


def _get_published_runtime_policy(
    session: Session,
    mission_id: str,
) -> MissionRuntimePolicy | None:
    """Единственная опубликованная policy миссии (или None для legacy-миссий).

    Частичный unique index ``uq_mission_runtime_policies_one_published_per_mission``
    гарантирует на уровне БД не более одной published policy на миссию,
    поэтому scalar безопасен.
    """
    return session.scalar(
        select(MissionRuntimePolicy).where(
            MissionRuntimePolicy.mission_id == mission_id,
            MissionRuntimePolicy.status == "published",
        )
    )


def _requirements_met(
    mission_id: str,
    requirements_by_mission: dict[str, list[MissionRequirement]],
    completed_mission_ids: set[str],
) -> bool:
    """Все requirements работают по AND; неизвестный тип блокирует миссию."""
    for requirement in requirements_by_mission.get(mission_id, []):
        if requirement.requirement_type != "mission_completed":
            return False

        required_id = requirement.requirement_value.get("missionId")

        if not required_id or required_id not in completed_mission_ids:
            return False

    return True


def _synchronize_player_missions(
    session: Session,
    player_id: str,
) -> dict[str, PlayerMission]:
    """Создать недостающий прогресс и пересчитать locked/available статусы."""
    missions = session.scalars(
        select(Mission)
        .where(Mission.status == "published")
        .order_by(Mission.sort_order, Mission.id)
    ).all()

    requirements_by_mission: dict[str, list[MissionRequirement]] = {}
    for requirement in session.scalars(select(MissionRequirement)).all():
        requirements_by_mission.setdefault(requirement.mission_id, []).append(
            requirement
        )

    rows = session.scalars(
        select(PlayerMission).where(PlayerMission.player_id == player_id)
    ).all()

    progress = {row.mission_id: row for row in rows}
    completed = {
        row.mission_id for row in rows
        if row.status == "completed"
    }

    for mission in missions:
        player_mission = progress.get(mission.id)

        if player_mission is None:
            player_mission = PlayerMission(
                id=_new_id("player-mission"),
                player_id=player_id,
                mission_id=mission.id,
                status="locked",
                attempt_count=0,
                progress={},
            )
            session.add(player_mission)
            progress[mission.id] = player_mission

        # Терминальные статусы движок не трогает: cancelled — admin-only
        # terminal, синхронизация не имеет права «реактивировать» отмену.
        if player_mission.status in {"completed", "cancelled"}:
            continue

        if _requirements_met(mission.id, requirements_by_mission, completed):
            if player_mission.status == "locked":
                player_mission.status = "available"
        else:
            player_mission.status = "locked"

    session.flush()
    return progress


def _serialize_item(player_item: PlayerItem, item: Item) -> dict:
    return {
        "id": item.id,
        "slug": item.slug,
        "code": item.code,
        "title": item.title,
        "description": item.description,
        "symbol": item.symbol,
        "category": item.category,
        "rarity": item.rarity,
        "quantity": player_item.quantity,
    }


def _serialize_story_node(story_node: StoryNode) -> dict:
    return {
        "id": story_node.id,
        "slug": story_node.slug,
        "title": story_node.title,
        "body": story_node.body,
        "presentationType": story_node.presentation_type,
        "content": story_node.content,
    }


def _build_bootstrap(session: Session, player_id: str) -> dict:
    """
    Возвращает только публичные данные для клиента.
    validation_config намеренно никогда не включается в ответ.
    """
    player = _ensure_player(session, player_id)
    progress = _synchronize_player_missions(session, player_id)
    wallet = _get_or_create_root_wallet(session, player_id)

    missions = session.scalars(
        select(Mission)
        .where(Mission.status == "published")
        .order_by(Mission.sort_order, Mission.id)
    ).all()

    inventory_rows = session.execute(
        select(PlayerItem, Item)
        .join(Item, Item.id == PlayerItem.item_id)
        .where(PlayerItem.player_id == player_id)
        .order_by(Item.code)
    ).all()

    unlocked_story_node_exists = (
        select(MissionReward.id)
        .join(
            PlayerMission,
            PlayerMission.mission_id == MissionReward.mission_id,
        )
        .where(
            MissionReward.story_node_id == StoryNode.id,
            MissionReward.reward_type == "story_node",
            PlayerMission.player_id == player_id,
            PlayerMission.status == "completed",
        )
        .exists()
    )

    # Avoid SELECT DISTINCT over StoryNode.content (JSON): PostgreSQL JSON
    # has no equality operator. EXISTS also naturally prevents duplicates.
    story_nodes = session.scalars(
        select(StoryNode)
        .where(unlocked_story_node_exists)
        .order_by(StoryNode.sort_order, StoryNode.id)
    ).all()

    # Get published segments
    segments = session.scalars(
        select(Segment)
        .where(Segment.status == "published")
        .order_by(Segment.sort_order, Segment.id)
    ).all()

    return {
        "player": {
            "id": player.id,
            "displayName": player.display_name,
            "rootBalance": wallet.available_balance,
        },
        "wallet": {
            "currency": wallet.currency,
            "availableBalance": wallet.available_balance,
            "lockedBalance": wallet.locked_balance,
        },
        "missions": [
            {
                "id": mission.id,
                "slug": mission.slug,
                "missionType": mission.mission_type,
                "title": mission.title,
                "description": mission.description,
                "content": mission.content,
                "status": progress[mission.id].status,
                "attemptCount": progress[mission.id].attempt_count,
                "startedAt": (
                    progress[mission.id].started_at.isoformat()
                    if progress[mission.id].started_at
                    else None
                ),
                "completedAt": (
                    progress[mission.id].completed_at.isoformat()
                    if progress[mission.id].completed_at
                    else None
                ),
            }
            for mission in missions
        ],
        "segments": [
            {
                "id": segment.id,
                "slug": segment.slug,
                "title": segment.title,
                "description": segment.description,
                "content": segment.content,
                "status": segment.status,
                "sortOrder": segment.sort_order,
                "linkedMissions": [
                    {
                        "id": link.mission.id,
                        "slug": link.mission.slug,
                        "title": link.mission.title,
                    }
                    for link in sorted(
                        segment.mission_links,
                        key=lambda current: (current.sort_order, current.mission_id),
                    )
                    if (
                        link.status == "active"
                        and link.mission.status == "published"
                    )
                ],
            }
            for segment in segments
        ],
        "inventory": [
            _serialize_item(player_item, item)
            for player_item, item in inventory_rows
        ],
        "storyNodes": [
            _serialize_story_node(story_node)
            for story_node in story_nodes
        ],
    }


def get_bootstrap(player_id: str) -> dict:
    with SessionLocal.begin() as session:
        return _build_bootstrap(session, player_id)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _validate_submission(
    mission: Mission,
    answer: str | None,
    sequence: list[str] | None,
) -> bool:
    """
    Проверяет закрытый validation_config исключительно на сервере.
    """
    validator = mission.validation_config.get("validator")

    if validator == "normalized_text_match":
        if not isinstance(answer, str):
            return False

        accepted_answers = mission.validation_config.get("acceptedAnswers", [])
        normalized_answer = _normalize_text(answer)

        return any(
            normalized_answer == _normalize_text(expected)
            for expected in accepted_answers
            if isinstance(expected, str)
        )

    if validator == "ordered_blocks_match":
        correct_sequence = mission.validation_config.get("correctSequence", [])

        return (
            isinstance(sequence, list)
            and all(isinstance(block, str) for block in sequence)
            and sequence == correct_sequence
        )

    return False


def _award_mission_rewards(
    session: Session,
    player_id: str,
    mission: Mission,
) -> dict:
    """
    Выдаёт награды в той же транзакции, что и completion миссии.

    ROOT защищён на уровне БД уникальным индексом:
    wallet_id + reference_type + reference_id.
    """
    rewards = session.scalars(
        select(MissionReward)
        .where(MissionReward.mission_id == mission.id)
        .order_by(MissionReward.sort_order, MissionReward.id)
    ).all()

    wallet = _get_or_create_root_wallet(session, player_id)
    awarded_root = 0
    awarded_items: list[dict] = []
    unlocked_story_node_ids: list[str] = []

    for reward in rewards:
        if reward.reward_type == "currency":
            currency = reward.reward_value.get("currency")

            if currency != ROOT_CURRENCY or not reward.amount or reward.amount <= 0:
                continue

            existing_transaction = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id == mission.id,
                )
            )

            if existing_transaction is not None:
                continue

            wallet.available_balance += reward.amount
            awarded_root += reward.amount

            session.add(
                WalletTransaction(
                    id=_new_id("wallet-transaction"),
                    wallet_id=wallet.id,
                    amount=reward.amount,
                    balance_after=wallet.available_balance,
                    transaction_type="credit",
                    reason=f"Mission reward: {mission.slug}",
                    reference_type="mission_reward",
                    reference_id=mission.id,
                    metadata_json={
                        "missionId": mission.id,
                        "missionSlug": mission.slug,
                        "rewardId": reward.id,
                    },
                )
            )

        elif reward.reward_type == "item" and reward.item_id:
            item = session.get(Item, reward.item_id)

            if item is None:
                raise MissionEngineError(
                    500,
                    "Награда миссии ссылается на отсутствующий предмет.",
                )

            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == player_id,
                    PlayerItem.item_id == reward.item_id,
                )
            )

            quantity = reward.amount or 1

            if player_item is None:
                player_item = PlayerItem(
                    id=_new_id("player-item"),
                    player_id=player_id,
                    item_id=reward.item_id,
                    quantity=quantity,
                    obtained_from_type="mission",
                    obtained_from_id=mission.id,
                )
                session.add(player_item)
            else:
                player_item.quantity += quantity

            awarded_items.append(
                {
                    "id": item.id,
                    "code": item.code,
                    "title": item.title,
                    "quantity": quantity,
                }
            )

        elif reward.reward_type == "story_node" and reward.story_node_id:
            unlocked_story_node_ids.append(reward.story_node_id)

    session.flush()

    return {
        "root": awarded_root,
        "items": awarded_items,
        "storyNodeIds": unlocked_story_node_ids,
    }


def _consume_entry_resources(
    session: Session,
    player_id: str,
    mission: Mission,
    player_mission: PlayerMission,
) -> None:
    """Атомарно списать ROOT-взнос и расходуемые ключи при взятии миссии.

    - Нет published policy (legacy-миссия) — вернуться без действий и логов.
    - Порядок: 1) баланс ROOT, 2) наличие/количество PlayerItem,
      3) Item.status == published, 4) debit ROOT, 5) списание ключей.
    - amount в WalletTransaction всегда положительный, направление задаёт
      transaction_type ("debit"). balance_after = баланс после списания.
    - Идемпотентность: повторный вход видит существующий WalletTransaction
      (миссия уже оплачена) или InventoryEvent (ключ уже списан) и не пишет
      дубликат; на гонки работает уникальный индекс + retry-цикл submit_mission.
    - player_mission зарезервирован под Stage 5 (snapshot/run) и в v1 не читается.
    - Любая ошибка всплывает MissionEngineError → транзакция откатывается целиком.
    """
    policy = _get_published_runtime_policy(session, mission.id)
    if policy is None:
        return

    requirements = policy.required_items_json.get("items", [])
    root_debit = policy.entry_root_atomic

    wallet = _get_or_create_root_wallet(session, player_id)

    # 1. ROOT: вход запрещён, пока не хватает баланса.
    if root_debit > 0 and wallet.available_balance < root_debit:
        raise MissionEngineError(409, "Недостаточно ROOT для взятия миссии.")

    # 2. Ключи: наличие PlayerItem и достаточное количество (AND-семантика).
    player_items: dict[str, PlayerItem] = {}
    for requirement in requirements:
        item_id = requirement["itemId"]
        required_quantity = requirement["quantity"]

        player_item = session.scalar(
            select(PlayerItem).where(
                PlayerItem.player_id == player_id,
                PlayerItem.item_id == item_id,
            )
        )
        if player_item is None or player_item.quantity < required_quantity:
            raise MissionEngineError(
                409,
                "Недостаточно ключей для взятия миссии.",
            )
        player_items[item_id] = player_item

    # 3. Lifecycle Item: повторная проверка на start (контракт policy).
    for requirement in requirements:
        item = session.get(Item, requirement["itemId"])
        if item is None or item.status != "published":
            raise MissionEngineError(409, "Ключ недоступен.")

    # 4. ROOT debit (идемпотентно по уникальному индексу wallet+reference).
    if root_debit > 0:
        existing_debit = session.scalar(
            select(WalletTransaction.id).where(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.reference_type == ENTRY_DEBIT_REFERENCE_TYPE,
                WalletTransaction.reference_id == mission.id,
            )
        )
        if existing_debit is None:
            wallet.available_balance -= root_debit
            session.add(
                WalletTransaction(
                    id=_new_id("wallet-transaction"),
                    wallet_id=wallet.id,
                    amount=root_debit,
                    balance_after=wallet.available_balance,
                    transaction_type="debit",
                    reason=f"Mission entry debit: {mission.slug}",
                    reference_type=ENTRY_DEBIT_REFERENCE_TYPE,
                    reference_id=mission.id,
                    metadata_json={
                        "missionId": mission.id,
                        "missionSlug": mission.slug,
                        "policyId": policy.id,
                        "policyVersion": policy.version,
                    },
                )
            )

    # 5. Списание ключей: только is_consumable=True; остальные уже проверены.
    for requirement in requirements:
        item_id = requirement["itemId"]

        rule = session.scalar(
            select(KeyRules).where(KeyRules.item_id == item_id)
        )
        # Нет записи KeyRules — дефолт модели: ключ расходуется.
        if rule is not None and not rule.is_consumable:
            continue

        player_item = player_items[item_id]
        required_quantity = requirement["quantity"]

        existing_event = session.scalar(
            select(InventoryEvent.id).where(
                InventoryEvent.player_item_id == player_item.id,
                InventoryEvent.event_type == ENTRY_ITEM_EVENT_TYPE,
                InventoryEvent.reference_type == ENTRY_ITEM_REFERENCE_TYPE,
                InventoryEvent.reference_id == mission.id,
            )
        )
        if existing_event is not None:
            continue

        player_item.quantity -= required_quantity
        session.add(
            InventoryEvent(
                id=_new_id("inventory-event"),
                player_item_id=player_item.id,
                # Stage 5: ссылка на MissionRun появится вместе с run-таблицами.
                mission_run_id=None,
                event_type=ENTRY_ITEM_EVENT_TYPE,
                quantity_delta=-required_quantity,
                reference_type=ENTRY_ITEM_REFERENCE_TYPE,
                reference_id=mission.id,
                metadata_json={
                    "missionId": mission.id,
                    "missionSlug": mission.slug,
                    "itemId": item_id,
                    "policyId": policy.id,
                    "policyVersion": policy.version,
                },
            )
        )

    # Явный flush: поверхность ошибок идемпотентности до commit,
    # чтобы retry-цикл submit_mission увидел IntegrityError без частичных записей.
    session.flush()


def _submit_mission_once(
    player_id: str,
    mission_id: str,
    answer: str | None = None,
    sequence: list[str] | None = None,
) -> dict:
    """Проверить попытку, завершить миссию и атомарно выдать награды."""
    with SessionLocal.begin() as session:
        _ensure_player(session, player_id)

        mission = session.scalar(
            select(Mission).where(
                Mission.id == mission_id,
                Mission.status == "published",
            )
        )

        if mission is None:
            raise MissionEngineError(404, "Опубликованная миссия не найдена.")

        if mission.mission_type == "team":
            raise MissionEngineError(
                409,
                "Team Mission требует отдельного geo/team runtime API.",
            )

        progress = _synchronize_player_missions(session, player_id)
        player_mission = progress[mission.id]

        if player_mission.status == "cancelled":
            raise MissionEngineError(
                409,
                "Миссия отменена администратором.",
            )

        if player_mission.status == "locked":
            raise MissionEngineError(
                403,
                "Миссия заблокирована: сначала завершите обязательные задания.",
            )

        if player_mission.status == "completed":
            return {
                "accepted": True,
                "alreadyCompleted": True,
                "missionId": mission.id,
                "missionStatus": "completed",
                "awarded": {
                    "root": 0,
                    "items": [],
                    "storyNodeIds": [],
                },
                "bootstrap": _build_bootstrap(session, player_id),
            }

        attempt_count_before = player_mission.attempt_count
        player_mission.attempt_count += 1

        if player_mission.started_at is None:
            player_mission.started_at = _utcnow()

        player_mission.status = "in_progress"

        # Шаг 4.1: списание ROOT-взноса и расходуемых ключей при взятии миссии.
        # До валидации ответа: «вход» оплачивается независимо от исхода попытки.
        # Любая нехватка ресурсов/недоступный ключ → 409 и полный откат.
        _consume_entry_resources(session, player_id, mission, player_mission)

        if not _validate_submission(mission, answer, sequence):
            # Шаг 4.3a: первый неверный ответ → персональный fallback-entitlement.
            # attempt_count_before == 0 => это первая попытка (V1 semantics,
            # docs/fallback-shop-contract.md): eligible независимо от paid policy,
            # работает и для бесплатных миссий. Функция идемпотентна, вызываем
            # только после успешного _consume_entry_resources и только при отказе.
            create_first_failure_entitlement(
                session,
                player_id,
                mission.id,
                attempt_count_before=attempt_count_before,
            )
            return {
                "accepted": False,
                "alreadyCompleted": False,
                "missionId": mission.id,
                "missionStatus": "in_progress",
                "message": (
                    "Ответ не принят. Проверьте структуру пакета и попробуйте снова."
                ),
                "awarded": {
                    "root": 0,
                    "items": [],
                    "storyNodeIds": [],
                },
                "bootstrap": _build_bootstrap(session, player_id),
            }

        player_mission.status = "completed"
        player_mission.completed_at = _utcnow()

        awarded = _award_mission_rewards(session, player_id, mission)

        return {
            "accepted": True,
            "alreadyCompleted": False,
            "missionId": mission.id,
            "missionStatus": "completed",
            "awarded": awarded,
            "bootstrap": _build_bootstrap(session, player_id),
        }



def submit_mission(
    player_id: str,
    mission_id: str,
    answer: str | None = None,
    sequence: list[str] | None = None,
) -> dict:
    """
    Идемпотентно отправить миссию.

    При двух почти одновременных submit SQLite/PostgreSQL могут сообщить
    о конфликте уникальности или временной блокировке записи. Повторяем всю
    короткую транзакцию: после commit первого запроса второй увидит completed
    и вернёт alreadyCompleted=True без повторной награды.
    """
    max_attempts = 3
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return _submit_mission_once(
                player_id=player_id,
                mission_id=mission_id,
                answer=answer,
                sequence=sequence,
            )
        except (IntegrityError, OperationalError) as error:
            last_error = error

            if attempt == max_attempts - 1:
                break

            # 50 мс, затем 100 мс — достаточно для короткой игровой записи.
            time.sleep(0.05 * (2**attempt))

    raise MissionEngineError(
        409,
        "Запрос конкурирует с другой операцией. Повторите отправку миссии.",
    ) from last_error
