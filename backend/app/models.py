from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


from app.geo_team_runtime_models import (  # noqa: F401
    InventoryEvent,
    InventoryReservation,
    LocationProof,
    MissionAttempt,
    MissionRun,
    MissionRuntimePolicy,
    MissionSettlement,
    PlayerFallbackEntitlement,
    TeamSession,
    TeamSessionMember,
    WalletReservation,
)


class TimestampMixin:
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


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    season_id: Mapped[str] = mapped_column(
        ForeignKey("seasons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StoryNode(TimestampMixin, Base):
    __tablename__ = "story_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    presentation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="archive",
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Segment(TimestampMixin, Base):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)

    mission_links: Mapped[list["SegmentMission"]] = relationship(
        "SegmentMission",
        back_populates="segment",
        cascade="save-update, merge",
        passive_deletes=False,
    )


class Mission(TimestampMixin, Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    story_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Геозона-шаблон: сервер сгенерирует координаты при взятии миссии (Sprint 8.2).
    # Привязка опциональна для draft, но обязательна для published (правило в admin_missions).
    geo_zone_id: Mapped[str | None] = mapped_column(
        ForeignKey("geo_zones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # AR-объект: показывается игроку после сканирования QR (Sprint 8.6+).
    # Привязка опциональна для draft, обязательна для published.
    ar_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("ar_objects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    mission_type: Mapped[str] = mapped_column(String(64), nullable=False)
    mission_category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="solo",
        index=True,
        comment=("Категория участия: solo / team / race / co-op. "
                 "Определяет флоу прохождения."),
    )
    mission_layer: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="solo",
        index=True,
        comment=(
            "Слой миссии: story (сюжетная), team (командная), solo "
            "(индивидуальная). Используется для UI-группировки, цветов "
            "и правила '≤1 активной на слой для игрока'."
        ),
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Параметры отображения механики: вопрос, инструкция, блоки и т.п.
    # Правильные ответы и чувствительные данные не должны попадать в API игрока.
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Закрытые параметры проверки: ответы, правильный порядок, QR-secret.
    # В будущем они будут исключаться из всех player API-схем.
    validation_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Лимит времени на выполнение задания в секундах.
    # None = без ограничения. Устанавливается админом в CMS.
    execution_time_limit_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )

    # Время перезарядки в секундах до повторного взятия миссии после завершения/провала.
    # 0 = одноразовая (после завершения/провала больше не появляется).
    # >0 = через N секунд снова доступна.
    reentry_cooldown_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # Цепочка разблокировки: эта миссия станет available только после того,
    # как указанная миссия перейдёт в completed. None = нет зависимости.
    unlock_after_mission_id: Mapped[str | None] = mapped_column(
        ForeignKey("missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "mission_category IN ('solo', 'team', 'race', 'co-op')",
            name="ck_missions_mission_category",
        ),
        CheckConstraint(
            "mission_layer IN ('story', 'team', 'solo')",
            name="ck_missions_mission_layer",
        ),
        CheckConstraint(
            "execution_time_limit_seconds IS NULL OR execution_time_limit_seconds > 0",
            name="ck_missions_execution_time_limit_positive",
        ),
        CheckConstraint(
            "reentry_cooldown_seconds >= 0",
            name="ck_missions_reentry_cooldown_nonnegative",
        ),
    )

    segment_links: Mapped[list["SegmentMission"]] = relationship(
        "SegmentMission",
        back_populates="mission",
        cascade="save-update, merge",
        passive_deletes=False,
    )


class SegmentMission(TimestampMixin, Base):
    __tablename__ = "segments_missions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("segments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    archived_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            (
                "(status = 'active' "
                "AND archived_at IS NULL "
                "AND archived_by_admin_id IS NULL) "
                "OR "
                "(status = 'archived' AND archived_at IS NOT NULL)"
            ),
            name="ck_segments_missions_lifecycle",
        ),
        Index(
            "ix_segments_missions_active_segment_sort",
            "segment_id",
            "sort_order",
            "id",
        ),
        Index(
            "uq_segments_missions_active_pair",
            "segment_id",
            "mission_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    segment: Mapped["Segment"] = relationship(
        "Segment",
        back_populates="mission_links",
    )
    mission: Mapped["Mission"] = relationship(
        "Mission",
        back_populates="segment_links",
    )


class MissionRequirement(TimestampMixin, Base):
    __tablename__ = "mission_requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    requirement_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Item(TimestampMixin, Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="archive")
    rarity: Mapped[str] = mapped_column(String(32), nullable=False, default="common")
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )


class KeyRules(TimestampMixin, Base):
    """CMS-правила ключа доступа: одна запись на один Item (item_id UNIQUE).

    Ключ — это обычный Item из items, а KeyRules задаёт игровые правила его
    использования (расход из инвентаря, размер стопки, запрет передачи /
    продажи / обмена). Механики читают правила из CMS, а не из хардкода.
    """

    __tablename__ = "key_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_consumable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    stack_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    transfer_forbidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    sale_forbidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    trade_forbidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            name="uq_key_rules_item_id",
        ),
        CheckConstraint(
            "stack_limit >= 1",
            name="ck_key_rules_stack_limit_min",
        ),
    )


class MissionReward(TimestampMixin, Base):
    __tablename__ = "mission_rewards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reward_type: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    story_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reward_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RewardPool(TimestampMixin, Base):
    """CMS-пул случайных наград: независимая сущность.

    На шаге 3.4 пул не привязан к Mission/MissionReward — связь появится
    отдельным шагом. Возможные награды и их веса хранятся в
    RewardPoolEntry. Все игровые правила читаются из CMS, не из хардкода.
    """

    __tablename__ = "reward_pools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RewardPoolEntry(TimestampMixin, Base):
    """Одна строка пула случайных наград.

    reward_type/amount/item_id/story_node_id/reward_value повторяют форму
    MissionReward; weight задаёт относительный шанс entry. Суммы весов
    валидируются позже, на шаге админ-роутера.
    """

    __tablename__ = "reward_pool_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pool_id: Mapped[str] = mapped_column(
        ForeignKey("reward_pools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reward_type: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    story_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reward_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "weight > 0",
            name="ck_reward_pool_entries_weight_positive",
        ),
    )


class GeoZone(TimestampMixin, Base):
    """CMS-справочник геозон для миссий и AR-объектов.

    Внешние ссылки на зону идут по ``slug`` строкой без FK
    (validationConfig.geo.zoneId, LocationProof.zone_id).
    Координаты хранятся как Float/JSON: PostGIS не используется.
    Cross-field-валидация по типу зоны (radius требует radius_meters,
    polygon — polygon_coordinates) выполняется в Python-контракте, не в БД.

    GeoZone — шаблон: search_radius_meters задаёт область поиска, в которой
    сервер генерирует конкретное место зоны при взятии миссии.
    """

    __tablename__ = "geo_zones"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    zone_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="radius",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Центр зоны для radius / poi / event.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_meters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Радиус поиска: в этом радиусе сервер генерирует место зоны при взятии миссии.
    # Игрок видит этот радиус как область поиска. radius_meters — размер самой зоны.
    search_radius_meters: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Правила размещения: {'avoid_buildings': true, 'avoid_water': true, 'avoid_roads': true, 'avoid_private': true}.
    # Используется сервером при генерации точки зоны в Спринте 8.2.
    location_constraints: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict,
    )

    # Контур полигона: [[lat, lon], ...], минимум 3 точки.
    polygon_coordinates: Mapped[list | None] = mapped_column(
        JSON, nullable=True, default=list
    )

    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_location_accuracy_meters: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    minimum_presence_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    __table_args__ = (
        CheckConstraint(
            "zone_type IN ('radius', 'polygon', 'poi', 'event')",
            name="ck_geo_zones_zone_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_geo_zones_status",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_geo_zones_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_geo_zones_longitude_range",
        ),
        CheckConstraint(
            "radius_meters IS NULL OR radius_meters > 0",
            name="ck_geo_zones_radius_positive",
        ),
        CheckConstraint(
            "search_radius_meters IS NULL OR search_radius_meters > 0",
            name="ck_geo_zones_search_radius_positive",
        ),
        CheckConstraint(
            "max_location_accuracy_meters IS NULL OR max_location_accuracy_meters >= 0",
            name="ck_geo_zones_accuracy_nonnegative",
        ),
        CheckConstraint(
            "minimum_presence_seconds >= 0",
            name="ck_geo_zones_presence_nonnegative",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at",
            name="ck_geo_zones_time_order",
        ),
    )


class ARObject(TimestampMixin, Base):
    """CMS-справочник AR-объектов, привязанных к геозонам.

    Контур roadmap 7.2: тип объекта, ассет, место появления, время
    доступности, сценарий обнаружения, мини-игра, инструкция,
    конфигурация валидации (и награды — отдельным шагом).
    GeoZone-связь — FK (CMS -> CMS) с ondelete=RESTRICT; runtime-ссылки
    на зоны остаются slug-строками без FK (LocationProof.zone_id,
    validationConfig.geo.zoneId).
    """

    __tablename__ = "ar_objects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    geo_zone_id: Mapped[str] = mapped_column(
        ForeignKey("geo_zones.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    asset_mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scene_preset: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Размер AR-объекта в реальном мире (метры). 1.0 = 1 метр.
    # Модель нормализуется так, что 1 unit = 1 метр; scale_meters — множитель.
    scale_meters: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0,
    )
    # Ориентация: 'free' — вращается, 'upright' — стоит, 'flat' — лежит плашмя.
    orientation: Mapped[str] = mapped_column(
        String(32), nullable=False, default="free",
    )

    discovery_scenario: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    minigame_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    instruction_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Server-only: ответы, QR-secret, правила проверки. Не попадает в player API.
    validation_config: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_ar_objects_status",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at",
            name="ck_ar_objects_time_order",
        ),
        CheckConstraint(
            "scale_meters > 0 AND scale_meters <= 10",
            name="ck_ar_objects_scale_range",
        ),
        CheckConstraint(
            "orientation IN ('free', 'upright', 'flat')",
            name="ck_ar_objects_orientation",
        ),
        Index(
            "ix_ar_objects_geo_zone_status",
            "geo_zone_id",
            "status",
        ),
    )


class GamePlayer(TimestampMixin, Base):
    __tablename__ = "game_players"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="demo",
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Telegram user.id is stored in external_id for auth_provider="telegram".
    # Username is a mutable convenience address for UI/search, never identity.
    telegram_username: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    telegram_username_normalized: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    telegram_first_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    telegram_last_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    telegram_photo_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
    )

    __table_args__ = (
        UniqueConstraint(
            "auth_provider",
            "external_id",
            name="uq_game_players_provider_external_id",
        ),
        # SQLite already treats NULL values as distinct in unique indexes.
        # PostgreSQL additionally uses this predicate for the same contract.
        Index(
            "uq_game_players_telegram_username_normalized",
            "telegram_username_normalized",
            unique=True,
            postgresql_where=text("telegram_username_normalized IS NOT NULL"),
        ),
    )


class PlayerRestriction(TimestampMixin, Base):
    """Ограничения игрока (шаг 5.1).

    PlayerRestriction — источник истины о гранулярных ограничениях
    (chat/transfer/team/mission/payment/withdrawal, suspended, blocked).
    GamePlayer.status остаётся кэшем агрегата для быстрого auth-гейтинга
    (не-active = вход запрещён), синхронизация — через domain-executor
    в шагах 5.4+. Физическое удаление запрещено: lifecycle active →
    expired (lazy по expires_at) или revoked (админом).
    """

    __tablename__ = "player_restrictions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    restriction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_id: Mapped[str] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    approval_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_approval_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revoked_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "restriction_type IN ('chat_restricted', 'transfer_restricted', "
            "'team_restricted', 'mission_restricted', 'payment_restricted', "
            "'withdrawal_restricted', 'suspended', 'blocked')",
            name="ck_player_restrictions_type",
        ),
        CheckConstraint(
            "status IN ('active', 'expired', 'revoked')",
            name="ck_player_restrictions_status",
        ),
        CheckConstraint(
            "expires_at IS NULL OR starts_at IS NULL OR expires_at >= starts_at",
            name="ck_player_restrictions_time_order",
        ),
        Index(
            "ix_player_restrictions_player_type",
            "player_id",
            "restriction_type",
        ),
        Index(
            "uq_player_restrictions_active_per_type",
            "player_id",
            "restriction_type",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class Team(TimestampMixin, Base):
    """Команда игроков (шаг 6.1).

    Постоянная сущность (в отличие от TeamSession — временной runtime-
    сборки под конкретную командную миссию из этапа 3). Игрок состоит
    максимум в одной активной команде — это ограничение уровня сервиса
    (6.4), не модели.

    Физическое удаление запрещено: lifecycle active → disbanded.
    leader_id — fast-pointer на текущего лидера; инвариант
    "leader ∈ members" держит сервис 6.4; после 6.2 role='leader'
    в TeamMember станет источником истины.

    Имя команды НЕ уникально: игроки не должны искать «свободное»
    имя. Адресация — по id (String(64)), FK — по id.
    Лимиты (max_members) могут быть NULL (без лимита); значения
    по умолчанию — из system settings, не хардкод (CMS-first).
    """

    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    emblem_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    leader_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )
    join_policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="by_request",
    )
    max_members: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disbanded')",
            name="ck_teams_status",
        ),
        CheckConstraint(
            "join_policy IN ('open', 'by_request', 'invite_only')",
            name="ck_teams_join_policy",
        ),
        CheckConstraint(
            "max_members IS NULL OR max_members >= 1",
            name="ck_teams_max_members_min",
        ),
    )


class TeamMember(TimestampMixin, Base):
    """Членство игрока в команде (шаг 6.2).

    Инвариант "игрок в одной активной команде" — сервис-уровень (6.4).
    Партиал-unique ниже страхует на уровне БД: одна active-запись
    (team_id, player_id) + одна active-запись (player_id) через два
    индекса. role: leader | member. Покинувший команду игрок остаётся
    в таблице со status='left' — история.
    """

    __tablename__ = "team_members"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("role IN ('leader', 'member')", name="ck_team_members_role"),
        CheckConstraint("status IN ('active', 'left')", name="ck_team_members_status"),
        UniqueConstraint("team_id", "player_id", name="uq_team_members_team_player"),
        Index(
            "uq_team_members_active_player",
            "player_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class TeamInvitation(TimestampMixin, Base):
    """Приглашение игрока в команду (шаг 6.2).

    Создаётся лидером/офицером. status: pending | accepted | rejected
    | expired | cancelled. Партиал-unique: одна pending на пару
    (team_id, invited_player_id).
    """

    __tablename__ = "team_invitations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invited_player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invited_by_player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'expired', 'cancelled')",
            name="ck_team_invitations_status",
        ),
        Index(
            "uq_team_invitations_pending",
            "team_id",
            "invited_player_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


class TeamJoinRequest(TimestampMixin, Base):
    """Заявка игрока на вступление в команду (шаг 6.2).

    Создаётся игроком. status: pending | accepted | rejected
    | cancelled. Одна pending на пару (team_id, player_id).
    """

    __tablename__ = "team_join_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by_player_id: Mapped[str | None] = mapped_column(
        ForeignKey("game_players.id", ondelete="SET NULL"),
        nullable=True,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'cancelled')",
            name="ck_team_join_requests_status",
        ),
        Index(
            "uq_team_join_requests_pending",
            "team_id",
            "player_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


class TeamMembershipHistory(TimestampMixin, Base):
    """Immutable-лог изменений состава команды (шаг 6.2).

    Одна запись = одно событие: joined | left | kicked | promoted
    | demoted | leadership_transferred. Записи не удаляются и не
    изменяются (immutability обеспечена логикой + индексами; триггеры
    — отдельная задача при необходимости).
    """

    __tablename__ = "team_membership_history"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_player_id: Mapped[str | None] = mapped_column(
        ForeignKey("game_players.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('joined', 'left', 'kicked', 'promoted', "
            "'demoted', 'leadership_transferred', 'disbanded')",
            name="ck_team_membership_history_event_type",
        ),
    )


class PlayerMission(TimestampMixin, Base):
    __tablename__ = "player_missions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="locked",
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Абсолютный момент времени, до которого игрок должен выполнить миссию.
    # None = без ограничения. Заполняется при первом accept:
    # started_at + Mission.execution_time_limit_seconds.
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Момент, раньше которого миссию нельзя взять повторно (после провала/завершения).
    # None = либо миссия одноразовая (не возвращается), либо ещё не была завершена.
    available_again_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "mission_id",
            name="uq_player_missions_player_mission",
        ),
    )


class PlayerItem(TimestampMixin, Base):
    __tablename__ = "player_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    obtained_from_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    obtained_from_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "item_id",
            name="uq_player_items_player_item",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_player_items_quantity_nonnegative",
        ),
    )


class Wallet(TimestampMixin, Base):
    __tablename__ = "wallets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[str] = mapped_column(
        ForeignKey("game_players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(32), nullable=False, default="ROOT")
    available_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "currency",
            name="uq_wallets_player_currency",
        ),
    )


class WalletTransaction(TimestampMixin, Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wallet_id: Mapped[str] = mapped_column(
        ForeignKey("wallets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        # Это именно unique index, чтобы соответствовать Alembic revision
        # 68c404c6ace4 и одинаково работать в SQLite/PostgreSQL.
        Index(
            "uq_wallet_transactions_wallet_reference",
            "wallet_id",
            "reference_type",
            "reference_id",
            unique=True,
        ),
    )

class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)

    # role is retained temporarily for compatibility with existing endpoints.
    # New administrative authorization uses is_super_admin + AdminUserPermission.
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    created_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deactivation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

class AdminPermission(TimestampMixin, Base):
    __tablename__ = "admin_permissions"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[object] = mapped_column(JSON, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", index=True
    )
    created_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class AdminUserPermission(TimestampMixin, Base):
    __tablename__ = "admin_user_permissions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("admin_permissions.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    execution_mode: Mapped[str] = mapped_column(
        String(64), nullable=False, default="direct"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    granted_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "admin_user_id",
            "permission_code",
            name="uq_admin_user_permissions_user_permission",
        ),
    )


class AdminApprovalRequest(TimestampMixin, Base):
    __tablename__ = "admin_approval_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    requested_by_admin_id: Mapped[str] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    required_permission_code: Mapped[str] = mapped_column(
        ForeignKey("admin_permissions.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_ip_address: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    approved_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_by_admin_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "requested_by_admin_id",
            "request_id",
            name="uq_admin_approval_requests_requester_request_id",
        ),
    )


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
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


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    permission_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    admin_username_snapshot: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    after_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    error_context_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
