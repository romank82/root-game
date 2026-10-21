"""Admin StoryNode — CRUD, FK chapter_id, строгая иерархия (Sprint 8.26).

Live SQLite + alembic upgrade head (паттерн test_admin_chapters.py): disposable
БД со схемой из миграций (включая таблицы seasons/chapters/story_nodes и admin
permissions story_nodes.read/story_nodes.manage, заселённые миграцией
90de6dad12b). Endpoint-функции вызываются напрямую с реальными AdminUser из БД
и замоканным SessionLocal модуля admin_story_nodes.

Покрытые согласованные решения (Sprint 8.26):
(а) create в archived-главу -> 422;
(б) смена chapter_id у published-story-node -> 409;
(в) повторный publish published-story-node -> 422;
(г) publish только при published главе -> 422 иначе;
(д) archived story-node не редактируется -> 409;
(е) архив только published->archived; archive draft -> 422.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import DIRECT_EXECUTION_MODE
from app.admin_story_nodes import (
    STORY_NODES_MANAGE_PERMISSION,
    STORY_NODES_READ_PERMISSION,
    StoryNodeCreatePayload,
    StoryNodeUpdatePayload,
    archive_admin_story_node,
    create_admin_story_node,
    get_admin_story_node,
    list_admin_story_nodes,
    publish_admin_story_node,
    update_admin_story_node,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminStoryNodesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-story-nodes-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "admin.sqlite3"
        database_url = f"sqlite:///{cls.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(cls.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        from app import admin_story_nodes

        cls.admin_story_nodes = admin_story_nodes
        cls._session_local_patch = patch.object(
            admin_story_nodes, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.9"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _make_chapter(
        self,
        *,
        slug: str,
        status: str = "published",
        season_status: str = "published",
    ) -> str:
        from app.models import Chapter

        season_id = self._make_season(slug=f"season-{slug}", status=season_status)
        chapter_id = f"chapter-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Chapter(
                    id=chapter_id,
                    season_id=season_id,
                    slug=slug,
                    title=f"Глава {slug}",
                    status=status,
                    sort_order=0,
                )
            )
        return chapter_id

    def _create(self, admin, *, chapter_id, slug=None, title=None, body=None, **kwargs):
        payload = StoryNodeCreatePayload(
            chapter_id=chapter_id,
            slug=slug,
            title=title or f"StoryNode {uuid.uuid4().hex[:6]}",
            body=body or "Тело сюжетного узла",
            **kwargs,
        )
        return create_admin_story_node(
            payload=payload,
            request=self._request(),
            admin=admin,
        )["story_node"]

    def _load_story_node(self, story_node_id: str):
        from app.models import StoryNode

        with self.SessionLocal() as session:
            return session.get(StoryNode, story_node_id)

    def _count_audit(self, action: str, admin_id: str) -> int:
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return len(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == action,
                        AdminAuditLog.entity_type == "story_node",
                        AdminAuditLog.admin_user_id == admin_id,
                    )
                ).all()
            )


    def _grant(self, admin_id: str, permission_code: str) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=DIRECT_EXECUTION_MODE,
                    is_active=True,
                )
            )

    def _make_season(self, *, slug: str, status: str = "published") -> str:
        from app.models import Season

        season_id = f"season-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=season_id,
                    slug=slug,
                    title=f"Сезон {slug}",
                    status=status,
                    sort_order=0,
                )
            )
        return season_id


# ---- Тесты: create ------------------------------------------------------

    def test_create_story_node_in_published_chapter(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(slug="sn-chapter-create", status="published")

        created = self._create(
            admin, chapter_id=chapter_id, slug="node-one", title="Узел первый"
        )

        self.assertTrue(created["id"].startswith("story-node-"))
        self.assertEqual(created["chapterId"], chapter_id)
        self.assertEqual(created["slug"], "node-one")
        self.assertEqual(created["title"], "Узел первый")
        self.assertEqual(created["body"], "Тело сюжетного узла")
        self.assertEqual(created["presentationType"], "archive")
        self.assertEqual(created["content"], {})
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["sortOrder"], 0)

        stored = self._load_story_node(created["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "draft")
        self.assertEqual(stored.chapter_id, chapter_id)
        self.assertEqual(self._count_audit("story_node.created", admin.id), 1)

    def test_create_autoslug_from_russian_title(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-autoslug", status="published"
        )

        created = self._create(admin, chapter_id=chapter_id, title="ГЛАВА 2: ПЕРЕХОД")

        self.assertEqual(created["slug"], "glava-2-perekhod")

    def test_create_missing_chapter_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin,
                chapter_id="chapter-not-exists",
                slug="no-chapter",
                title="Нет главы",
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_create_in_archived_chapter_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-archived", status="archived"
        )

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin,
                chapter_id=chapter_id,
                slug="archived-host",
                title="В архиве",
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_create_duplicate_slug_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(slug="sn-chapter-dup", status="published")

        first = self._create(
            admin, chapter_id=chapter_id, slug="duplicated", title="Первый"
        )

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin, chapter_id=chapter_id, slug="duplicated", title="Второй"
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_story_node(first["id"]).slug, "duplicated")

        # (PATCH): чужой slug при update тоже даёт 409.
        other_chapter_id = self._make_chapter(
            slug="sn-chapter-dup-other", status="published"
        )
        second = self._create(
            admin,
            chapter_id=other_chapter_id,
            slug="unique-other",
            title="Другой узел",
        )
        with self.assertRaises(HTTPException) as caught:
            update_admin_story_node(
                story_node_id=second["id"],
                payload=StoryNodeUpdatePayload(slug="duplicated"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_create_presentation_type_and_content(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-presentation", status="published"
        )

        created = self._create(
            admin,
            chapter_id=chapter_id,
            slug="custom-presentation",
            title="Кастомное представление",
            presentation_type="dialogue",
            content={"caption": "Текст на экране", "choices": ["a", "b"]},
            sort_order=7,
        )

        self.assertEqual(created["presentationType"], "dialogue")
        self.assertEqual(
            created["content"], {"caption": "Текст на экране", "choices": ["a", "b"]}
        )
        self.assertEqual(created["sortOrder"], 7)

# ---- Тесты: publish --------------------------------------------------------

    def test_publish_in_draft_chapter_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(slug="sn-chapter-draft", status="draft")

        created = self._create(
            admin, chapter_id=chapter_id, slug="draft-home", title="В черновике"
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_story_node(
                story_node_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self._load_story_node(created["id"]).status, "draft")

    def test_publish_in_published_chapter_ok(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-pub", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="publish-me", title="Опубликовать"
        )

        published = publish_admin_story_node(
            story_node_id=created["id"],
            request=self._request(),
            admin=admin,
        )["story_node"]

        self.assertEqual(published["status"], "published")
        self.assertEqual(self._load_story_node(created["id"]).status, "published")
        self.assertEqual(self._count_audit("story_node.published", admin.id), 1)

    def test_publish_twice_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-twice", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="double-publish", title="Дважды"
        )
        publish_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_story_node(
                story_node_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)

# ---- Тесты: archive ---------------------------------------------------------

    def test_archive_published_ok(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-archive", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="archive-me", title="Архивировать"
        )
        publish_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )

        archived = archive_admin_story_node(
            story_node_id=created["id"],
            request=self._request(),
            admin=admin,
        )["story_node"]

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self._load_story_node(created["id"]).status, "archived")
        self.assertEqual(self._count_audit("story_node.archived", admin.id), 1)

    def test_archive_draft_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-archive-draft", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="archive-draft", title="Архив черновика"
        )

        with self.assertRaises(HTTPException) as caught:
            archive_admin_story_node(
                story_node_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)

    # ---- Тесты: update ---------------------------------------------------------

    def test_update_published_change_chapter_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_a = self._make_chapter(
            slug="sn-chapter-a", status="published"
        )
        chapter_b = self._make_chapter(
            slug="sn-chapter-b", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_a, slug="frozen-node", title="Закреплённый"
        )
        publish_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            update_admin_story_node(
                story_node_id=created["id"],
                payload=StoryNodeUpdatePayload(chapterId=chapter_b),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            self._load_story_node(created["id"]).chapter_id, chapter_a
        )

    def test_update_archived_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-frozendb", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="frozen-final", title="Замороженный"
        )
        publish_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            update_admin_story_node(
                story_node_id=created["id"],
                payload=StoryNodeUpdatePayload(title="Нельзя изменить"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            self._load_story_node(created["id"]).status, "archived"
        )

    def test_update_draft_allowed_and_audited(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-update", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="before", title="До"
        )
        updated = update_admin_story_node(
            story_node_id=created["id"],
            payload=StoryNodeUpdatePayload(title="После", body="Новый текст"),
            request=self._request(),
            admin=admin,
        )["story_node"]

        self.assertEqual(updated["title"], "После")
        self.assertEqual(updated["body"], "Новый текст")
        stored = self._load_story_node(created["id"])
        self.assertEqual(stored.title, "После")
        self.assertEqual(self._count_audit("story_node.updated", admin.id), 1)

    # ---- Тесты: get / list -----------------------------------------------------

    def test_get_and_404(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_READ_PERMISSION)
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-get", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="get-me", title="Get-Me"
        )

        got = get_admin_story_node(story_node_id=created["id"], _admin=admin)
        self.assertEqual(got["story_node"]["id"], created["id"])
        self.assertEqual(got["story_node"]["title"], "Get-Me")
        self.assertEqual(got["story_node"]["chapterId"], chapter_id)

        with self.assertRaises(HTTPException) as caught:
            get_admin_story_node(story_node_id="story-node-missing", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

    def test_list_ordered_and_filters(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_READ_PERMISSION)
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_a = self._make_chapter(
            slug="sn-chapter-list-a", status="published"
        )
        chapter_b = self._make_chapter(
            slug="sn-chapter-list-b", status="published"
        )

        self._create(
            admin,
            chapter_id=chapter_a,
            slug="node-b",
            title="B-узел",
            sort_order=2,
        )
        first = self._create(
            admin,
            chapter_id=chapter_a,
            slug="node-a",
            title="A-узел",
            sort_order=1,
        )
        self._create(
            admin, chapter_id=chapter_b, slug="node-c", title="C-узел", sort_order=0
        )
        publish_admin_story_node(
            story_node_id=first["id"], request=self._request(), admin=admin
        )

        result = list_admin_story_nodes(_admin=admin)
        slugs = [node["slug"] for node in result["story_nodes"]]
        self.assertIn("node-a", slugs)
        self.assertIn("node-b", slugs)
        self.assertLess(slugs.index("node-a"), slugs.index("node-b"))

        published = list_admin_story_nodes(status="published", _admin=admin)
        self.assertIn("node-a", [node["slug"] for node in published["story_nodes"]])
        self.assertNotIn(
            "node-b", [node["slug"] for node in published["story_nodes"]]
        )

        by_chapter = list_admin_story_nodes(chapter_id=chapter_a, _admin=admin)
        self.assertEqual(
            {node["slug"] for node in by_chapter["story_nodes"]},
            {"node-a", "node-b"},
        )

        with self.assertRaises(HTTPException) as caught:
            list_admin_story_nodes(status="unknown", _admin=admin)
        self.assertEqual(caught.exception.status_code, 422)

    def test_lifecycle_writes_audit_records(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, STORY_NODES_MANAGE_PERMISSION)
        chapter_id = self._make_chapter(
            slug="sn-chapter-audit", status="published"
        )

        created = self._create(
            admin, chapter_id=chapter_id, slug="lifecycle", title="Жизненный цикл"
        )
        publish_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_story_node(
            story_node_id=created["id"], request=self._request(), admin=admin
        )

        self.assertEqual(self._count_audit("story_node.created", admin.id), 1)
        self.assertEqual(self._count_audit("story_node.published", admin.id), 1)
        self.assertEqual(self._count_audit("story_node.archived", admin.id), 1)


if __name__ == "__main__":
    unittest.main()

