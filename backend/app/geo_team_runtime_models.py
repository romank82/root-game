from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RuntimeTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LocationProof(RuntimeTimestampMixin, Base):
    """
    Server-side projection of a trusted verifier result.

    Never store raw coordinates, raw location evidence, device identifiers,
    anti-abuse payloads, or QR material in this table.
    """

    __tablename__ = "location_proofs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    verifier_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('verified', 'rejected', 'expired')",
            name="ck_location_proofs_status",
        ),
    )


class TeamSession(RuntimeTimestampMixin, Base):
    __tablename__ = "team_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    effective_config_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Sprint 8.x-2a: механика волн командной мини-игры (схема, логика — 8.x-2b+).
    # Поля append-only: валидацию статусов/границ волн делает сервис,
    # CheckConstraint намеренно не добавляем (не ломать существующие строки).
    current_wave: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    max_waves: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    wave_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="playing", server_default="playing"
    )
    wave_played_members: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    current_cipher_session: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None, server_default=None
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'collecting', 'ready_to_start', 'active', 'succeeded', 'failed', "
            "'expired', 'cancelled_before_start'"
            ")",
            name="ck_team_sessions_status",
        ),
    )


class MissionRuntimePolicy(RuntimeTimestampMixin, Base):
    """Versioned CMS policy used to create immutable solo-run snapshots."""

    __tablename__ = "mission_runtime_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entry_root_atomic: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    repeatability_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    required_items_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    challenge_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reward_policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fallback_policy_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feature_flags_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "mission_id",
            "version",
            name="uq_mission_runtime_policies_mission_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_mission_runtime_policies_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_mission_runtime_policies_version_positive",
        ),
        CheckConstraint(
            "entry_root_atomic >= 0",
            name="ck_mission_runtime_policies_entry_root_nonnegative",
        ),
        CheckConstraint(
            "max_attempts >= 1",
            name="ck_mission_runtime_policies_max_attempts_positive",
        ),
        Index(
            "uq_mission_runtime_policies_one_published_per_mission",
            "mission_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
    )


class MissionRun(RuntimeTimestampMixin, Base):
    __tablename__ = "mission_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    team_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("team_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    runtime_policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("mission_runtime_policies.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    runtime_policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    start_request_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    effective_config_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'reserved', 'accepted', 'active', 'succeeded', 'failed', "
            "'timeout', 'abandoned', 'cancelled_before_start'"
            ")",
            name="ck_mission_runs_status",
        ),
        CheckConstraint(
            "(runtime_policy_id IS NULL AND runtime_policy_version IS NULL) "
            "OR (runtime_policy_id IS NOT NULL AND runtime_policy_version IS NOT NULL)",
            name="ck_mission_runs_runtime_policy_pair",
        ),
        Index(
            "uq_mission_runs_player_start_idempotency",
            "player_id",
            "start_idempotency_key",
            unique=True,
            postgresql_where=text("start_idempotency_key IS NOT NULL"),
            sqlite_where=text("start_idempotency_key IS NOT NULL"),
        ),
    )


class TeamSessionMember(RuntimeTimestampMixin, Base):
    __tablename__ = "team_session_members"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_session_id: Mapped[str] = mapped_column(
        ForeignKey("team_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_run_id: Mapped[str] = mapped_column(
        ForeignKey("mission_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Sprint 8.x-4-final-status-1: снапшот наград игрока за эту командную
    # сессию — dict из _award_mission_rewards: {"root": int, "items": [...],
    # "storyNodeIds": [...]}. Пишется в _submit_wave_answer в той же
    # транзакции, что и награды (ветка верного ответа). None — «наград нет /
    # ещё не записано» (append-only, старые строки получают None).
    awarded_snapshot: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )

    __table_args__ = (
        UniqueConstraint(
            "team_session_id",
            "player_id",
            name="uq_team_session_members_session_player",
        ),
        UniqueConstraint(
            "mission_run_id",
            name="uq_team_session_members_mission_run",
        ),
        CheckConstraint(
            "status IN ('joined', 'ready', 'left', 'removed', 'settled')",
            name="ck_team_session_members_status",
        ),
    )


class MissionAttempt(RuntimeTimestampMixin, Base):
    __tablename__ = "mission_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_run_id: Mapped[str] = mapped_column(
        ForeignKey("mission_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    challenge_type: Mapped[str] = mapped_column(String(64), nullable=False)
    protected_challenge_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    issue_idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    submit_idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    submit_request_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "mission_run_id",
            "sequence_number",
            name="uq_mission_attempts_run_sequence",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_mission_attempts_sequence_positive",
        ),
        CheckConstraint(
            "status IN ('issued', 'submitted', 'succeeded', 'failed', 'timed_out')",
            name="ck_mission_attempts_status",
        ),
        Index(
            "uq_mission_attempts_run_issue_idempotency",
            "mission_run_id",
            "issue_idempotency_key",
            unique=True,
            postgresql_where=text("issue_idempotency_key IS NOT NULL"),
            sqlite_where=text("issue_idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_mission_attempts_submit_idempotency",
            "submit_idempotency_key",
            unique=True,
            postgresql_where=text("submit_idempotency_key IS NOT NULL"),
            sqlite_where=text("submit_idempotency_key IS NOT NULL"),
        ),
    )


class WalletReservation(RuntimeTimestampMixin, Base):
    __tablename__ = "wallet_reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_run_id: Mapped[str] = mapped_column(
        ForeignKey("mission_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "wallet_id",
            "mission_run_id",
            name="uq_wallet_reservations_wallet_run",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_wallet_reservations_amount_nonnegative",
        ),
        CheckConstraint(
            "status IN ('reserved', 'charged', 'released')",
            name="ck_wallet_reservations_status",
        ),
    )


class InventoryReservation(RuntimeTimestampMixin, Base):
    __tablename__ = "inventory_reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_item_id: Mapped[str] = mapped_column(
        ForeignKey("player_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_run_id: Mapped[str] = mapped_column(
        ForeignKey("mission_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "player_item_id",
            "mission_run_id",
            name="uq_inventory_reservations_item_run",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_inventory_reservations_quantity_positive",
        ),
        CheckConstraint(
            "status IN ('reserved', 'consumed', 'released')",
            name="ck_inventory_reservations_status",
        ),
    )


class InventoryEvent(Base):
    """Immutable inventory ledger event; guarded by DB triggers in its migration."""

    __tablename__ = "inventory_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_item_id: Mapped[str] = mapped_column(
        ForeignKey("player_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("mission_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "player_item_id",
            "event_type",
            "reference_type",
            "reference_id",
            name="uq_inventory_events_item_event_reference",
        ),
        CheckConstraint(
            "quantity_delta <> 0",
            name="ck_inventory_events_quantity_delta_nonzero",
        ),
        CheckConstraint(
            "event_type IN ('reserved', 'released', 'consumed', 'credited')",
            name="ck_inventory_events_type",
        ),
    )


class MissionSettlement(RuntimeTimestampMixin, Base):
    __tablename__ = "mission_settlements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_run_id: Mapped[str] = mapped_column(
        ForeignKey("mission_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    team_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("team_sessions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settlement_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        UniqueConstraint(
            "mission_run_id",
            name="uq_mission_settlements_mission_run",
        ),
        CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'timeout', 'abandoned')",
            name="ck_mission_settlements_outcome",
        ),
    )


class PlayerFallbackEntitlement(RuntimeTimestampMixin, Base):
    __tablename__ = "player_fallback_entitlements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Sprint 8.16: ключ-награда (item), на который выдан entitlement.
    # У миссии может быть несколько ключей — у каждого свой entitlement.
    # NULL только у legacy-строк до миграции (backfill: item_id = offer_id).
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quota_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Sprint 8.17 (шаг 8): номер захода (PlayerMission.entry_count на момент
    # выдачи/re-arm entitlement'а). Каждый новый заход многоразовой миссии —
    # новый шанс: exhausted-предложение прошлого захода переармируется, а
    # reference_id покупки привязывается к заходу ({id}:{run}:{count}),
    # сохраняя идемпотентность ledger при повторных покупках по runs.
    run_entry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "mission_id",
            "item_id",
            name="uq_pfe_player_mission_item",
        ),
        CheckConstraint(
            "quota_limit >= 0",
            name="ck_player_fallback_entitlements_quota_nonnegative",
        ),
        CheckConstraint(
            "consumed_count >= 0 AND consumed_count <= quota_limit",
            name="ck_player_fallback_entitlements_consumed_bounds",
        ),
        CheckConstraint(
            "status IN ('available', 'exhausted', 'disabled')",
            name="ck_player_fallback_entitlements_status",
        ),
    )


class TeamSessionMessage(RuntimeTimestampMixin, Base):
    """Сообщение чата командной сессии (этап 6.6-a).

    Чат живёт ТОЛЬКО в пределах TeamSession: после финала сессии
    (succeeded/failed/expired/cancelled_before_start) новые сообщения
    запрещены, старые остаются в истории (физическое удаление запрещено).
    Модерации пока нет: поле status заложено под скрытие модератором
    (visible|hidden) в 6.7.b — hidden не отдаётся в списке.
    """

    __tablename__ = "team_session_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_session_id: Mapped[str] = mapped_column(
        ForeignKey("team_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="visible")

    __table_args__ = (
        CheckConstraint(
            "status IN ('visible', 'hidden')",
            name="ck_team_session_messages_status",
        ),
        Index(
            "ix_team_session_messages_session_created",
            "team_session_id",
            "created_at",
        ),
    )

