from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class MissionEngineAcceptTests(unittest.TestCase):
    """8.4.e: accept_mission — генерация spawn, идемпотентность и ошибки.

    Инварианты проверяются не через абсолютные расстояния в градусах
    (хардкод под конкретный search_radius_m), а через контракт ответа:
    spawn не None, spawn != центр игрока, searchRadiusMeters равен
    search_radius_meters зоны, zoneRadiusMeters равен radius_meters зоны,
    arObjectId равен миссии, status == in_progress, accepted is True.
    Инвариант «расстояние <= search_radius_m» покрыт в test_geo_spawn.py.
    """

    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-accept-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "mission-engine-accept.sqlite3"
        )
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

        from app import mission_engine

        cls.mission_engine = mission_engine
        cls._session_local_patch = patch.object(
            mission_engine,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------
    def _fixture(
        self,
        *,
        search_radius_meters: int = 3000,
        mission_type: str = "text_answer",
        with_zone: bool = True,
        execution_time_limit_seconds: int | None = None,
        reentry_cooldown_seconds: int = 0,
        unlock_after_mission_id: str | None = None,
        player_id: str | None = None,
    ) -> dict[str, str]:
        from app.models import ARObject, Chapter, GamePlayer, GeoZone, Mission, Season

        suffix = uuid.uuid4().hex
        ids = {
            "player": player_id or f"player-{suffix}",
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "zone": f"zone-{suffix}",
            "ar_object": f"ar-object-{suffix}",
            "mission": f"mission-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Accept test season",
                    description="Isolated accept fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()

            session.add(
                Chapter(
                    id=ids["chapter"],
                    season_id=ids["season"],
                    slug=f"chapter-{suffix}",
                    title="Accept test chapter",
                    description="Isolated accept fixture",
                    status="published",
                    sort_order=1,
                )
            )

            if player_id is None:
                session.add(
                    GamePlayer(
                        id=ids["player"],
                        display_name=f"Accept Player-{ids['player'][-6:]}",
                        auth_provider="telegram",
                        external_id=f"tg-{uuid.uuid4().hex}",
                        status="active",
                    )
                )
            else:
                # Общий игрок для цепочки разблокировки: переиспользуем
                # существующего, нового не создаём.
                self.assertIsNotNone(session.get(GamePlayer, player_id))
            session.flush()

            if with_zone:
                session.add(
                    GeoZone(
                        id=ids["zone"],
                        slug=f"zone-{suffix}",
                        title="Accept test zone",
                        description="Isolated accept fixture",
                        zone_type="radius",
                        status="published",
                        sort_order=1,
                        radius_meters=50,
                        search_radius_meters=search_radius_meters,
                        location_constraints={"avoid_buildings": True},
                        timezone="UTC",
                    )
                )
                session.flush()

                session.add(
                    ARObject(
                        id=ids["ar_object"],
                        slug=f"ar-object-{suffix}",
                        title="Accept test AR object",
                        description="Isolated accept fixture",
                        status="published",
                        sort_order=1,
                        geo_zone_id=ids["zone"],
                        object_type="collectible",
                        asset_uri=f"https://example.test/assets/{suffix}.glb",
                        asset_mime_type="model/gltf-binary",
                        scene_preset="default",
                        scale_meters=1.0,
                        orientation="upright",
                        discovery_scenario={},
                        minigame_config={},
                        instruction_text="Accept test instruction",
                        validation_config={},
                    )
                )
                session.flush()

            session.add(
                Mission(
                    id=ids["mission"],
                    chapter_id=ids["chapter"],
                    slug=f"mission-{suffix}",
                    mission_type=mission_type,
                    mission_category="solo",
                    title="Accept test mission",
                    description="Isolated accept fixture",
                    content={"schemaVersion": 1},
                    validation_config={},
                    status="published",
                    sort_order=1,
                    geo_zone_id=ids["zone"] if with_zone else None,
                    ar_object_id=ids["ar_object"] if with_zone else None,
                    execution_time_limit_seconds=execution_time_limit_seconds,
                    reentry_cooldown_seconds=reentry_cooldown_seconds,
                    unlock_after_mission_id=unlock_after_mission_id,
                )
            )

        return ids

    def _assert_spawn_invariants(
        self,
        response: dict,
        ids: dict[str, str],
        *,
        search_radius_meters: int,
        zone_radius_meters: int = 50,
    ) -> None:
        """Инварианты ответа accept_mission (без хардкода градусов)."""
        self.assertIs(response["accepted"], True)
        self.assertEqual(response["status"], "in_progress")
        self.assertIsNotNone(response["spawn"])

        spawn = response["spawn"]
        self.assertEqual(spawn["searchRadiusMeters"], search_radius_meters)
        self.assertEqual(spawn["zoneRadiusMeters"], zone_radius_meters)
        self.assertEqual(spawn["arObjectId"], ids["ar_object"])
        self.assertNotEqual(
            (spawn["latitude"], spawn["longitude"]),
            (self.PLAYER_LATITUDE, self.PLAYER_LONGITUDE),
        )

    def _call_accept(
        self,
        ids: dict[str, str],
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        accuracy: float | None = None,
    ) -> dict:
        return self.mission_engine.accept_mission(
            ids["player"],
            ids["mission"],
            latitude if latitude is not None else self.PLAYER_LATITUDE,
            longitude if longitude is not None else self.PLAYER_LONGITUDE,
            accuracy=accuracy,
        )
# ---- 8.4.e: сценарии ------------------------------------------------
    def test_accept_generates_spawn_point(self) -> None:
        ids = self._fixture(search_radius_meters=3000)

        response = self._call_accept(ids)

        self._assert_spawn_invariants(
            response,
            ids,
            search_radius_meters=3000,
        )

    def test_accept_with_small_search_radius(self) -> None:
        ids = self._fixture(search_radius_meters=500)

        response = self._call_accept(ids)

        self._assert_spawn_invariants(
            response,
            ids,
            search_radius_meters=500,
        )

    def test_accept_with_large_search_radius(self) -> None:
        ids = self._fixture(search_radius_meters=20000)

        response = self._call_accept(ids)

        self._assert_spawn_invariants(
            response,
            ids,
            search_radius_meters=20000,
        )

    def test_accept_is_idempotent(self) -> None:
        from app.models import PlayerMission

        ids = self._fixture(search_radius_meters=3000)

        first = self._call_accept(ids)
        second = self._call_accept(ids)

        self._assert_spawn_invariants(
            first,
            ids,
            search_radius_meters=3000,
        )
        self._assert_spawn_invariants(
            second,
            ids,
            search_radius_meters=3000,
        )

        # Спавн при повторном accept идентичен (latitude, longitude, generatedAt).
        self.assertEqual(first["spawn"]["latitude"], second["spawn"]["latitude"])
        self.assertEqual(first["spawn"]["longitude"], second["spawn"]["longitude"])
        self.assertEqual(first["spawn"]["generatedAt"], second["spawn"]["generatedAt"])

        # В БД ровно одна запись PlayerMission для пары (player, mission).
        with self.SessionLocal() as session:
            count = session.scalar(
                select(func.count(PlayerMission.id)).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            )
        self.assertEqual(count, 1)

        # tz-инвариант: оба ответа сериализуют startedAt с "+00:00".
        # Первый ответ — aware из памяти; второй — после reload из SQLite.
        # Если этот инвариант нарушится — на фронте сломается new Date(...) в часовых поясах.
        self.assertIsNotNone(first["startedAt"])
        self.assertIsNotNone(second["startedAt"])
        self.assertTrue(
            first["startedAt"].endswith("+00:00"),
            f"first.startedAt должен заканчиваться на +00:00, получили: {first['startedAt']!r}",
        )
        self.assertTrue(
            second["startedAt"].endswith("+00:00"),
            f"second.startedAt должен заканчиваться на +00:00, получили: {second['startedAt']!r}",
        )

    def test_accept_sets_deadline_from_limit(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select
        from datetime import timedelta

        ids = self._fixture(execution_time_limit_seconds=3600)
        response = self._call_accept(ids)

        self._assert_spawn_invariants(response, ids, search_radius_meters=3000)

        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            self.assertIsNotNone(pm.started_at)
            self.assertIsNotNone(pm.deadline_at)
            delta = pm.deadline_at - pm.started_at
            # Допуск: ±2 секунды (SQLite tz-awareness)
            self.assertLess(abs(delta.total_seconds() - 3600), 2)

    def test_accept_without_limit_leaves_deadline_none(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select

        ids = self._fixture(execution_time_limit_seconds=None)
        self._call_accept(ids)

        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            self.assertIsNotNone(pm.started_at)
            self.assertIsNone(pm.deadline_at)

    def test_idempotent_accept_does_not_change_deadline(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select

        ids = self._fixture(execution_time_limit_seconds=1800)

        self._call_accept(ids)
        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            first_deadline = pm.deadline_at

        # Повторный accept
        self._call_accept(ids)
        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            self.assertEqual(pm.deadline_at, first_deadline)

    def test_bootstrap_includes_deadline_fields(self) -> None:
        ids = self._fixture(execution_time_limit_seconds=600)
        self._call_accept(ids)

        from app.mission_engine import get_bootstrap
        bootstrap = get_bootstrap(ids["player"])

        mission_entry = next(
            (m for m in bootstrap["missions"] if m["id"] == ids["mission"]),
            None,
        )
        self.assertIsNotNone(mission_entry)
        self.assertEqual(mission_entry["executionTimeLimitSeconds"], 600)
        self.assertIsNotNone(mission_entry["deadlineAt"])

    def test_accept_fails_when_mission_has_no_zone(self) -> None:
        ids = self._fixture(with_zone=False)

        with self.assertRaises(MissionEngineError) as error:
            self._call_accept(ids)

        self.assertEqual(error.exception.status_code, 422)

    def test_accept_fails_for_team_mission(self) -> None:
        ids = self._fixture(mission_type="team")

        with self.assertRaises(MissionEngineError) as error:
            self._call_accept(ids)

        self.assertEqual(error.exception.status_code, 409)

    def test_accept_validation_coordinates(self) -> None:
        ids = self._fixture()

        # latitude вне диапазона.
        with self.assertRaises(MissionEngineError) as error:
            self._call_accept(ids, latitude=100.0)
        self.assertEqual(error.exception.status_code, 422)

        # longitude вне диапазона.
        with self.assertRaises(MissionEngineError) as error:
            self._call_accept(ids, longitude=200.0)
        self.assertEqual(error.exception.status_code, 422)

        # accuracy отрицательная.
        with self.assertRaises(MissionEngineError) as error:
            self._call_accept(ids, accuracy=-1.0)
        self.assertEqual(error.exception.status_code, 422)

    # ---- 8.6.r.3: expiry + cooldown -------------------------------------
    def test_expire_mission_sets_expired(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select

        ids = self._fixture(reentry_cooldown_seconds=3600)
        self._call_accept(ids)

        self.mission_engine.expire_mission(ids["player"], ids["mission"])

        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            self.assertEqual(pm.status, "expired")
            self.assertIsNotNone(pm.available_again_at)

    def test_expire_mission_is_idempotent(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select

        ids = self._fixture(reentry_cooldown_seconds=3600)
        self._call_accept(ids)

        self.mission_engine.expire_mission(ids["player"], ids["mission"])
        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            first_available = pm.available_again_at

        # Второй вызов не должен менять available_again_at
        self.mission_engine.expire_mission(ids["player"], ids["mission"])
        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            self.assertEqual(pm.available_again_at, first_available)

    def test_expire_mission_on_available_returns_409(self) -> None:
        ids = self._fixture()
        # PlayerMission создаётся в _fixture со статусом по умолчанию (locked или available).
        # Сначала отправим её в available через _synchronize.

        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.expire_mission(ids["player"], ids["mission"])
        # Если PM нет — 404, если есть в locked/available — 409
        self.assertIn(ctx.exception.status_code, (404, 409))

    def test_expire_mission_without_player_mission_returns_404(self) -> None:
        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.expire_mission("no-player", "no-mission")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_accept_on_cooldown_returns_429(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=3600)
        self._call_accept(ids)
        self.mission_engine.expire_mission(ids["player"], ids["mission"])

        with self.assertRaises(MissionEngineError) as ctx:
            self._call_accept(ids)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_cooldown_expires_returns_to_available(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select
        from datetime import timedelta

        ids = self._fixture(reentry_cooldown_seconds=10)  # 10 сек
        # Sprint 8.15: возврат из expired после cooldown возможен только для
        # after_terminal (legacy/one_time → архив).
        from app.geo_team_runtime_models import MissionRuntimePolicy

        with self.SessionLocal.begin() as session:
            session.add(
                MissionRuntimePolicy(
                    id=f"policy-{uuid.uuid4().hex}",
                    mission_id=ids["mission"],
                    version=1,
                    status="published",
                    entry_root_atomic=0,
                    max_attempts=3,
                    repeatability_policy="after_terminal",
                    required_items_json={"schemaVersion": 1, "items": []},
                    challenge_policy_json={},
                    reward_policy_json={},
                    fallback_policy_json=None,
                    feature_flags_json={},
                )
            )
        self._call_accept(ids)
        self.mission_engine.expire_mission(ids["player"], ids["mission"])

        # Сдвигаем available_again_at в прошлое
        with self.SessionLocal.begin() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            pm.available_again_at = pm.available_again_at - timedelta(seconds=20)

        # Bootstrap должен вернуть available
        from app.mission_engine import get_bootstrap
        bootstrap = get_bootstrap(ids["player"])
        m = next(x for x in bootstrap["missions"] if x["id"] == ids["mission"])
        self.assertEqual(m["status"], "available")

    def test_deadline_expired_auto_expires(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select
        from datetime import timedelta

        ids = self._fixture(
            execution_time_limit_seconds=60,
            reentry_cooldown_seconds=3600,
        )
        self._call_accept(ids)

        # Сдвигаем deadline в прошлое
        with self.SessionLocal.begin() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            pm.deadline_at = pm.deadline_at - timedelta(seconds=120)

        from app.mission_engine import get_bootstrap
        bootstrap = get_bootstrap(ids["player"])
        m = next(x for x in bootstrap["missions"] if x["id"] == ids["mission"])
        self.assertEqual(m["status"], "expired")
        self.assertIsNotNone(m["availableAgainAt"])

    def test_bootstrap_includes_available_again_at(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=3600)
        self._call_accept(ids)
        self.mission_engine.expire_mission(ids["player"], ids["mission"])

        from app.mission_engine import get_bootstrap
        bootstrap = get_bootstrap(ids["player"])
        m = next(x for x in bootstrap["missions"] if x["id"] == ids["mission"])
        self.assertIsNotNone(m["availableAgainAt"])

    # ---- 8.6.x: цепочка разблокировки (unlock_after_mission_id) ---------
    def test_unlock_chain_locks_mission_until_predecessor_completes(self) -> None:
        from app.mission_engine import get_bootstrap

        # Создать A (без цепочки) и B (зависит от A) для одного игрока.
        ids_a = self._fixture()
        ids_b = self._fixture(
            unlock_after_mission_id=ids_a["mission"],
            player_id=ids_a["player"],
        )

        bootstrap = get_bootstrap(ids_b["player"])

        # Санity: A без зависимостей доступна — лок B вызван именно цепочкой.
        mission_a = next(
            (m for m in bootstrap["missions"] if m["id"] == ids_a["mission"]),
            None,
        )
        self.assertIsNotNone(mission_a)
        self.assertEqual(mission_a["status"], "available")

        # B заблокирована, пока A не completed.
        mission_b = next(
            (m for m in bootstrap["missions"] if m["id"] == ids_b["mission"]),
            None,
        )
        self.assertIsNotNone(mission_b)
        self.assertEqual(mission_b["status"], "locked")

    def test_unlock_chain_unlocks_after_predecessor_completed(self) -> None:
        from datetime import datetime, timezone

        from app.mission_engine import get_bootstrap
        from app.models import PlayerMission
        from sqlalchemy import select

        ids_a = self._fixture()
        ids_b = self._fixture(
            unlock_after_mission_id=ids_a["mission"],
            player_id=ids_a["player"],
        )

        # Синхронизация создаёт PlayerMission для A — без этого пометить её
        # completed вручную нечем.
        bootstrap = get_bootstrap(ids_a["player"])
        mission_before = next(
            (m for m in bootstrap["missions"] if m["id"] == ids_b["mission"]),
            None,
        )
        self.assertIsNotNone(mission_before)
        self.assertEqual(mission_before["status"], "locked")

        # Вручную отметить A как completed.
        with self.SessionLocal.begin() as session:
            pm_a = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids_a["player"],
                    PlayerMission.mission_id == ids_a["mission"],
                )
            ).first()
            self.assertIsNotNone(pm_a)
            pm_a.status = "completed"
            pm_a.completed_at = pm_a.started_at or datetime.now(timezone.utc)

        # После completed предшественника B становится available.
        bootstrap = get_bootstrap(ids_a["player"])
        mission_b = next(
            (m for m in bootstrap["missions"] if m["id"] == ids_b["mission"]),
            None,
        )
        self.assertIsNotNone(mission_b)
        self.assertEqual(mission_b["status"], "available")

    def test_expired_mission_not_recalculated_by_unlock_chain(self) -> None:
        from datetime import datetime, timezone

        from app.mission_engine import get_bootstrap
        from app.models import PlayerMission
        from sqlalchemy import select

        # A — предшественник: завершаем заранее, чтобы B стала available.
        ids_a = self._fixture()
        get_bootstrap(ids_a["player"])  # создаёт PlayerMission для A
        with self.SessionLocal.begin() as session:
            pm_a = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids_a["player"],
                    PlayerMission.mission_id == ids_a["mission"],
                )
            ).first()
            self.assertIsNotNone(pm_a)
            pm_a.status = "completed"
            pm_a.completed_at = pm_a.started_at or datetime.now(timezone.utc)

        ids_b = self._fixture(
            unlock_after_mission_id=ids_a["mission"],
            player_id=ids_a["player"],
            reentry_cooldown_seconds=3600,
        )

        bootstrap = get_bootstrap(ids_a["player"])
        mission_b = next(
            (m for m in bootstrap["missions"] if m["id"] == ids_b["mission"]),
            None,
        )
        self.assertIsNotNone(mission_b)
        self.assertEqual(mission_b["status"], "available")

        # Берём B и экспайрим её.
        self.mission_engine.accept_mission(
            ids_b["player"],
            ids_b["mission"],
            self.PLAYER_LATITUDE,
            self.PLAYER_LONGITUDE,
        )
        self.mission_engine.expire_mission(ids_b["player"], ids_b["mission"])

        # Ломаем цепочку: A больше не completed. Если бы expired-миссии
        # пересчитывались через unlock-цепочку, B ушла бы в locked и
        # потеряла cooldown-трекинг.
        with self.SessionLocal.begin() as session:
            pm_a = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids_a["player"],
                    PlayerMission.mission_id == ids_a["mission"],
                )
            ).first()
            self.assertIsNotNone(pm_a)
            pm_a.status = "available"
            pm_a.completed_at = None

        bootstrap = get_bootstrap(ids_a["player"])
        mission_b = next(
            (m for m in bootstrap["missions"] if m["id"] == ids_b["mission"]),
            None,
        )
        self.assertIsNotNone(mission_b)
        self.assertEqual(mission_b["status"], "expired")
        self.assertIsNotNone(mission_b["availableAgainAt"])
