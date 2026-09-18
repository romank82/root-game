from __future__ import annotations

from datetime import datetime, timezone
import time
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    GamePlayer,
    Item,
    Mission,
    MissionRequirement,
    MissionReward,
    PlayerItem,
    PlayerMission,
    StoryNode,
    Wallet,
    WalletTransaction,
)

ROOT_CURRENCY = "ROOT"


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

        if player_mission.status == "completed":
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

        progress = _synchronize_player_missions(session, player_id)
        player_mission = progress[mission.id]

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

        player_mission.attempt_count += 1

        if player_mission.started_at is None:
            player_mission.started_at = _utcnow()

        player_mission.status = "in_progress"

        if not _validate_submission(mission, answer, sequence):
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

def reset_demo_engine_progress(player_id: str) -> dict:
    """
    Сбрасывает только новый SQLAlchemy engine.
    Legacy tables players/completed_rewards не затрагиваются.
    """
    with SessionLocal.begin() as session:
        _ensure_player(session, player_id)

        session.query(PlayerMission).filter(
            PlayerMission.player_id == player_id
        ).delete(synchronize_session=False)

        session.query(PlayerItem).filter(
            PlayerItem.player_id == player_id
        ).delete(synchronize_session=False)

        wallet = _get_or_create_root_wallet(session, player_id)

        session.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id
        ).delete(synchronize_session=False)

        wallet.available_balance = 0
        wallet.locked_balance = 0

        return _build_bootstrap(session, player_id)
