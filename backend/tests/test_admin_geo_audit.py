"""Sprint 8.9.c-2: тесты админ-раздела «Гео-аудит» (3 роута).

Покрывает:
  - GET  /api/v1/admin/geo-audit/flags                       (list_geo_audit_flags);
  - GET  /api/v1/admin/geo-audit/flags/{player_id}/{mission_id} (детали);
  - POST /api/v1/admin/geo-audit/flags/{player_id}/{mission_id}/review;
  - permission-гейты (players.read / players.manage): 403 без гранта,
    положительный контроль с грантом.

Инфраструктура — по образцу test_admin_economy.py: свежая disposable SQLite
(alembic upgrade head) на КАЖДЫЙ тест, потому что admin_audit_log immutable
(DB-триггеры запрещают UPDATE/DELETE) и между тестами его нельзя чистить.

SessionLocal патчится в трёх местах: модуль admin_geo_audit, app.db и
admin_access (grant-проверка require_permission читает гранты через
app.admin_access.SessionLocal). Роуты вызываются напрямую (функция + admin),
как во всех admin-тестах репозитория: Depends(require_permission(...)) при
прямом вызове не исполняется, поэтому permission проверяется отдельно через
сам dependency.

Сырые координаты в before/after/metadata аудита не попадают — это отдельный
тест. Данные создаются только в изолированной тестовой БД.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy import event as sa_event
from sqlalchemy.orm import sessionmaker

from app.admin_geo_audit import (
    EVENT_TYPE_ANTICHEAT_FLAG,
    EVENT_TYPE_ANTICHEAT_REVIEW,
    GEO_AUDIT_MANAGE_PERMISSION,
    GEO_AUDIT_READ_PERMISSION,
    ReviewFlagPayload,
    get_geo_audit_flag_detail,
    list_geo_audit_flags,
    review_geo_audit_flag,
)
from app.models import (
    AdminAuditLog,
    AdminUser,
    AdminUserPermission,
    Chapter,
    GamePlayer,
    Mission,
    PlayerEvent,
    PlayerMission,
    Season,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"

VELOCITY_SIGNAL = {
    "signal": "velocity",
    "speedKmh": 459.3,
    "distanceKm": 1.276,
    "elapsedSeconds": 10,
    "thresholdKmh": 120,
}
ACCURACY_SIGNAL = {
    "signal": "accuracy",
    "accuracyMeters": 1.0,
    "thresholdMeters": 3,
}


def _now_naive_utc() -> datetime:
    """Naive UTC now — как SQLite хранит DateTime(timezone=True)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminGeoAuditTests(unittest.TestCase):
    """Гео-аудит: список флагов, детали и review на реальной SQLite."""

    @classmethod
    def setUpClass(cls) -> None:
        from app import admin_access, admin_geo_audit

        cls.admin_access = admin_access
        cls.admin_geo_audit = admin_geo_audit

    def setUp(self) -> None:
        """Свежая disposable SQLite + alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-geo-audit-tests-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "geo-audit.sqlite3"
        )
        database_url = f"sqlite:///{self.database_path}"

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

        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @sa_event.listens_for(self.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        self._session_local_patches = [
            patch.object(self.admin_geo_audit, "SessionLocal", self.SessionLocal),
            patch("app.db.SessionLocal", self.SessionLocal),
            patch.object(self.admin_access, "SessionLocal", self.SessionLocal),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Хелперы --------------------------------------------------------

    def _request(self) -> SimpleNamespace:
        """Фейковый Request для write_admin_audit (как в test_admin_economy)."""
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.9"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self, is_super_admin: bool = True) -> AdminUser:
        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin" if is_super_admin else "admin",
                    is_super_admin=is_super_admin,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(self, admin_id: str, permission_code: str) -> None:
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode="direct",
                    is_active=True,
                )
            )

    def _make_player(self, session) -> str:
        player_id = f"player-{uuid.uuid4().hex}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"Geo Audit Player-{player_id[-6:]}",
                auth_provider="telegram",
                external_id=f"tg-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()
        return player_id

    def _seed_mission_chain(self, session, mission_id: str) -> None:
        """Season + Chapter + Mission: PlayerMission.mission_id — FK."""
        suffix = uuid.uuid4().hex
        season_id = f"season-{suffix}"
        chapter_id = f"chapter-{suffix}"
        session.add(
            Season(id=season_id, slug=f"season-{suffix}", title="Season")
        )
        session.flush()
        session.add(
            Chapter(
                id=chapter_id,
                season_id=season_id,
                slug=f"chapter-{suffix}",
                title="Chapter",
            )
        )
        session.flush()
        session.add(
            Mission(
                id=mission_id,
                chapter_id=chapter_id,
                slug=f"mission-{suffix}",
                mission_type="text_answer",
                mission_category="solo",
                title="Geo audit mission",
                content={},
                validation_config={},
                status="published",
                sort_order=0,
            )
        )
        session.flush()

    def _seed_player_mission(
        self,
        session,
        player_id: str,
        mission_id: str,
        *,
        status: str = "in_progress",
        anticheat_status: str = "review",
        signals: list[dict] | None = None,
    ) -> PlayerMission:
        player_mission = PlayerMission(
            id=f"player-mission-{uuid.uuid4().hex}",
            player_id=player_id,
            mission_id=mission_id,
            status=status,
            progress={
                "anticheat": {
                    "status": anticheat_status,
                    "signals": (
                        signals
                        if signals is not None
                        else [dict(VELOCITY_SIGNAL)]
                    ),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        session.add(player_mission)
        session.flush()
        return player_mission

    def _add_flag_event(
        self,
        session,
        player_id: str,
        mission_id: str,
        *,
        created_at: datetime | None = None,
        signals: list[dict] | None = None,
        zone_id: str = "zone-slug",
    ) -> PlayerEvent:
        event = PlayerEvent(
            id=f"player-event-{uuid.uuid4().hex}",
            player_id=player_id,
            event_type=EVENT_TYPE_ANTICHEAT_FLAG,
            payload_json={
                "missionId": mission_id,
                "zoneId": zone_id,
                "playerId": player_id,
                "mode": "flag",
                "signals": signals if signals is not None else [dict(VELOCITY_SIGNAL)],
            },
            correlation_id=uuid.uuid4().hex,
        )
        event.created_at = created_at or _now_naive_utc()
        session.add(event)
        session.flush()
        return event

    def _call_list(self, admin: AdminUser, **kwargs) -> dict:
        return list_geo_audit_flags(_admin=admin, **kwargs)

    def _call_detail(
        self,
        player_id: str,
        mission_id: str,
        admin: AdminUser,
    ) -> dict:
        return get_geo_audit_flag_detail(
            player_id=player_id,
            mission_id=mission_id,
            _admin=admin,
        )

    def _call_review(
        self,
        player_id: str,
        mission_id: str,
        decision: str,
        admin: AdminUser,
        *,
        reason: str | None = None,
    ) -> dict:
        return review_geo_audit_flag(
            player_id=player_id,
            mission_id=mission_id,
            payload=ReviewFlagPayload(decision=decision, reason=reason),
            request=self._request(),
            admin=admin,
        )


    # ---- GET /flags: список флагов --------------------------------------

    def test_list_empty(self) -> None:
        admin = self._make_admin()

        result = self._call_list(admin, period="all")

        self.assertEqual(result["flags"], [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["limit"], 50)
        self.assertEqual(result["offset"], 0)

    def test_list_returns_flags(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            mission_id = f"mission-{uuid.uuid4().hex}"
            self._seed_mission_chain(session, mission_id)
            self._seed_player_mission(session, player_id, mission_id)
            self._add_flag_event(session, player_id, mission_id)

        result = self._call_list(admin, period="all", player_id=player_id)

        self.assertEqual(result["total"], 1)
        flag = result["flags"][0]
        self.assertEqual(flag["playerId"], player_id)
        self.assertEqual(flag["missionId"], mission_id)
        self.assertEqual(flag["zoneId"], "zone-slug")
        self.assertEqual(flag["mode"], "flag")
        self.assertEqual(flag["signals"][0]["signal"], "velocity")
        self.assertEqual(flag["signals"][0]["speedKmh"], 459.3)
        self.assertEqual(flag["reviewStatus"], "review")
        self.assertIsNotNone(flag["correlationId"])
        self.assertIsNotNone(flag["createdAt"])

    def test_list_filter_player_id(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_a = self._make_player(session)
            player_b = self._make_player(session)
            self._add_flag_event(session, player_a, "mission-a")
            self._add_flag_event(session, player_b, "mission-b")

        result = self._call_list(admin, period="all", player_id=player_a)

        self.assertEqual(result["total"], 1)
        self.assertEqual([flag["playerId"] for flag in result["flags"]], [player_a])

    def test_list_period_week_excludes_old(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._add_flag_event(
                session,
                player_id,
                "mission-old",
                created_at=_now_naive_utc() - timedelta(days=10),
            )

        week = self._call_list(admin, period="week", player_id=player_id)
        month = self._call_list(admin, period="month", player_id=player_id)

        self.assertEqual(week["total"], 0)
        self.assertEqual(month["total"], 1)

    def test_list_signal_filter_velocity(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._add_flag_event(
                session, player_id, "mission-v", signals=[dict(VELOCITY_SIGNAL)]
            )
            self._add_flag_event(
                session, player_id, "mission-a", signals=[dict(ACCURACY_SIGNAL)]
            )

        result = self._call_list(
            admin, period="all", player_id=player_id, signal="velocity"
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["flags"][0]["missionId"], "mission-v")


    def test_list_signal_filter_accuracy(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._add_flag_event(
                session, player_id, "mission-v", signals=[dict(VELOCITY_SIGNAL)]
            )
            self._add_flag_event(
                session, player_id, "mission-a", signals=[dict(ACCURACY_SIGNAL)]
            )

        result = self._call_list(
            admin, period="all", player_id=player_id, signal="accuracy"
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["flags"][0]["missionId"], "mission-a")

    def test_list_review_status_from_progress(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            review_player = self._make_player(session)
            reviewed_player = self._make_player(session)
            orphan_player = self._make_player(session)

            review_mission = f"mission-{uuid.uuid4().hex}"
            reviewed_mission = f"mission-{uuid.uuid4().hex}"
            self._seed_mission_chain(session, review_mission)
            self._seed_mission_chain(session, reviewed_mission)
            self._seed_player_mission(
                session, review_player, review_mission, anticheat_status="review"
            )
            self._seed_player_mission(
                session,
                reviewed_player,
                reviewed_mission,
                anticheat_status="reviewed",
            )
            self._add_flag_event(session, review_player, review_mission)
            self._add_flag_event(session, reviewed_player, reviewed_mission)
            # Флаг без PlayerMission: reviewStatus отсутствует.
            self._add_flag_event(session, orphan_player, "mission-orphan")

        review_result = self._call_list(admin, period="all", player_id=review_player)
        reviewed_result = self._call_list(
            admin, period="all", player_id=reviewed_player
        )
        orphan_result = self._call_list(admin, period="all", player_id=orphan_player)

        self.assertEqual(review_result["flags"][0]["reviewStatus"], "review")
        self.assertEqual(reviewed_result["flags"][0]["reviewStatus"], "reviewed")
        self.assertIsNone(orphan_result["flags"][0]["reviewStatus"])

    def test_list_pagination_and_clamp(self) -> None:
        admin = self._make_admin()
        now = _now_naive_utc()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            for index in range(3):
                self._add_flag_event(
                    session,
                    player_id,
                    f"mission-{index}",
                    created_at=now - timedelta(seconds=index + 1),
                )

        page = self._call_list(
            admin, period="all", player_id=player_id, limit=1, offset=1
        )
        clamped = self._call_list(
            admin, period="all", player_id=player_id, limit=999, offset=-5
        )

        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["flags"]), 1)
        self.assertEqual(page["flags"][0]["missionId"], "mission-1")
        self.assertEqual(page["limit"], 1)
        self.assertEqual(page["offset"], 1)

        self.assertEqual(clamped["limit"], 200)
        self.assertEqual(clamped["offset"], 0)
        self.assertEqual(clamped["total"], 3)

    def test_list_422_bad_period(self) -> None:
        admin = self._make_admin()

        with self.assertRaises(HTTPException) as context:
            self._call_list(admin, period="bogus")

        self.assertEqual(context.exception.status_code, 422)

    def test_list_422_bad_signal(self) -> None:
        admin = self._make_admin()

        with self.assertRaises(HTTPException) as context:
            self._call_list(admin, signal="teleport")

        self.assertEqual(context.exception.status_code, 422)


    # ---- GET /flags/{player_id}/{mission_id}: детали ---------------------

    def test_detail_ok(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            mission_id = f"mission-{uuid.uuid4().hex}"
            self._seed_mission_chain(session, mission_id)
            self._seed_player_mission(session, player_id, mission_id)
            self._add_flag_event(session, player_id, mission_id)

        result = self._call_detail(player_id, mission_id, admin)

        self.assertEqual(result["playerId"], player_id)
        self.assertEqual(result["missionId"], mission_id)
        self.assertIsNotNone(result["flag"])
        self.assertEqual(result["flag"]["missionId"], mission_id)
        self.assertEqual(result["flag"]["reviewStatus"], "review")
        self.assertEqual(result["anticheat"]["status"], "review")
        self.assertIsNone(result["lastReview"])

    def test_detail_404(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)

        with self.assertRaises(HTTPException) as context:
            self._call_detail(player_id, "mission-missing", admin)

        self.assertEqual(context.exception.status_code, 404)

    def test_detail_progress_only(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            mission_id = f"mission-{uuid.uuid4().hex}"
            self._seed_mission_chain(session, mission_id)
            self._seed_player_mission(session, player_id, mission_id)

        result = self._call_detail(player_id, mission_id, admin)

        self.assertIsNone(result["flag"])
        self.assertEqual(result["anticheat"]["status"], "review")
        self.assertIsNone(result["lastReview"])


    # ---- POST /flags/{player_id}/{mission_id}/review ---------------------

    def _seed_review_case(self) -> tuple[str, str, str]:
        """Player + mission chain + PlayerMission(review) + flag event."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            mission_id = f"mission-{uuid.uuid4().hex}"
            self._seed_mission_chain(session, mission_id)
            player_mission = self._seed_player_mission(
                session, player_id, mission_id
            )
            self._add_flag_event(session, player_id, mission_id)
            return player_id, mission_id, player_mission.id

    def _audit_rows(self, player_mission_id: str) -> list:
        with self.SessionLocal() as session:
            return list(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == "anticheat.review",
                        AdminAuditLog.entity_type == "player_mission",
                        AdminAuditLog.entity_id == player_mission_id,
                    )
                ).all()
            )

    def _review_events(self, player_id: str) -> list:
        with self.SessionLocal() as session:
            return list(
                session.scalars(
                    select(PlayerEvent).where(
                        PlayerEvent.player_id == player_id,
                        PlayerEvent.event_type == EVENT_TYPE_ANTICHEAT_REVIEW,
                    )
                ).all()
            )

    def test_review_happy_reviewed(self) -> None:
        admin = self._make_admin()
        player_id, mission_id, player_mission_id = self._seed_review_case()

        result = self._call_review(player_id, mission_id, "reviewed", admin)

        self.assertEqual(
            result,
            {
                "playerId": player_id,
                "missionId": mission_id,
                "status": "reviewed",
            },
        )

        with self.SessionLocal() as session:
            stored = session.get(PlayerMission, player_mission_id)
            anticheat = stored.progress["anticheat"]
        self.assertEqual(anticheat["status"], "reviewed")
        self.assertEqual(anticheat["reviewedByAdminId"], admin.id)
        self.assertIsNotNone(anticheat["reviewedAt"])

        audits = self._audit_rows(player_mission_id)
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.admin_user_id, admin.id)
        self.assertEqual(audit.permission_code, GEO_AUDIT_MANAGE_PERMISSION)
        self.assertEqual(audit.outcome, "success")
        self.assertEqual(audit.metadata_json["playerId"], player_id)
        self.assertEqual(audit.metadata_json["missionId"], mission_id)
        self.assertEqual(audit.metadata_json["zoneId"], "zone-slug")
        self.assertEqual(audit.metadata_json["decision"], "reviewed")
        self.assertIs(audit.metadata_json["reasonProvided"], False)
        self.assertIsNotNone(audit.correlation_id)

        events = self._review_events(player_id)
        self.assertEqual(len(events), 1)
        payload = events[0].payload_json
        self.assertEqual(payload["decision"], "reviewed")
        self.assertEqual(payload["adminId"], admin.id)
        self.assertEqual(payload["missionId"], mission_id)
        self.assertEqual(payload["zoneId"], "zone-slug")

    def test_review_dismissed(self) -> None:
        admin = self._make_admin()
        player_id, mission_id, player_mission_id = self._seed_review_case()

        result = self._call_review(player_id, mission_id, "dismissed", admin)

        self.assertEqual(result["status"], "dismissed")
        with self.SessionLocal() as session:
            stored = session.get(PlayerMission, player_mission_id)
            anticheat = stored.progress["anticheat"]
        self.assertEqual(anticheat["status"], "dismissed")

        audits = self._audit_rows(player_mission_id)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].metadata_json["decision"], "dismissed")

        events = self._review_events(player_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload_json["decision"], "dismissed")

    def test_review_409_repeat(self) -> None:
        admin = self._make_admin()
        player_id, mission_id, _player_mission_id = self._seed_review_case()

        self._call_review(player_id, mission_id, "reviewed", admin)

        with self.assertRaises(HTTPException) as context:
            self._call_review(player_id, mission_id, "dismissed", admin)

        self.assertEqual(context.exception.status_code, 409)


    def test_review_404_missing_player_mission(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)

        with self.assertRaises(HTTPException) as context:
            self._call_review(player_id, "mission-missing", "reviewed", admin)

        self.assertEqual(context.exception.status_code, 404)

    def test_review_409_not_review_status(self) -> None:
        admin = self._make_admin()
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            mission_id = f"mission-{uuid.uuid4().hex}"
            self._seed_mission_chain(session, mission_id)
            self._seed_player_mission(
                session, player_id, mission_id, anticheat_status="reviewed"
            )

        with self.assertRaises(HTTPException) as context:
            self._call_review(player_id, mission_id, "dismissed", admin)

        self.assertEqual(context.exception.status_code, 409)

    def test_review_reason_not_in_audit_but_in_event(self) -> None:
        admin = self._make_admin()
        player_id, mission_id, player_mission_id = self._seed_review_case()

        self._call_review(
            player_id, mission_id, "reviewed", admin, reason="manual check"
        )

        audit = self._audit_rows(player_mission_id)[0]
        self.assertIs(audit.metadata_json["reasonProvided"], True)
        serialized_audit = json.dumps(
            [audit.metadata_json, audit.before_json, audit.after_json]
        )
        self.assertNotIn("manual check", serialized_audit)

        events = self._review_events(player_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload_json["reason"], "manual check")

    def test_audit_payload_has_no_raw_coordinates(self) -> None:
        admin = self._make_admin()
        player_id, mission_id, player_mission_id = self._seed_review_case()

        self._call_review(player_id, mission_id, "reviewed", admin)

        audit = self._audit_rows(player_mission_id)[0]
        serialized = json.dumps(
            [audit.before_json, audit.after_json, audit.metadata_json]
        )
        for forbidden in (
            '"latitude"',
            '"longitude"',
            '"generated_from_lat"',
            '"generated_from_lng"',
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertIn('"speedKmh"', serialized)


    # ---- Permission-гейты (require_permission) --------------------------

    def test_read_permission_403_and_positive(self) -> None:
        from app.admin_access import require_permission

        dependency = require_permission(GEO_AUDIT_READ_PERMISSION)
        admin = self._make_admin(is_super_admin=False)

        # Ровно тот dependency, что защищает роут в проде.
        with self.assertRaises(HTTPException) as context:
            dependency(admin=admin)
        self.assertEqual(context.exception.status_code, 403)

        # Положительный контроль: с direct-грантом гейт открыт.
        self._grant(admin.id, GEO_AUDIT_READ_PERMISSION)
        granted = dependency(admin=admin)
        self.assertEqual(granted.id, admin.id)

    def test_manage_permission_403_and_positive(self) -> None:
        from app.admin_access import require_permission

        dependency = require_permission(GEO_AUDIT_MANAGE_PERMISSION)
        admin = self._make_admin(is_super_admin=False)

        with self.assertRaises(HTTPException) as context:
            dependency(admin=admin)
        self.assertEqual(context.exception.status_code, 403)

        self._grant(admin.id, GEO_AUDIT_MANAGE_PERMISSION)
        granted = dependency(admin=admin)
        self.assertEqual(granted.id, admin.id)

    def test_review_payload_validation(self) -> None:
        """decision допускает только reviewed|dismissed (Pydantic Literal)."""
        with self.assertRaises(ValidationError):
            ReviewFlagPayload(decision="bogus")


if __name__ == "__main__":
    unittest.main()

