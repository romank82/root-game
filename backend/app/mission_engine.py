from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.datetime_utils import ensure_utc
from app.db import SessionLocal
from app.fallback_shop import (
    create_first_failure_entitlements,
    is_key_reserved_for_player,
)
from app.geo_country import resolve_country_or_none
from app.geo_spawn import generate_spawn_point
from app.player_restrictions_engine import recompute_player_status
from app.qr_service import generate_qr_payload, get_qr_ttl_seconds
from app.runtime_policy_contract import scaled_attempt_multipliers
from app.models import (
    GamePlayer,
    GeoZone,
    InventoryEvent,
    Item,
    KeyRules,
    Mission,
    MissionRequirement,
    MissionReward,
    MissionRuntimePolicy,
    MinigameProfile,
    PlayerItem,
    PlayerMission,
    Segment,
    StoryNode,
    Wallet,
    WalletTransaction,
)

from app.minigame_handlers import CIPHER_ALPHABET, get_handler

ROOT_CURRENCY = "ROOT"

# Reference-типы входа в миссию (шаг 4.1). Значения — по контракту ledger:
# уникальные ключи идемпотентности = (wallet_id, reference_type, reference_id)
# и (player_item_id, event_type, reference_type, reference_id).
ENTRY_DEBIT_REFERENCE_TYPE = "mission_entry_debit"
ENTRY_ITEM_REFERENCE_TYPE = "mission_entry"
ENTRY_ITEM_EVENT_TYPE = "consumed"

# Sprint 8.17.14: алфавит cipher живёт в minigame_handlers.py (одна точка истины).
# Оставлен re-export для обратной совместимости с текущими тестами/импортами.
CIPHER_ALPHABET = CIPHER_ALPHABET  # noqa: PLW0127 (re-export)


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


def _get_root_wallet_for_update(session: Session, player_id: str) -> Wallet:
    """ROOT-кошелёк с FOR UPDATE (PostgreSQL; SQLite — no-op).

    Создаётся при отсутствии. Использовать только в мутирующих
    путях (reward, entry-debit).
    """
    wallet = session.scalar(
        select(Wallet).where(
            Wallet.player_id == player_id,
            Wallet.currency == ROOT_CURRENCY,
        ).with_for_update()
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

        now = _utcnow()

        # Терминальные статусы: cancelled — admin-only terminal, синхронизация
        # не имеет права «реактивировать» отмену.
        if player_mission.status == "cancelled":
            continue

        if player_mission.status == "completed":
            # Sprint 8.14 (шаг 5): after_terminal для solo. Читаем
            # repeatability_policy из published runtime policy.
            policy = _get_published_runtime_policy(session, mission.id)
            if policy is None:
                continue  # legacy без policy — остаётся completed
            if policy.repeatability_policy != "after_terminal":
                # one_time / after_failure_only — после успеха остаётся completed.
                continue
            # Условие возврата в available:
            # - если reentry_cooldown_seconds > 0: только после
            #   available_again_at (или сейчас, если не задан).
            # - если cooldown == 0: сразу available.
            if mission.reentry_cooldown_seconds > 0:
                if player_mission.available_again_at is None:
                    # Первый вход в sync после completed — ставим available_again_at.
                    player_mission.available_again_at = (
                        (player_mission.completed_at or now)
                        + timedelta(seconds=mission.reentry_cooldown_seconds)
                    )
                if ensure_utc(player_mission.available_again_at) > now:
                    continue  # ещё в cooldown
            # Cooldown прошёл (или его нет) — переводим в available.
            player_mission.status = "available"
            player_mission.started_at = None
            player_mission.completed_at = None
            player_mission.available_again_at = None
            player_mission.attempt_count = 0
            player_mission.progress = {}
            # entry_count и successful_completions НЕ сбрасываем —
            # они накопительные (для reference_id).
            continue

        # Sprint 8.14 (шаг 7): инвариант status ↔ attempt_count.
        # Если миссия в in_progress, но attempt_count >= max_attempts
        # (из published policy) — переводим в expired (защита от рассинхрона).
        if player_mission.status == "in_progress":
            policy = _get_published_runtime_policy(session, mission.id)
            if policy is not None and player_mission.attempt_count >= policy.max_attempts:
                player_mission.status = "expired"
                if mission.reentry_cooldown_seconds > 0:
                    player_mission.available_again_at = (
                        now + timedelta(seconds=mission.reentry_cooldown_seconds)
                    )
                else:
                    player_mission.available_again_at = None
                player_mission.deadline_at = None
                continue

        # Авто-expire: если deadline истёк, перевести в 'expired'.
        # Если у миссии есть cooldown > 0 — заполняем available_again_at.
        if (
            player_mission.status == "in_progress"
            and player_mission.deadline_at is not None
            and ensure_utc(player_mission.deadline_at) < now
        ):
            player_mission.status = "expired"
            if mission.reentry_cooldown_seconds and mission.reentry_cooldown_seconds > 0:
                player_mission.available_again_at = now + timedelta(
                    seconds=mission.reentry_cooldown_seconds,
                )
            player_mission.deadline_at = None

        # Sprint 8.15 (fix): expired + cooldown, консистентно с completed-веткой.
        # - one_time → остаётся expired (архив).
        # - after_terminal + cooldown=0 → immediately available.
        # - after_terminal + cooldown>0 → wait cooldown → available.
        if player_mission.status == "expired":
            # Policy check (как в completed-ветке выше).
            policy = _get_published_runtime_policy(session, mission.id)
            if policy is None:
                continue  # legacy без policy — остаётся expired (как сейчас)
            if policy.repeatability_policy != "after_terminal":
                continue  # one_time / after_failure_only — остаётся expired (архив)
            # after_terminal: проверяем cooldown.
            if player_mission.available_again_at is not None:
                if ensure_utc(player_mission.available_again_at) > now:
                    continue  # ещё в cooldown
                # cooldown истёк → возврат в available.
            # available_again_at is None → cooldown=0 → immediately available.
            player_mission.status = "available"
            player_mission.available_again_at = None
            player_mission.attempt_count = 0
            player_mission.started_at = None
            player_mission.completed_at = None
            player_mission.progress = {}
            continue

        # Expired-миссия (на cooldown или одноразовая) — не пересчитываем через
        # requirements. Иначе при изменении требований админом она бы ушла в
        # 'locked' и потеряла cooldown-трекинг.
        if player_mission.status == "expired":
            continue

        # Цепочка разблокировки: если задан unlock_after_mission_id и его
        # PlayerMission ещё не в completed — миссия locked (независимо от
        # MissionRequirement).
        unlock_ok = True
        if mission.unlock_after_mission_id:
            unlock_ok = mission.unlock_after_mission_id in completed

        if unlock_ok and _requirements_met(mission.id, requirements_by_mission, completed):
            if player_mission.status == "locked":
                player_mission.status = "available"
        else:
            player_mission.status = "locked"

    session.flush()
    return progress


def _load_mission_for_accept(session: Session, mission_id: str) -> Mission:
    """Загрузить миссию и проверить, что она published и solo-подобная."""
    mission = session.get(Mission, mission_id)
    if mission is None or mission.status != "published":
        raise MissionEngineError(
            404,
            "Миссия не найдена или не опубликована.",
        )
    if mission.mission_type == "team":
        raise MissionEngineError(
            409,
            "Командные миссии берутся через отдельный API.",
        )
    if mission.geo_zone_id is None:
        raise MissionEngineError(
            422,
            "У миссии не настроена геозона.",
        )
    return mission


def _extract_spawn_for_bootstrap(
    player_mission: PlayerMission,
) -> dict[str, Any] | None:
    """
    Возвращает spawn-координаты для bootstrap, если они есть и миссия in_progress.

    Для draft/available/completed/cancelled — None (spawn не нужен).
    Формат ответа — camelCase, как в _serialize_accept_response.
    """
    if player_mission.status != "in_progress":
        return None
    progress = player_mission.progress or {}
    spawn_record = progress.get("spawn")
    if not isinstance(spawn_record, dict):
        return None
    try:
        return {
            "latitude": spawn_record["latitude"],
            "longitude": spawn_record["longitude"],
            "searchRadiusMeters": spawn_record["search_radius_m"],
            "zoneRadiusMeters": spawn_record.get("zone_radius_m"),
            "arObjectId": spawn_record.get("ar_object_id"),
            "generatedFromLat": spawn_record.get("generated_from_lat"),
            "generatedFromLng": spawn_record.get("generated_from_lng"),
            "generatedAt": spawn_record["generated_at"],
        }
    except KeyError:
        # Битые данные в progress — не роняем bootstrap
        return None


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

    # Sprint 8.14 (ui): лимит попыток для UI-счётчика. Источник — единственная
    # published MissionRuntimePolicy миссии; для legacy-миссий без policy — None.
    # Частичный unique index гарантирует не более одной published policy на
    # миссию, поэтому scalar-чтение по одной на миссию безопасно.
    max_attempts_by_mission: dict[str, int | None] = {}
    for mission in missions:
        policy = _get_published_runtime_policy(session, mission.id)
        max_attempts_by_mission[mission.id] = (
            policy.max_attempts if policy is not None else None
        )

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
                "missionLayer": mission.mission_layer,
                "title": mission.title,
                "description": mission.description,
                "content": mission.content,
                "geoZoneId": mission.geo_zone_id,
                "arObjectId": mission.ar_object_id,
                "spawn": _extract_spawn_for_bootstrap(progress[mission.id]),
                "cipherSession": _serialize_cipher_session_for_bootstrap(
                    mission,
                    progress[mission.id],
                ),
                "status": progress[mission.id].status,
                "attemptCount": progress[mission.id].attempt_count,
                "maxAttempts": max_attempts_by_mission[mission.id],
                "startedAt": (
                    ensure_utc(progress[mission.id].started_at).isoformat()
                    if progress[mission.id].started_at
                    else None
                ),
                "completedAt": (
                    ensure_utc(progress[mission.id].completed_at).isoformat()
                    if progress[mission.id].completed_at
                    else None
                ),
                "executionTimeLimitSeconds": mission.execution_time_limit_seconds,
                "deadlineAt": (
                    ensure_utc(progress[mission.id].deadline_at).isoformat()
                    if progress[mission.id].deadline_at
                    else None
                ),
                "availableAgainAt": (
                    ensure_utc(progress[mission.id].available_again_at).isoformat()
                    if progress[mission.id].available_again_at
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


def _serialize_cipher_session_for_bootstrap(
    mission: Mission,
    player_mission: PlayerMission,
) -> dict | None:
    """Sprint 8.17: публичные барабаны и правильный код для cipher-игры.

    correctCode отдаётся намеренно: cipher — игра на внимательность и
    скорость, а не на разгадку (docs/minigame-cipher.md, раздел 3) — код
    показывается игроку на экране. Проверка ответа при submit всё равно
    выполняется на сервере по progress.cipher_session.
    """
    if mission.mission_type != "cipher":
        return None
    session_data = (player_mission.progress or {}).get("cipher_session")
    if not isinstance(session_data, dict):
        return None
    drums = session_data.get("drums")
    correct_code = session_data.get("correct_code")
    if not isinstance(drums, list) or not isinstance(correct_code, list):
        return None
    return {
        "drums": drums,
        "correctCode": correct_code,
        # 8.17-timer: лимит времени на попытку (profile.settings.timeLimitSeconds,
        # прокинут через generate_session) доезжает до фронта.
        "timeLimitSeconds": session_data.get("timeLimitSeconds"),
    }


def _validate_submission(
    mission: Mission,
    answer: str | None,
    sequence: list[str] | None,
    player_mission: PlayerMission | None = None,
) -> bool:
    """
    Проверяет закрытую часть ответа исключительно на сервере.

    Для обычных валидаторов источник истины — mission.validation_config
    (правила из CMS). Для cipher_match (Sprint 8.17, шаг 6) правильный код
    генерируется при accept и хранится в progress.cipher_session;
    validation_config.correctCombination больше не используется.
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

    if validator == "cipher_match":
        handler = get_handler("cipher")
        if handler is None:
            return False
        session_data = None
        if player_mission is not None:
            session_data = (player_mission.progress or {}).get("cipher_session")
        return handler.validate_submission(session_data=session_data, sequence=sequence)

    return False


def _award_mission_rewards(
    session: Session,
    player_id: str,
    mission: Mission,
    *,
    reference_id: str | None = None,
    mission_run_id: str | None = None,
    attempt_number: int | None = None,
    attempt_count_before: int | None = None,
) -> dict:
    """
    Выдаёт награды в той же транзакции, что и completion миссии.

    ROOT защищён на уровне БД уникальным индексом:
    wallet_id + reference_type + reference_id.

    reference_id — чем помечаем проводку: для solo это миссия
    (mission.id), для team — сессия (team_session.id), чтобы одну
    командную миссию можно было награждать в каждой новой сессии.
    По умолчанию mission.id (solo, поведение не меняется).

    mission_run_id — линк на MissionRun (для team), для solo None;
    при непустом значении попадает в metadata_json credit-проводки.

    attempt_number — 1-базовый номер попытки в текущем проходе
    (None для team/admin-флоу). Задаёт per-attempt множитель ROOT-награды
    по attemptMultipliers опубликованной runtime-policy миссии
    (Sprint 8.14, шаг 4). При None/без policy награда не масштабируется.
    Значение и выбранный factor фиксируются в metadata_json проводки.

    attempt_count_before — число попыток ДО текущего submit (0 — успех
    с первой попытки захода). Используется per-run guard'ом fallback-ключа:
    ключ выдаётся наградой, только если в ЭТОМ заходе провала не было.
    """
    if reference_id is None:
        reference_id = mission.id
    rewards = session.scalars(
        select(MissionReward)
        .where(MissionReward.mission_id == mission.id)
        .order_by(MissionReward.sort_order, MissionReward.id)
    ).all()

    wallet = _get_root_wallet_for_update(session, player_id)
    awarded_root = 0
    awarded_items: list[dict] = []
    unlocked_story_node_ids: list[str] = []

    # Sprint 8.14 (шаг 4): per-attempt reward multiplier. Множитель выбирается
    # по номеру попытки в текущем проходе (1-базовый): attempt 1 → 1.0,
    # attempt 2 → 0.5, attempt 3 → 0.25. Источник — attemptMultipliers
    # опубликованной runtime-policy миссии (policy собирается на шаге 4 из
    # System Settings missions.default_attempt_reward_multipliers).
    # Без attempt_number / policy / multipliers награда не масштабируется.
    # MULTIPLIER_SCALE = 1_000_000 (runtime_policy_contract, не экспортируется).
    factor = 1_000_000
    if attempt_number is not None and attempt_number >= 1:
        policy = _get_published_runtime_policy(session, mission.id)
        if policy is not None:
            reward_policy = policy.reward_policy_json or {}
            multipliers_raw = reward_policy.get("attemptMultipliers")
            if multipliers_raw:
                try:
                    scaled = scaled_attempt_multipliers(reward_policy)
                    index = attempt_number - 1
                    if 0 <= index < len(scaled):
                        factor = scaled[index]
                except Exception:
                    factor = 1_000_000

    for reward in rewards:
        if reward.reward_type == "currency":
            currency = reward.reward_value.get("currency")

            if currency != ROOT_CURRENCY or not reward.amount or reward.amount <= 0:
                continue

            existing_transaction = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id == reference_id,
                )
            )

            if existing_transaction is not None:
                continue

            # Sprint 8.14 (шаг 4): ROOT-награда масштабируется множителем
            # попытки (factor — целый, 1_000_000 == 1.0). Дробные доли
            # округляются вниз; нулевая/отрицательная сумма не проводит запись.
            base_amount = reward.amount
            scaled_amount = base_amount * factor // 1_000_000
            if scaled_amount <= 0:
                continue

            wallet.available_balance += scaled_amount
            awarded_root += scaled_amount

            metadata_json: dict = {
                "missionId": mission.id,
                "missionSlug": mission.slug,
                "rewardId": reward.id,
            }
            if mission_run_id is not None:
                metadata_json["missionRunId"] = mission_run_id
            # Сольная награда: фиксируем номер попытки и применённый
            # множитель. Для team/admin (attempt_number=None) ключи не пишем,
            # чтобы не менять форму их metadata_json.
            if attempt_number is not None:
                metadata_json["attemptNumber"] = attempt_number
                metadata_json["multiplierScale"] = factor

            session.add(
                WalletTransaction(
                    id=_new_id("wallet-transaction"),
                    wallet_id=wallet.id,
                    amount=scaled_amount,
                    balance_after=wallet.available_balance,
                    transaction_type="credit",
                    reason=f"Mission reward: {mission.slug}",
                    reference_type="mission_reward",
                    reference_id=reference_id,
                    metadata_json=metadata_json,
                )
            )

        elif reward.reward_type == "item" and reward.item_id:
            item = session.get(Item, reward.item_id)

            if item is None:
                raise MissionEngineError(
                    500,
                    "Награда миссии ссылается на отсутствующий предмет.",
                )

            # Sprint 8.14/8.16 (fix): если это fallback-ключ миссии (published
            # item с KeyRules) и он уже зарезервирован в магазине на ЭТУ
            # миссию — НЕ выдавать наградой. Per-key XOR per-run: каждый ключ
            # миссии либо награда (успех с 1-й попытки), либо магазин (в
            # текущем заходе первая попытка провалена).
            # Sprint 8.16: у миссии может быть несколько ключей-наград —
            # проверяем резервацию конкретного item, а не только первого.
            # attempt_count_before > 0 ⟺ в текущем заходе уже был провал.
            failed_before_in_run = (
                attempt_count_before is not None and attempt_count_before > 0
            )
            has_key_rules = (
                session.scalar(select(KeyRules).where(KeyRules.item_id == item.id))
                is not None
            )
            if (
                failed_before_in_run
                and has_key_rules
                and is_key_reserved_for_player(
                    session,
                    player_id,
                    mission.id,
                    item_id=item.id,
                )
            ):
                continue  # ключ уже в магазине

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
                    obtained_from_id=reference_id,
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


def _apply_entry_debit(
    session: Session,
    *,
    player_id: str,
    mission: Mission,
    root_debit: int,
    requirements: list[dict],
    reference_id: str,
    mission_run_id: str | None = None,
) -> None:
    """Ядро списания entry-ресурсов (ROOT + расходуемые ключи).

    Источник правил — вызывающий код:
    - solo-путь: _consume_entry_resources читает policy;
    - team-путь: team_missions_service читает validation_config.economy.

    Идемпотентность:
    - ROOT: unique (wallet_id, reference_type=ENTRY_DEBIT_REFERENCE_TYPE,
      reference_id=reference_id);
    - Ключи: unique (player_item_id, event_type=ENTRY_ITEM_EVENT_TYPE,
      reference_type=ENTRY_ITEM_REFERENCE_TYPE, reference_id=reference_id).

    reference_id:
    - solo → "<player_mission.id>_entry_<entry_count>" (per-run;
      Sprint 8.14 fix: entry_count инкрементится на каждом новом accept,
      поэтому после провала/успеха повторный заход списывает entry заново)
    - team → team_session.id

    Порядок: 1) баланс ROOT, 2) наличие/количество PlayerItem,
    3) Item.status == published, 4) debit ROOT, 5) списание ключей.
    amount в WalletTransaction всегда положительный, направление задаёт
    transaction_type ("debit"). balance_after = баланс после списания.
    Любая ошибка всплывает MissionEngineError → транзакция откатывается целиком.

    policy (если есть) ищется только для audit-метаданных
    (policyId/policyVersion); правила списания приходят от вызывающего кода.
    """
    wallet = _get_root_wallet_for_update(session, player_id)

    metadata: dict = {
        "missionId": mission.id,
        "missionSlug": mission.slug,
    }
    policy = _get_published_runtime_policy(session, mission.id)
    if policy is not None:
        metadata["policyId"] = policy.id
        metadata["policyVersion"] = policy.version
    if mission_run_id is not None:
        metadata["missionRunId"] = mission_run_id

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
                WalletTransaction.reference_id == reference_id,
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
                    reference_id=reference_id,
                    metadata_json=metadata,
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
                InventoryEvent.reference_id == reference_id,
            )
        )
        if existing_event is not None:
            continue

        player_item.quantity -= required_quantity
        session.add(
            InventoryEvent(
                id=_new_id("inventory-event"),
                player_item_id=player_item.id,
                mission_run_id=mission_run_id,
                event_type=ENTRY_ITEM_EVENT_TYPE,
                quantity_delta=-required_quantity,
                reference_type=ENTRY_ITEM_REFERENCE_TYPE,
                reference_id=reference_id,
                metadata_json={
                    **metadata,
                    "itemId": item_id,
                },
            )
        )

    # Явный flush: поверхность ошибок идемпотентности до commit,
    # чтобы retry-цикл submit_mission увидел IntegrityError без частичных записей.
    session.flush()


def _consume_entry_resources(
    session: Session,
    player_id: str,
    mission: Mission,
    player_mission: PlayerMission,
) -> None:
    """Solo-обёртка над _apply_entry_debit (источник — runtime policy)."""
    policy = _get_published_runtime_policy(session, mission.id)
    if policy is None:
        return

    requirements = policy.required_items_json.get("items", [])
    root_debit = policy.entry_root_atomic

    # Sprint 8.14 (fix): per-run reference_id для entry, чтобы повторный заход
    # списывал цену входа заново (unique index не блокировал). entry_count
    # инкрементится при каждом НОВОМ accept (см. _accept_mission_once) →
    # каждый заход (в т.ч. после провала → кулдауна) получает уникальный
    # "<player_mission.id>_entry_<entry_count>". Внутри одного захода retry
    # использует тот же reference_id → второй debit не создаётся.
    entry_reference_id = f"{player_mission.id}_entry_{player_mission.entry_count}"
    _apply_entry_debit(
        session,
        player_id=player_id,
        mission=mission,
        root_debit=root_debit,
        requirements=requirements,
        reference_id=entry_reference_id,
        mission_run_id=None,
    )


def _resolve_minigame_settings(session: Session, mission: Mission) -> dict:
    """Sprint 8.17.15: параметры мини-игры.

    Приоритет:
      1. Если у миссии есть minigame_profile_id и профиль published —
         берём profile.settings.
      2. Иначе (нет профиля / draft / archived) — legacy content.ui.
    Возврат: dict параметров для handler.generate_session(settings).
    """
    profile_id = getattr(mission, "minigame_profile_id", None)
    if profile_id:
        profile = session.get(MinigameProfile, profile_id)
        if profile is not None and profile.status == "published":
            return dict(profile.settings or {})
    return dict((mission.content or {}).get("ui", {}))


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

        # Sprint 8.14 (шаг 3): enforcement max_attempts.
        # Если attempt_count уже >= max_attempts из published policy —
        # новую попытку не начинаем (не инкрементим, не валидируем),
        # переводим миссию в expired и возвращаем 409.
        # policy is None (legacy-миссии без runtime policy) — проверка
        # пропускается, поведение сохраняется.
        policy = _get_published_runtime_policy(session, mission.id)
        if policy is not None and attempt_count_before >= policy.max_attempts:
            player_mission.status = "expired"
            if mission.reentry_cooldown_seconds > 0:
                player_mission.available_again_at = _utcnow() + timedelta(
                    seconds=mission.reentry_cooldown_seconds
                )
            else:
                player_mission.available_again_at = None
            # MissionEngineError откатывает транзакцию _submit_mission_once
            # целиком, поэтому expired-статус фиксируем ДО raise (иначе
            # перевод в expired не сохранился бы).
            session.commit()
            raise MissionEngineError(
                409,
                "Попытки исчерпаны. Миссия переведена в expired.",
            )

        player_mission.attempt_count += 1

        if player_mission.started_at is None:
            player_mission.started_at = _utcnow()

        player_mission.status = "in_progress"

        # Sprint 8.14 (fix): штатное списание entry перенесено в
        # _accept_mission_once («взял миссию → заплатил»). Здесь остаётся
        # только legacy-fallback: если заход НЕ открывался через accept
        # (entry_count == 0), вход списывается при submit — чтобы прямой
        # submit без accept не позволял завершить платную миссию бесплатно.
        # После accept entry_count >= 1 → повторного списания нет.
        # Любая нехватка ресурсов/недоступный ключ → 409 и полный откат.
        if player_mission.entry_count == 0:
            _consume_entry_resources(session, player_id, mission, player_mission)

        if not _validate_submission(
            mission, answer, sequence, player_mission=player_mission
        ):
            # Шаг 4.3a: первый неверный ответ → персональный fallback-entitlement.
            # attempt_count_before == 0 => это первая попытка (V1 semantics,
            # docs/fallback-shop-contract.md): eligible независимо от paid policy,
            # работает и для бесплатных миссий. Функция идемпотентна, вызываем
            # только после успешного _consume_entry_resources и только при отказе.
            create_first_failure_entitlements(
                session,
                player_id,
                mission.id,
                attempt_count_before=attempt_count_before,
            )
            # Sprint 8.17 (шаг 6): неверная попытка закрыта — следующая попытка
            # получает новый код и новые барабаны (сгенерированная при accept
            # сессия больше недействительна).
            handler = get_handler(mission.mission_type)
            if handler is not None:
                # Sprint 8.17.15: profile.settings, если есть published-профиль;
                # иначе legacy content.ui.
                settings = _resolve_minigame_settings(session, mission)
                new_session = handler.generate_session(settings)
                progress = dict(player_mission.progress or {})
                progress["cipher_session"] = new_session
                player_mission.progress = progress
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

        # Sprint 8.14 (шаг 2): per-run награда для solo.
        # Счётчик успешных проходов инкрементируется до награды, чтобы
        # reference_id включал его. Уникальный индекс (wallet_id,
        # reference_type, reference_id) гарантирует идемпотентность
        # повторного submit одной и той же попытки.
        player_mission.successful_completions += 1
        run_reference_id = f"{player_mission.id}_{player_mission.successful_completions}"

        awarded = _award_mission_rewards(
            session,
            player_id,
            mission,
            reference_id=run_reference_id,
            # Sprint 8.14 (шаг 4): attempt_count уже инкрементирован
            # (attempt_count_before + 1) — это 1-базовый номер попытки
            # в текущем проходе, по которому выбирается множитель награды.
            attempt_number=player_mission.attempt_count,
            # Sprint 8.14 (fix): per-run guard fallback-ключа — был ли
            # провал до этой успешной попытки в текущем заходе.
            attempt_count_before=attempt_count_before,
        )

        return {
            "accepted": True,
            "alreadyCompleted": False,
            "missionId": mission.id,
            "missionStatus": "completed",
            "awarded": awarded,
            "bootstrap": _build_bootstrap(session, player_id),
        }


def _accept_mission_once(
    session: Session,
    *,
    player_id: str,
    mission_id: str,
    latitude: float,
    longitude: float,
    accuracy: float | None,
) -> dict[str, Any]:
    # Валидация координат
    if not (-90.0 <= latitude <= 90.0):
        raise MissionEngineError(
            422,
            "latitude должен быть в диапазоне [-90, 90].",
        )
    if not (-180.0 <= longitude <= 180.0):
        raise MissionEngineError(
            422,
            "longitude должен быть в диапазоне [-180, 180].",
        )
    if accuracy is not None and accuracy <= 0:
        raise MissionEngineError(
            422,
            "accuracy должен быть > 0 или null.",
        )

    with session.begin():
        mission = _load_mission_for_accept(session, mission_id)
        player = _ensure_player(session, player_id)
        _synchronize_player_missions(session, player_id)

        player_mission = session.scalars(
            select(PlayerMission).where(
                PlayerMission.player_id == player_id,
                PlayerMission.mission_id == mission_id,
            )
        ).first()
        if player_mission is None:
            raise MissionEngineError(
                500,
                "Прогресс по миссии не найден.",
            )

        # Терминальные статусы
        if player_mission.status == "completed":
            raise MissionEngineError(
                409,
                "Миссия уже завершена.",
            )
        if player_mission.status == "cancelled":
            raise MissionEngineError(
                409,
                "Миссия отменена.",
            )
        if player_mission.status == "locked":
            raise MissionEngineError(
                403,
                "Миссия недоступна: не выполнены требования.",
            )

        if player_mission.status == "expired":
            # Если cooldown истёк — синхронизация уже должна была вернуть в available.
            # Если нет — значит ещё на cooldown.
            if player_mission.available_again_at is not None and ensure_utc(player_mission.available_again_at) > _utcnow():
                seconds_left = int(
                    (ensure_utc(player_mission.available_again_at) - _utcnow()).total_seconds()
                )
                minutes_left = max(1, seconds_left // 60)
                raise MissionEngineError(
                    429,
                    f"Миссия на перезарядке. Доступна через {minutes_left} мин.",
                )
            raise MissionEngineError(
                409,
                "Время на выполнение миссии истекло. Миссия больше недоступна.",
            )

        # Идемпотентность: если spawn уже есть в progress — вернуть как есть
        progress = player_mission.progress or {}
        existing_spawn = progress.get("spawn")
        if existing_spawn is not None and player_mission.status == "in_progress":
            return _serialize_accept_response(
                mission, player_mission, existing_spawn
            )

        # Sprint 8.14 (fix): entry списывается при КАЖДОМ новом заходе.
        # Инкремент entry_count делаем только при переходе из НЕ-in_progress.
        # Идемпотентный повторный accept (in_progress + spawn) уже отсечён
        # early-return выше; was_in_progress — страховка на случай
        # статуса in_progress без spawn в progress.
        was_in_progress = player_mission.status == "in_progress" and (
            progress.get("spawn") is not None
        )

        # Правило: ≤1 активной миссии на слой (story/team/solo).
        # Проверяем, нет ли у игрока другой in_progress миссии того же layer.
        conflicting = session.scalars(
            select(PlayerMission)
            .join(Mission, Mission.id == PlayerMission.mission_id)
            .where(
                PlayerMission.player_id == player_id,
                PlayerMission.status == "in_progress",
                Mission.mission_layer == mission.mission_layer,
                Mission.id != mission.id,
            )
            .limit(1)
        ).first()
        if conflicting is not None:
            conflicting_mission = session.get(Mission, conflicting.mission_id)
            layer_label = {
                "story": "сюжетного слоя",
                "team": "командного слоя",
                "solo": "индивидуального слоя",
            }.get(mission.mission_layer, mission.mission_layer)
            raise MissionEngineError(
                409,
                f"У вас уже есть активная миссия {layer_label}. "
                f"Завершите её, прежде чем брать новую.",
            )

        # Загрузить GeoZone-шаблон
        zone_template = session.get(GeoZone, mission.geo_zone_id)
        if zone_template is None or zone_template.search_radius_meters is None:
            raise MissionEngineError(
                422,
                "Шаблон геозоны не найден или не содержит search_radius_meters.",
            )

        # 10.0.5: фактическая страна игрока по координатам (geo-intel-offline).
        # Миссия уже валидна: load прошёл, статусы и конфликты проверены,
        # шаблон зоны есть — резолвим страну только для успешного accept.
        # Ручной ввод (анкета) не приоритет — country перезаписываем при
        # резолве с confidence >= 0.7; иначе оставляем как есть (без мусора).
        resolved = resolve_country_or_none(latitude, longitude)
        if resolved is not None:
            player.country = resolved

        # Сгенерировать spawn
        spawn = generate_spawn_point(
            center_latitude=latitude,
            center_longitude=longitude,
            search_radius_m=zone_template.search_radius_meters,
        )

        spawn_record = {
            "latitude": spawn.latitude,
            "longitude": spawn.longitude,
            "search_radius_m": zone_template.search_radius_meters,
            "zone_radius_m": zone_template.radius_meters,
            "ar_object_id": mission.ar_object_id,
            "generated_at": ensure_utc(_utcnow()).isoformat(),
            "generated_from_lat": latitude,
            "generated_from_lng": longitude,
        }

        progress = dict(progress)
        progress["spawn"] = spawn_record
        player_mission.progress = progress

        # Sprint 8.17 (шаг 6): cipher-игра получает при accept новый случайный
        # код и символы барабанов. Сессия хранится в progress.cipher_session:
        # при submit сервер сверяется именно с ней, а не с validation_config.
        handler = get_handler(mission.mission_type)
        if handler is not None:
            # Sprint 8.17.15: profile.settings, если есть published-профиль;
            # иначе legacy content.ui.
            settings = _resolve_minigame_settings(session, mission)
            session_data = handler.generate_session(settings)
            progress = dict(player_mission.progress or {})
            progress["cipher_session"] = session_data
            player_mission.progress = progress

        if player_mission.started_at is None:
            started = _utcnow()
            player_mission.started_at = started
            # Лимит времени: deadline_at = started + execution_time_limit_seconds.
            # None = без ограничения (не пишем deadline).
            if mission.execution_time_limit_seconds:
                player_mission.deadline_at = started + timedelta(
                    seconds=mission.execution_time_limit_seconds,
                )
        # Sprint 8.14 (fix): новый заход (НЕ идемпотентный повторный accept)
        # инкрементирует entry_count → per-run reference_id входа
        # "_entry_<entry_count>" будет уникальным для каждого взятия миссии.
        if not was_in_progress:
            player_mission.entry_count += 1

        # Sprint 8.14 (fix): штатное списание entry (ROOT-взнос + расходуемые
        # ключи) выполняется ПРИ ВЗЯТИИ миссии — «взял миссию → заплатил».
        # Идемпотентный повторный accept (in_progress + spawn) отсечён
        # early-return выше, поэтому сюда попадаем только с уже
        # инкрементированным entry_count → reference_id
        # "<player_mission.id>_entry_<entry_count>" уникален для захода.
        # Нехватка ресурсов/недоступный ключ → MissionEngineError: транзакция
        # accept откатывается целиком (spawn не сохраняется, entry_count и
        # статус миссии остаются прежними).
        _consume_entry_resources(session, player_id, mission, player_mission)

        player_mission.status = "in_progress"

        session.flush()

        return _serialize_accept_response(mission, player_mission, spawn_record)


def _serialize_accept_response(
    mission: Mission,
    player_mission: PlayerMission,
    spawn_record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "accepted": True,
        "mission": {
            "id": mission.id,
            "slug": mission.slug,
            "title": mission.title,
            "missionType": mission.mission_type,
        },
        "spawn": {
            "latitude": spawn_record["latitude"],
            "longitude": spawn_record["longitude"],
            "searchRadiusMeters": spawn_record["search_radius_m"],
            "zoneRadiusMeters": spawn_record.get("zone_radius_m"),
            "arObjectId": spawn_record.get("ar_object_id"),
            "generatedFromLat": spawn_record.get("generated_from_lat"),
            "generatedFromLng": spawn_record.get("generated_from_lng"),
            "generatedAt": spawn_record["generated_at"],
        },
        "status": player_mission.status,
        "startedAt": (
            ensure_utc(player_mission.started_at).isoformat()
            if player_mission.started_at
            else None
        ),
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


def accept_mission(
    player_id: str,
    mission_id: str,
    latitude: float,
    longitude: float,
    accuracy: float | None = None,
) -> dict[str, Any]:
    """
    Игрок берёт миссию: генерируется spawn-точка в радиусе от его GPS.

    Идемпотентно: повторный вызов для in_progress миссии возвращает
    уже существующий spawn без регенерации.
    """
    with SessionLocal() as session:
        return _accept_mission_once(
            session,
            player_id=player_id,
            mission_id=mission_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
        )


def get_mission_qr_payload(player_id: str, mission_id: str) -> dict[str, Any]:
    """
    8.6.c: подписанный QR-payload для миссии в статусе in_progress.

    Read-only: ничего не пишет в БД и не создаёт PlayerMission — QR не
    является действием игрока, а лишь материалом для отображения на грани
    AR-куба (8.6.d). Проверка подписи при скане — отдельный шаг 8.8.

    Индивидуальность гарантируется подписью: player_id и mission_id входят
    в подписанный body, поэтому чужой (или подделанный) QR не пройдёт
    verify_qr_payload. Одноразовый nonce и TTL не дают переиспользовать
    payload повторно и ограничивают время его жизни.

    Ответ: missionId, payload, hmac, expiresAt, ttlSeconds. Секреты,
    validation_config и иные server-only поля не возвращаются.
    """
    with SessionLocal() as session:
        _ensure_player(session, player_id)

        mission = session.get(Mission, mission_id)
        if mission is None or mission.status != "published":
            raise MissionEngineError(
                404,
                "Миссия не найдена или не опубликована.",
            )

        player_mission = session.scalars(
            select(PlayerMission).where(
                PlayerMission.player_id == player_id,
                PlayerMission.mission_id == mission_id,
            )
        ).first()

        # Словарь статусов повторяет accept: терминальные и «не взята» дают
        # конкретное сообщение, а не общее «нельзя».
        status = player_mission.status if player_mission is not None else None
        if status == "locked":
            raise MissionEngineError(
                403,
                "Миссия недоступна: не выполнены требования.",
            )
        if status == "completed":
            raise MissionEngineError(
                409,
                "Миссия уже завершена.",
            )
        if status == "cancelled":
            raise MissionEngineError(
                409,
                "Миссия отменена.",
            )
        if status != "in_progress":
            raise MissionEngineError(
                409,
                "Миссия не запущена: сначала возьмите миссию.",
            )

        try:
            qr = generate_qr_payload(
                player_id=player_id,
                mission_id=mission_id,
            )
        except RuntimeError as error:
            # GAME_SESSION_SECRET не настроен: это серверная проблема, а не
            # ошибка игрока (та же семантика 503, что в telegram_auth).
            raise MissionEngineError(
                503,
                "QR-подписи не настроены на сервере.",
            ) from error

        return {
            "missionId": mission_id,
            "payload": qr["payload"],
            "hmac": qr["hmac"],
            "expiresAt": qr["expiresAt"],
            "ttlSeconds": get_qr_ttl_seconds(),
        }


def process_qr_scan(
    player_id: str,
    mission_id: str,
    payload_and_hmac: str,
) -> dict[str, Any]:
    """
    Проверить отсканированный QR игрока.
    При успехе — сохранить факт сканирования в PlayerMission.progress
    и вернуть mini-game config.
    """
    from app.qr_service import split_payload_and_hmac, verify_qr_payload

    with SessionLocal() as session:
        with session.begin():
            mission = session.get(Mission, mission_id)
            if mission is None or mission.status != "published":
                raise MissionEngineError(404, "Миссия не найдена или не опубликована.")

            player_mission = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            ).first()
            if player_mission is None:
                raise MissionEngineError(404, "Прогресс по миссии не найден.")

            if player_mission.status != "in_progress":
                raise MissionEngineError(
                    409,
                    "QR можно сканировать только для миссии в статусе in_progress.",
                )

            progress = player_mission.progress or {}
            if not isinstance(progress.get("spawn"), dict):
                raise MissionEngineError(
                    409,
                    "Для этой миссии ещё не сгенерирован spawn.",
                )

            try:
                payload_b64, hmac_b64 = split_payload_and_hmac(payload_and_hmac)
            except ValueError:
                raise MissionEngineError(422, "QR-код недействителен (формат).")

            try:
                body = verify_qr_payload(
                    payload_b64=payload_b64,
                    hmac_b64=hmac_b64,
                    expected_player_id=player_id,
                    expected_mission_id=mission_id,
                )
            except ValueError as exc:
                # Не раскрываем детали игроку.
                raise MissionEngineError(422, "QR-код недействителен.") from exc

            scanned_at = _utcnow().isoformat()

            progress = dict(progress)
            progress["lastScanAt"] = scanned_at
            progress["lastScanNonce"] = body.get("nonce")
            player_mission.progress = progress
            session.flush()

            return {
                "accepted": True,
                "missionId": mission.id,
                "scannedAt": scanned_at,
                "miniGame": {
                    "missionType": mission.mission_type,
                    "content": mission.content,
                },
            }
def expire_mission(player_id: str, mission_id: str) -> dict[str, Any]:
    """
    Пометить активную миссию как просроченную (ручной expire по клику игрока).
    Если у миссии cooldown > 0 — установить available_again_at.
    """
    with SessionLocal() as session:
        with session.begin():
            mission = session.get(Mission, mission_id)
            if mission is None or mission.status != "published":
                raise MissionEngineError(404, "Миссия не найдена или не опубликована.")

            player_mission = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            ).first()
            if player_mission is None:
                raise MissionEngineError(404, "Прогресс по миссии не найден.")

            # Только для in_progress можно expire.
            if player_mission.status != "in_progress":
                # Идемпотентность: если уже expired — вернуть как есть.
                if player_mission.status == "expired":
                    return {
                        "expired": True,
                        "status": "expired",
                        "availableAgainAt": (
                            ensure_utc(player_mission.available_again_at).isoformat()
                            if player_mission.available_again_at
                            else None
                        ),
                    }
                raise MissionEngineError(
                    409,
                    f"Миссия не в статусе in_progress (текущий: {player_mission.status}).",
                )

            now = _utcnow()
            player_mission.status = "expired"
            if mission.reentry_cooldown_seconds and mission.reentry_cooldown_seconds > 0:
                player_mission.available_again_at = now + timedelta(
                    seconds=mission.reentry_cooldown_seconds,
                )
            player_mission.deadline_at = None
            session.flush()

            return {
                "expired": True,
                "status": "expired",
                "availableAgainAt": (
                    ensure_utc(player_mission.available_again_at).isoformat()
                    if player_mission.available_again_at
                    else None
                ),
            }
