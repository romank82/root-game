"""Sprint 8.x-2b-2b: семантика волн командной мини-игры (cipher).

Фиксирует поведение _submit_wave_answer (8.x-2b-1/2a):
- волна 'passed' + миссия 'succeeded', когда сыграли ВСЕ активные члены;
- волна 'playing' («ждём остальных»), пока не все сыграли;
- провал одного = провал волны для всех: переход к следующей волне,
  при исчерпании волн — миссия 'failed' с terminal_at;
- мусорный формат sequence → 400 «Некорректный формат ответа.» без смены
  статусов (hotfix 8.x-2b-1);
- награды, полученные за верный ответ в волне, которая затем провалилась
  другим игроком, остаются в ledger (осознанное решение).

Логику не меняем — только поведение. Race-сценарий (параллельные submit)
на SQLite НЕ покрыт: with_for_update — no-op, проверить на PostgreSQL позже.

Фабрики скопированы минимально из test_team_missions_service.py (приватные
методы класса) — существующий файл не трогаем.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError
from app.team_missions_service import (
    activate_session_entrypoint,
    create_team_session_entrypoint,
    join_team_session,
    mark_ready_entrypoint,
    submit_wave_answer_entrypoint,
)
from tests.test_geo_team_contract import valid_team_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class TeamWaveFlowTests(unittest.TestCase):
    """8.x-2b: волны командной мини-игры (cipher) в _submit_wave_answer."""

    @classmethod
    def setUpClass(cls) -> None:
        # Изолированная SQLite-БД через alembic head; SessionLocal патчится на
        # уровне app.db (сервисы импортируют его лениво) — как в
        # TeamMissionsServiceTests.
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-team-wave-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "team_wave.sqlite3"
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

        cls._session_local_patch = patch("app.db.SessionLocal", cls.SessionLocal)
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures (копия минимального набора из test_team_missions_service.py) ----

    def _make_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=f"Player-{player_id[-6:]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_team_mission(self, *, validation_config: dict | None = None) -> str:
        from app.models import Chapter, Mission, Season

        suffix = uuid.uuid4().hex
        config = valid_team_config() if validation_config is None else validation_config
        with self.SessionLocal.begin() as session:
            season = Season(
                id=f"season-{suffix}",
                slug=f"season-{suffix}",
                title="Season",
            )
            session.add(season)
            session.flush()
            chapter = Chapter(
                id=f"chapter-{suffix}",
                season_id=season.id,
                slug=f"chapter-{suffix}",
                title="Chapter",
            )
            session.add(chapter)
            session.flush()
            session.add(
                Mission(
                    id=f"mission-{suffix}",
                    chapter_id=chapter.id,
                    slug=f"mission-{suffix}",
                    mission_type="team",
                    mission_category="team",
                    title="Wave mission",
                    status="published",
                    content={},
                    validation_config=config,
                )
            )
        return f"mission-{suffix}"

    def _seed_item(self, item_id: str) -> None:
        from app.models import Item

        with self.SessionLocal.begin() as session:
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}-{uuid.uuid4().hex[:8]}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="Team key",
                    description="Team mission entry key",
                    symbol="◇",
                    category="key",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )

    def _seed_root_wallet(self, player_id: str, amount: int) -> None:
        from app.models import Wallet, WalletTransaction

        with self.SessionLocal.begin() as session:
            wallet = Wallet(
                id=f"wallet-{uuid.uuid4().hex}",
                player_id=player_id,
                currency="ROOT",
                available_balance=amount,
                locked_balance=0,
            )
            session.add(wallet)
            session.flush()
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet.id,
                    amount=amount,
                    balance_after=amount,
                    transaction_type="credit",
                    reason="Test seed balance",
                    reference_type="test_seed",
                    reference_id=f"seed-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )

    def _seed_key(self, player_id: str, item_id: str, quantity: int) -> None:
        from app.models import PlayerItem

        with self.SessionLocal.begin() as session:
            session.add(
                PlayerItem(
                    id=f"player-item-{uuid.uuid4().hex}",
                    player_id=player_id,
                    item_id=item_id,
                    quantity=quantity,
                )
            )

    def _seed_geo_zone(self, *, slug: str) -> None:
        from app.models import GeoZone

        with self.SessionLocal.begin() as session:
            session.add(
                GeoZone(
                    id=f"geo-zone-{uuid.uuid4().hex}",
                    slug=slug,
                    title="Central Park",
                    description="Test geo zone",
                    zone_type="radius",
                    status="published",
                    sort_order=0,
                    latitude=55.7558,
                    longitude=37.6173,
                    radius_meters=500,
                    polygon_coordinates=None,
                    timezone="UTC",
                    starts_at=None,
                    ends_at=None,
                    max_location_accuracy_meters=None,
                    minimum_presence_seconds=0,
                )
            )

    def _make_wave_session(
        self,
        players: list[str],
        *,
        max_attempts: int = 3,
        with_rewards: bool = False,
    ) -> tuple[str, str | None]:
        """Активная сессия с инициализированной волной 1 (полный флоу).

        mission(valid config) → create_team_session → join остальных → все
        ready → verified proofs → activate (волна 1 генерируется сервисом).
        Возвращает (session_id, reward_item_id | None).
        """
        config = valid_team_config()
        config["team"]["maxMembers"] = max(len(players), config["team"]["maxMembers"])
        config["team"]["minMembers"] = min(len(players), config["team"]["minMembers"])
        config["attempts"]["maxAttempts"] = max_attempts
        config["attempts"]["rewardMultipliers"] = [1.0] * max_attempts
        zone_slug = f"zone-{uuid.uuid4().hex}"
        self._seed_geo_zone(slug=zone_slug)
        config["geo"]["zoneId"] = zone_slug

        entry_item_id = f"item-{uuid.uuid4().hex}"
        config["economy"]["requiredItems"] = [{"itemId": entry_item_id, "quantity": 1}]
        self._seed_item(entry_item_id)
        mission_id = self._make_team_mission(validation_config=config)
        session_id = create_team_session_entrypoint(players[0], mission_id)["id"]
        for player_id in players[1:]:
            join_team_session(player_id, session_id)
        for player_id in players:
            self._seed_root_wallet(player_id, 100)
            self._seed_key(player_id, entry_item_id, 1)
        for player_id in players:
            mark_ready_entrypoint(player_id, session_id)
        self._seed_proofs(session_id, players, config)
        activate_session_entrypoint(players[0], session_id)

        reward_item_id = None
        if with_rewards:
            reward_item_id = self._make_team_mission_rewards(session_id)
        return session_id, reward_item_id

    def _seed_proofs(
        self,
        session_id: str,
        players: list[str],
        config: dict,
    ) -> None:
        from app.geo_team_runtime_models import LocationProof

        zone_id = config["geo"]["zoneId"]
        freshness = config["geo"]["proofFreshnessSeconds"]
        now = datetime.now(timezone.utc)
        with self.SessionLocal.begin() as session:
            for player_id in players:
                session.add(
                    LocationProof(
                        id=f"location-proof-{uuid.uuid4().hex}",
                        player_id=player_id,
                        provider="dev_mock",
                        status="verified",
                        zone_id=zone_id,
                        verifier_reference=None,
                        issued_at=now,
                        expires_at=now + timedelta(seconds=freshness),
                    )
                )

    def _make_team_mission_rewards(
        self,
        session_id: str,
        *,
        root_amount: int = 10,
        item_amount: int = 1,
    ) -> str:
        """Key-item (published + KeyRules) и MissionReward (ROOT + item)."""

        from app.geo_team_runtime_models import TeamSession
        from app.models import Item, KeyRules, MissionReward

        item_id = f"item-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            team_session = session.get(TeamSession, session_id)
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}-{uuid.uuid4().hex[:8]}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="Team reward key",
                    description="Team mission reward key",
                    symbol="★",
                    category="key",
                    rarity="epic",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )
            session.add(
                KeyRules(
                    id=f"key-rules-{uuid.uuid4().hex}",
                    item_id=item_id,
                    is_consumable=True,
                )
            )
            session.flush()
            mission_id = team_session.mission_id
            session.add(
                MissionReward(
                    id=f"reward-{uuid.uuid4().hex}",
                    mission_id=mission_id,
                    reward_type="currency",
                    amount=root_amount,
                    reward_value={"currency": "ROOT"},
                    sort_order=1,
                )
            )
            session.add(
                MissionReward(
                    id=f"reward-{uuid.uuid4().hex}",
                    mission_id=mission_id,
                    reward_type="item",
                    item_id=item_id,
                    amount=item_amount,
                    reward_value={},
                    sort_order=2,
                )
            )
        return item_id

    # ---- Хелперы чтения -------------------------------------------------

    def _get_session(self, session_id: str):
        from app.geo_team_runtime_models import TeamSession

        with self.SessionLocal() as session:
            return session.get(TeamSession, session_id)

    def _root_balance(self, player_id: str) -> int:
        from app.models import Wallet

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            return wallet.available_balance if wallet is not None else 0

    def _correct_code(self, session_id: str) -> list[str]:
        team_session = self._get_session(session_id)
        self.assertIsNotNone(team_session.current_cipher_session)
        return list(team_session.current_cipher_session["correct_code"])

    def _snapshot(self, session_id: str) -> dict:
        team_session = self._get_session(session_id)
        return {
            "status": team_session.status,
            "terminal_at": team_session.terminal_at,
            "current_wave": team_session.current_wave,
            "max_waves": team_session.max_waves,
            "wave_status": team_session.wave_status,
            "wave_played_members": list(team_session.wave_played_members or []),
            "current_cipher_session": team_session.current_cipher_session,
        }

    def _wrong_sequence(self) -> list[str]:
        # '#' не входит в CIPHER_ALPHABET (A-Z0-9) — гарантированно не совпадёт
        # с correct_code любой длины из алфавита.
        return ["#", "#", "#", "#"]

    def _set_wave_played(self, session_id: str, players: list[str]) -> None:
        """Явно задать wave_played_members (паттерн _set_member_status)."""

        from app.geo_team_runtime_models import TeamSession

        with self.SessionLocal.begin() as session:
            team_session = session.get(TeamSession, session_id)
            team_session.wave_played_members = players

    def _awarded_snapshot(self, session_id: str, player_id: str):
        """awarded_snapshot игрока в этой сессии (или None). 8.x-4-final-status-1."""

        from app.geo_team_runtime_models import TeamSessionMember

        with self.SessionLocal() as session:
            member = session.scalar(
                select(TeamSessionMember).where(
                    TeamSessionMember.team_session_id == session_id,
                    TeamSessionMember.player_id == player_id,
                )
            )
            return member.awarded_snapshot if member is not None else None

    def _serialize(self, session_id: str, player_id: str) -> dict:
        """Сериализовать сессию для игрока (тот же путь, что фронт получит)."""

        from app.geo_team_runtime_models import TeamSession
        from app.team_missions_service import _serialize_team_session

        with self.SessionLocal() as session:
            team_session = session.get(TeamSession, session_id)
            return _serialize_team_session(session, team_session, player_id)

    # ---- 8.x-2b: семантика волн -----------------------------------------

    def test_wave_success_when_all_played(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b], with_rewards=True)

        code = self._correct_code(session_id)
        first = submit_wave_answer_entrypoint(player_a, session_id, code)
        second = submit_wave_answer_entrypoint(player_b, session_id, code)

        # Первый: награда сразу, но волна ещё ждёт второго.
        self.assertTrue(first["accepted"])
        self.assertEqual(first["waveStatus"], "playing")
        self.assertEqual(first["sessionStatus"], "active")
        self.assertGreater(first["awarded"]["root"], 0)
        self.assertTrue(first["awarded"]["items"])

        # Второй: все сыграли → passed + миссия succeeded.
        self.assertTrue(second["accepted"])
        self.assertEqual(second["waveStatus"], "passed")
        self.assertEqual(second["sessionStatus"], "succeeded")
        self.assertGreater(second["awarded"]["root"], 0)

        snap = self._snapshot(session_id)
        self.assertEqual(snap["wave_status"], "passed")
        self.assertEqual(snap["status"], "succeeded")
        self.assertIsNotNone(snap["terminal_at"])
        self.assertIsNone(snap["current_cipher_session"])
        self.assertEqual(set(snap["wave_played_members"]), {player_a, player_b})

    def test_wave_stays_playing_when_not_all_played(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])

        code = self._correct_code(session_id)
        result = submit_wave_answer_entrypoint(player_a, session_id, code)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["waveStatus"], "playing")
        self.assertEqual(result["sessionStatus"], "active")

        snap = self._snapshot(session_id)
        self.assertEqual(snap["wave_status"], "playing")
        self.assertEqual(snap["status"], "active")
        self.assertEqual(snap["current_wave"], 1)
        self.assertEqual(snap["wave_played_members"], [player_a])
        self.assertIsNotNone(snap["current_cipher_session"])

    def test_wave_failed_advances_to_next(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])

        team_session_before = self._get_session(session_id)
        old_cipher = team_session_before.current_cipher_session
        old_code = list(old_cipher["correct_code"])

        result = submit_wave_answer_entrypoint(
            player_a, session_id, self._wrong_sequence()
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["waveStatus"], "playing")
        self.assertEqual(result["currentWave"], 2)
        self.assertEqual(result["sessionStatus"], "active")

        snap = self._snapshot(session_id)
        self.assertEqual(snap["wave_status"], "playing")
        self.assertEqual(snap["status"], "active")
        self.assertEqual(snap["current_wave"], 2)
        self.assertEqual(snap["wave_played_members"], [])
        self.assertIsNotNone(snap["current_cipher_session"])
        # Волна 2 — свежая cipher-сессия (новый dict, иной код).
        self.assertIsNot(snap["current_cipher_session"], old_cipher)
        self.assertNotEqual(list(snap["current_cipher_session"]["correct_code"]), old_code)

    def test_last_wave_failed_finalizes_mission(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        # max_attempts=1: единственная волна — ошибка сразу финализирует миссию.
        session_id, _ = self._make_wave_session([player_a, player_b], max_attempts=1)

        result = submit_wave_answer_entrypoint(
            player_a, session_id, self._wrong_sequence()
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["waveStatus"], "failed")
        self.assertEqual(result["sessionStatus"], "failed")
        self.assertEqual(result["currentWave"], 2)  # 2 > max_waves=1
        self.assertEqual(result["maxWaves"], 1)

        snap = self._snapshot(session_id)
        self.assertEqual(snap["status"], "failed")
        self.assertEqual(snap["wave_status"], "failed")
        self.assertEqual(snap["current_wave"], 2)
        self.assertIsNotNone(snap["terminal_at"])
        self.assertIsNone(snap["current_cipher_session"])

    def test_member_already_played_returns_409(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])

        # Ветка «уже сыграл в этой волне» (#7) проверяется при состоянии:
        # игрок уже в wave_played_members, MissionRun ещё active. Напрямую
        # такой submit невозможен (верный ответ сразу завершает MissionRun →
        # повтор ловится раньше как «Вы уже завершили миссию.»), поэтому
        # волновое состояние задаём явно (паттерн _set_member_status).
        self._set_wave_played(session_id, [player_a])
        before = self._snapshot(session_id)

        with self.assertRaises(MissionEngineError) as captured:
            submit_wave_answer_entrypoint(
                player_a, session_id, self._correct_code(session_id)
            )

        # Ответ отклонён, состояние волны и статусы не тронуты.
        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Вы уже сыграли в этой волне.")
        self.assertEqual(self._snapshot(session_id), before)

    def test_garbage_sequence_returns_400_without_wave_change(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])
        before = self._snapshot(session_id)

        for garbage in (None, "ROOT", [1, 2, 3]):
            with self.subTest(garbage=garbage):
                with self.assertRaises(MissionEngineError) as captured:
                    submit_wave_answer_entrypoint(player_a, session_id, garbage)
                self.assertEqual(captured.exception.status_code, 400)
                self.assertEqual(
                    captured.exception.detail, "Некорректный формат ответа."
                )

        after = self._snapshot(session_id)
        self.assertEqual(after, before)
        self.assertEqual(after["wave_status"], "playing")
        self.assertEqual(after["current_wave"], 1)
        self.assertEqual(after["wave_played_members"], [])
        self.assertEqual(after["status"], "active")
        self.assertIsNotNone(after["current_cipher_session"])

    def test_partial_play_does_not_set_wave_passed(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        player_c = self._make_player()
        session_id, _ = self._make_wave_session(
            [player_a, player_b, player_c], with_rewards=True
        )

        code = self._correct_code(session_id)
        first = submit_wave_answer_entrypoint(player_a, session_id, code)
        second = submit_wave_answer_entrypoint(player_b, session_id, code)

        self.assertEqual(first["waveStatus"], "playing")
        self.assertEqual(second["waveStatus"], "playing")
        self.assertEqual(second["sessionStatus"], "active")
        self.assertGreater(second["awarded"]["root"], 0)

        snap = self._snapshot(session_id)
        self.assertEqual(snap["wave_status"], "playing")  # НЕ passed
        self.assertEqual(snap["status"], "active")
        self.assertEqual(snap["current_wave"], 1)
        self.assertEqual(set(snap["wave_played_members"]), {player_a, player_b})
        self.assertIsNotNone(snap["current_cipher_session"])

    def test_rewards_kept_after_wave_failure(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b], with_rewards=True)

        balance_before = self._root_balance(player_a)
        code = self._correct_code(session_id)
        correct = submit_wave_answer_entrypoint(player_a, session_id, code)
        self.assertEqual(correct["waveStatus"], "playing")
        self.assertGreater(self._root_balance(player_a), balance_before)

        # Второй ошибается — волна провалена для всех, переход на волну 2.
        wrong = submit_wave_answer_entrypoint(
            player_b, session_id, self._wrong_sequence()
        )
        self.assertFalse(wrong["accepted"])
        self.assertEqual(wrong["waveStatus"], "playing")
        self.assertEqual(wrong["currentWave"], 2)

        snap = self._snapshot(session_id)
        self.assertEqual(snap["current_wave"], 2)
        self.assertEqual(snap["wave_played_members"], [])

        # Награда первого за волну 1 осталась в ledger (осознанное решение).
        self.assertEqual(self._root_balance(player_a), balance_before + 10)

    # ---- 8.x-4-final-status-1: снапшот наград в TeamSessionMember ----------

    def test_awarded_snapshot_written_on_success(self) -> None:
        """Оба игрока верно ответили → у КАЖДОГО в awarded_snapshot свои награды."""
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session(
            [player_a, player_b], with_rewards=True
        )

        code = self._correct_code(session_id)
        first = submit_wave_answer_entrypoint(player_a, session_id, code)
        self.assertEqual(first["accepted"], True)
        self.assertEqual(first["sessionStatus"], "active")  # B ещё не сыграл

        second = submit_wave_answer_entrypoint(player_b, session_id, code)
        self.assertEqual(second["accepted"], True)
        self.assertEqual(second["sessionStatus"], "succeeded")

        for player_id in (player_a, player_b):
            snap = self._awarded_snapshot(session_id, player_id)
            self.assertIsInstance(snap, dict)
            self.assertEqual(snap["root"], 10)  # ROOT-награда из _make_team_mission_rewards
            self.assertIsInstance(snap["items"], list)
            self.assertEqual(len(snap["items"]), 1)
            self.assertEqual(snap["items"][0]["quantity"], 1)
            self.assertIsInstance(snap["storyNodeIds"], list)
            self.assertEqual(snap["storyNodeIds"], [])

        self.assertEqual(self._snapshot(session_id)["status"], "succeeded")

    def test_awarded_snapshot_none_on_failure(self) -> None:
        """Ошибка ответа → наград нет, awarded_snapshot остаётся None."""
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])

        wrong = submit_wave_answer_entrypoint(
            player_a, session_id, self._wrong_sequence()
        )
        self.assertFalse(wrong["accepted"])
        self.assertEqual(wrong["sessionStatus"], "active")  # остались волны

        self.assertIsNone(self._awarded_snapshot(session_id, player_a))
        self.assertIsNone(self._awarded_snapshot(session_id, player_b))

    def test_awarded_snapshot_kept_after_team_failure(self) -> None:
        """A верно ответил (снапшот записан), B ошибается (волна провалена
        для всех) → награда A остаётся зафиксированной, у B — None."""
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session(
            [player_a, player_b], with_rewards=True
        )

        code = self._correct_code(session_id)
        correct = submit_wave_answer_entrypoint(player_a, session_id, code)
        self.assertEqual(correct["accepted"], True)
        self.assertEqual(correct["waveStatus"], "playing")

        wrong = submit_wave_answer_entrypoint(
            player_b, session_id, self._wrong_sequence()
        )
        self.assertFalse(wrong["accepted"])
        self.assertEqual(wrong["currentWave"], 2)
        self.assertEqual(wrong["waveStatus"], "playing")  # свежая волна 2

        snap = self._snapshot(session_id)
        self.assertEqual(snap["current_wave"], 2)
        self.assertEqual(snap["status"], "active")

        # Награда A за волну 1 осталась и зафиксирована в снапшоте.
        snap_a = self._awarded_snapshot(session_id, player_a)
        self.assertIsNotNone(snap_a)
        self.assertEqual(snap_a["root"], 10)
        self.assertEqual(len(snap_a["items"]), 1)
        # Ошибившийся B наград не получал.
        self.assertIsNone(self._awarded_snapshot(session_id, player_b))

    # ---- 8.x-3: сериализация игрового состояния волн --------------------

    def test_serialize_includes_wave_fields(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])
        code = self._correct_code(session_id)

        payload = self._serialize(session_id, player_a)

        # Контракт submit-wave: "sessionStatus" не дублируем — у сериализатора
        # уже есть "status".
        self.assertEqual(payload["status"], "active")
        self.assertNotIn("sessionStatus", payload)
        # Старые поля на месте.
        self.assertEqual(payload["memberCount"], 2)
        self.assertEqual(payload["myStatus"], "ready")
        # Новые игровые поля.
        self.assertEqual(payload["currentWave"], 1)
        self.assertEqual(payload["maxWaves"], 3)  # attempts.maxAttempts из конфига
        self.assertEqual(payload["waveStatus"], "playing")
        self.assertEqual(payload["wavePlayedCount"], 0)
        self.assertFalse(payload["myWavePlayed"])
        self.assertIsNotNone(payload["cipherSession"])
        self.assertEqual(
            set(payload["cipherSession"].keys()),
            {"correctCode", "drums", "timeLimitSeconds"},
        )
        self.assertEqual(payload["cipherSession"]["correctCode"], code)
        self.assertIsInstance(payload["cipherSession"]["drums"], list)
        self.assertTrue(payload["cipherSession"]["drums"])
        self.assertTrue(
            all(isinstance(drum, list) for drum in payload["cipherSession"]["drums"])
        )

    def test_serialize_my_wave_played_true_after_submit(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])

        code = self._correct_code(session_id)
        submit_wave_answer_entrypoint(player_a, session_id, code)

        payload_a = self._serialize(session_id, player_a)
        self.assertTrue(payload_a["myWavePlayed"])
        self.assertEqual(payload_a["wavePlayedCount"], 1)
        self.assertEqual(payload_a["waveStatus"], "playing")
        self.assertEqual(payload_a["currentWave"], 1)
        self.assertEqual(payload_a["status"], "active")

        # Второй игрок ещё не сыграл — его флаг False, счётчик тот же.
        payload_b = self._serialize(session_id, player_b)
        self.assertFalse(payload_b["myWavePlayed"])
        self.assertEqual(payload_b["wavePlayedCount"], 1)

    def test_serialize_cipher_session_none_after_finalize(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id, _ = self._make_wave_session([player_a, player_b])

        code = self._correct_code(session_id)
        submit_wave_answer_entrypoint(player_a, session_id, code)
        submit_wave_answer_entrypoint(player_b, session_id, code)

        payload = self._serialize(session_id, player_a)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["waveStatus"], "passed")
        self.assertIsNone(payload["cipherSession"])
        self.assertEqual(payload["wavePlayedCount"], 2)
        self.assertTrue(payload["myWavePlayed"])


if __name__ == "__main__":
    unittest.main()
