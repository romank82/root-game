"""simplify: season -> mission (drop chapter/segment/storynode)

Sprint Structure-Simplify, шаг 2/9. Переход «Сезон -> Миссия»:
убираем иерархию Season -> Chapter -> Segment/StoryNode -> Mission.

Upgrade:
  * добавляет missions.season_id (String(64), NOT NULL после backfill из
    chapters.season_id) с FK -> seasons.id (CASCADE) и индексом;
  * удаляет missions.chapter_id и missions.story_node_id (FK + индекс);
  * удаляет story_node_id из mission_rewards и reward_pool_entries;
  * удаляет таблицы segments_missions, segments, story_nodes, chapters
    (физическое удаление тестовых данных разрешено заказчиком);
  * удаляет 6 строк каталога admin_permissions
    (segments.* / chapters.* / story_nodes.*) — ни одна не выдана.

Dialect-aware:
  * SQLite — batch_alter_table (rebuild) для снятия FK и удаления колонок
    (FK chapter_id/story_node_id в SQLite безымянные);
  * PostgreSQL — drop_constraint по имени из reflection + drop_column.

Идемпотентность: каждая операция защищена проверкой текущей схемы через
sa.inspect(op.get_bind()), чтобы повторный запуск после частичного
применения не падал.

Revision ID: a7f3c2d9e1b0
Revises: e6b4a7c9d2f1
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7f3c2d9e1b0"
down_revision: Union[str, Sequence[str], None] = "e6b4a7c9d2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEASON_ID_FK = "fk_missions_season_id"
SEASON_ID_INDEX = "ix_missions_season_id"

# Порядок удаления таблиц: ссылки (RESTRICT) и дети раньше родителей.
LEGACY_TABLES_ORDER = ("segments_missions", "segments", "story_nodes", "chapters")

# (table, column, legacy index) — колонки story_node_id, которые удаляем.
STORY_NODE_FK_TABLES = (
    ("mission_rewards", "story_node_id", "ix_mission_rewards_story_node_id"),
    ("reward_pool_entries", "story_node_id", "ix_reward_pool_entries_story_node_id"),
)

LEGACY_PERMISSION_CODES = (
    "segments.read",
    "segments.manage",
    "chapters.read",
    "chapters.manage",
    "story_nodes.read",
    "story_nodes.manage",
)

PERMISSION_ROWS = (
    ("segments.read", "Просмотр сегментов",
     "Просмотр Segment, active-связей SegmentMission и административной конфигурации сегментов."),
    ("segments.manage", "Управление сегментами",
     "Создание, изменение, публикация, снятие с публикации и архивирование Segment без физического удаления."),
    ("chapters.read", "Просмотр глав",
     "Просмотр Chapter (список, детали) во вкладке «Главы» админ-панели."),
    ("chapters.manage", "Управление главами",
     "Создание, изменение, публикация и архивация Chapter без физического удаления."),
    ("story_nodes.read", "Просмотр сюжетных узлов",
     "Просмотр StoryNode (список, детали) во вкладке «Story Nodes» админ-панели."),
    ("story_nodes.manage", "Управление сюжетными узлами",
     "Создание, изменение, публикация и архивация StoryNode без физического удаления."),
)


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _has_index(bind, table: str, columns: list[str]) -> bool:
    for index in sa.inspect(bind).get_indexes(table):
        if index.get("column_names") == columns:
            return True
    return False


def _has_index_named(bind, table: str, name: str) -> bool:
    for index in sa.inspect(bind).get_indexes(table):
        if index.get("name") == name:
            return True
    return False


def _fk_name(bind, table: str, column: str) -> str | None:
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if fk.get("constrained_columns") == [column]:
            return fk.get("name")
    return None


def _column_nullable(bind, table: str, column: str) -> bool | None:
    for col in sa.inspect(bind).get_columns(table):
        if col["name"] == column:
            return bool(col.get("nullable", True))
    return None


def _drop_column_pg(bind, table: str, column: str) -> None:
    """PostgreSQL: снимаем именованный FK (если есть) и удаляем колонку."""
    fk_name = _fk_name(bind, table, column)
    if fk_name:
        op.drop_constraint(fk_name, table, type_="foreignkey")
    op.drop_column(table, column)


def _update_missions(dialect: str, bind, season_nullable: bool, had_chapter: bool) -> None:
    """season_id -> NOT NULL + индекс + FK; снимаем chapter_id/story_node_id."""
    needs_index = not _has_index(bind, "missions", ["season_id"])
    needs_fk = _fk_name(bind, "missions", "season_id") is None

    if dialect == "sqlite":
        with op.batch_alter_table("missions") as batch_op:
            if season_nullable:
                batch_op.alter_column(
                    "season_id",
                    existing_type=sa.String(length=64),
                    nullable=False,
                )
            if needs_index:
                batch_op.create_index(SEASON_ID_INDEX, ["season_id"])
            if needs_fk:
                batch_op.create_foreign_key(
                    SEASON_ID_FK,
                    "seasons",
                    ["season_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            if had_chapter:
                if _has_index(bind, "missions", ["chapter_id"]):
                    batch_op.drop_index("ix_missions_chapter_id")
                if _has_index(bind, "missions", ["story_node_id"]):
                    batch_op.drop_index("ix_missions_story_node_id")
                batch_op.drop_column("chapter_id")
                batch_op.drop_column("story_node_id")
        return

    if season_nullable:
        op.alter_column(
            "missions",
            "season_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
    if needs_index:
        op.create_index(SEASON_ID_INDEX, "missions", ["season_id"])
    if needs_fk:
        op.create_foreign_key(
            SEASON_ID_FK,
            "missions",
            "seasons",
            ["season_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if had_chapter:
        if _has_index_named(bind, "missions", "ix_missions_chapter_id"):
            op.drop_index("ix_missions_chapter_id", table_name="missions")
        if _has_index_named(bind, "missions", "ix_missions_story_node_id"):
            op.drop_index("ix_missions_story_node_id", table_name="missions")
        _drop_column_pg(bind, "missions", "chapter_id")
        _drop_column_pg(bind, "missions", "story_node_id")


def _drop_story_node_columns(dialect: str, bind) -> None:
    tables = _tables(bind)
    for table, column, index_name in STORY_NODE_FK_TABLES:
        if table not in tables or column not in _column_names(bind, table):
            continue
        if dialect == "sqlite":
            with op.batch_alter_table(table) as batch_op:
                if _has_index(bind, table, [column]):
                    batch_op.drop_index(index_name)
                batch_op.drop_column(column)
        else:
            if _has_index_named(bind, table, index_name):
                op.drop_index(index_name, table_name=table)
            _drop_column_pg(bind, table, column)


def _drop_legacy_tables(bind) -> None:
    for table in LEGACY_TABLES_ORDER:
        if table in _tables(bind):
            op.drop_table(table)


def _delete_legacy_permissions(bind) -> None:
    if "admin_permissions" not in _tables(bind):
        return
    if "code" not in _column_names(bind, "admin_permissions"):
        return
    codes = ", ".join(f"'{code}'" for code in LEGACY_PERMISSION_CODES)
    op.execute(sa.text(f"DELETE FROM admin_permissions WHERE code IN ({codes})"))


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("This migration supports only SQLite and PostgreSQL.")

    if "missions" not in _tables(bind):
        raise RuntimeError("Table 'missions' not found; refusing to run.")

    mission_columns = _column_names(bind, "missions")
    had_chapter = "chapter_id" in mission_columns

    # 1) добавляем season_id (nullable), если ещё нет.
    if "season_id" not in mission_columns:
        op.add_column(
            "missions",
            sa.Column("season_id", sa.String(length=64), nullable=True),
        )

    # 2) backfill season_id из chapters.season_id (dialect-agnostic SQL).
    if had_chapter:
        op.execute(
            sa.text(
                "UPDATE missions SET season_id = ("
                "SELECT chapters.season_id FROM chapters "
                "WHERE chapters.id = missions.chapter_id) "
                "WHERE chapter_id IS NOT NULL"
            )
        )

    # 3) страховка: после backfill не должно остаться NULL.
    season_nullable = _column_nullable(bind, "missions", "season_id")
    if season_nullable:
        orphans = bind.execute(
            sa.text("SELECT COUNT(*) FROM missions WHERE season_id IS NULL")
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"{orphans} missions have NULL season_id after backfill; "
                "refusing to set NOT NULL."
            )

    # 4) NOT NULL + FK + индекс, снятие chapter_id/story_node_id.
    _update_missions(
        dialect,
        bind,
        season_nullable=bool(season_nullable),
        had_chapter=had_chapter,
    )

    # 5) story_node_id из наград.
    _drop_story_node_columns(dialect, bind)

    # 6) legacy-таблицы (ссылки RESTRICT раньше родителей).
    _drop_legacy_tables(bind)

    # 7) каталог прав.
    _delete_legacy_permissions(bind)


def downgrade() -> None:
    """Best-effort восстановление структуры (данные тестовые).

    Таблицы восстанавливаются пустыми; missions.chapter_id/story_node_id
    возвращаются как nullable (однозначный backfill из season_id невозможен,
    т.к. восстановленные chapters пусты). Триггеры защиты истории
    segments_missions НЕ восстанавливаются.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect not in ("sqlite", "postgresql"):
        raise RuntimeError("This migration supports only SQLite and PostgreSQL.")

    tables = _tables(bind)

    # Вернуть catalog permission-строки.
    if "admin_permissions" in tables and "code" in _column_names(bind, "admin_permissions"):
        for code, title, description in PERMISSION_ROWS:
            exists = bind.execute(
                sa.text("SELECT 1 FROM admin_permissions WHERE code = :code"),
                {"code": code},
            ).scalar()
            if not exists:
                bind.execute(
                    sa.text(
                        "INSERT INTO admin_permissions "
                        "(code, title, description, category, is_active) "
                        "VALUES (:code, :title, :description, 'content', 1)"
                    ),
                    {"code": code, "title": title, "description": description},
                )

    # Вернуть missions.chapter_id / missions.story_node_id (nullable).
    mission_columns = _column_names(bind, "missions")
    if "chapter_id" not in mission_columns:
        op.add_column("missions", sa.Column("chapter_id", sa.String(length=64), nullable=True))
        op.create_index("ix_missions_chapter_id", "missions", ["chapter_id"])
    if "story_node_id" not in mission_columns:
        op.add_column("missions", sa.Column("story_node_id", sa.String(length=64), nullable=True))
        op.create_index("ix_missions_story_node_id", "missions", ["story_node_id"])

    # Вернуть story_node_id в награды.
    for table, column, index_name in STORY_NODE_FK_TABLES:
        if table not in _tables(bind):
            continue
        if column not in _column_names(bind, table):
            op.add_column(table, sa.Column(column, sa.String(length=64), nullable=True))
            op.create_index(index_name, table, [column])

    # Снять season_id (FK + индекс + колонка).
    if "missions" in _tables(bind) and "season_id" in _column_names(bind, "missions"):
        if dialect == "sqlite":
            with op.batch_alter_table("missions") as batch_op:
                if _fk_name(bind, "missions", "season_id") is not None:
                    batch_op.drop_constraint(SEASON_ID_FK, type_="foreignkey")
                if _has_index(bind, "missions", ["season_id"]):
                    batch_op.drop_index(SEASON_ID_INDEX)
                batch_op.drop_column("season_id")
        else:
            if _fk_name(bind, "missions", "season_id") is not None:
                op.drop_constraint(SEASON_ID_FK, "missions", type_="foreignkey")
            if _has_index_named(bind, "missions", SEASON_ID_INDEX):
                op.drop_index(SEASON_ID_INDEX, table_name="missions")
            op.drop_column("missions", "season_id")

    # Восстановить таблицы в порядке родитель -> ребёнок.

    if "chapters" not in tables:
        op.create_table(
            "chapters",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("season_id", sa.String(length=64), nullable=False),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_chapters_season_id", "chapters", ["season_id"])

    if "story_nodes" not in tables:
        op.create_table(
            "story_nodes",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("chapter_id", sa.String(length=64), nullable=False),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("presentation_type", sa.String(length=32), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_story_nodes_chapter_id", "story_nodes", ["chapter_id"])

    if "segments" not in tables:
        op.create_table(
            "segments",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("chapter_id", sa.String(length=64), nullable=False),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("content", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_segments_chapter_id", "segments", ["chapter_id"])

    if "segments_missions" not in tables:
        op.create_table(
            "segments_missions",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("segment_id", sa.String(length=64), nullable=False),
            sa.Column("mission_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_by_admin_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.CheckConstraint(
                "(status = 'active' AND archived_at IS NULL AND archived_by_admin_id IS NULL) "
                "OR (status = 'archived' AND archived_at IS NOT NULL)",
                name="ck_segments_missions_lifecycle",
            ),
            sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["archived_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_segments_missions_segment_id", "segments_missions", ["segment_id"])
        op.create_index("ix_segments_missions_mission_id", "segments_missions", ["mission_id"])
        op.create_index("ix_segments_missions_status", "segments_missions", ["status"])
        op.create_index("ix_segments_missions_archived_by_admin_id", "segments_missions", ["archived_by_admin_id"])
