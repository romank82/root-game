"""Unit-тесты read-only админ-эндпоинтов игроков (шаг 5.3).

Unit-style: fake-объекты (SimpleNamespace) вместо реальной БД и TestClient
(по образцу test_admin_reward_pools.py). FakeSession диспатчит запросы по
скомпиленному SQL c literal binds и не имеет методов записи — любой write
в read-only карточке упал бы с AttributeError.
"""
from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_players import (
    AGE_MAX,
    AGE_MIN,
    MISSION_HISTORY_LIMIT,
    PROFILE_FIELDS,
    VALID_GENDERS,
    _get_player_or_404,
    _serialize_player_card,
    _serialize_player_summary,
    get_profile_fields,
)


def _literal_sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def _dt(offset_days: int = 1) -> datetime:
    return datetime(2026, 10, offset_days, 10, 0, 0)


def _player(**overrides) -> SimpleNamespace:
    base = {
        "id": "player-1",
        "display_name": "Иван Петров",
        "auth_provider": "telegram",
        "external_id": "987654321",
        "status": "active",
        "nickname": None,
        "country": None,
        "gender": None,
        "age": None,
        "telegram_username": "@ivan",
        "telegram_username_normalized": "ivan",
        "telegram_first_name": "Иван",
        "telegram_last_name": "Петров",
        "telegram_photo_url": "https://example.com/photo.jpg",
        "created_at": _dt(1),
        "updated_at": _dt(2),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _wallet(**overrides) -> SimpleNamespace:
    base = {
        "id": "wallet-1",
        "player_id": "player-1",
        "currency": "ROOT",
        "available_balance": 1500,
        "locked_balance": 0,
        "created_at": _dt(1),
        "updated_at": _dt(2),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _item(**overrides) -> SimpleNamespace:
    base = {
        "id": "item-1",
        "slug": "item-slug",
        "code": "ITEM",
        "title": "Предмет",
        "symbol": "key_icon",
        "category": "key",
        "rarity": "common",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _player_item(**overrides) -> SimpleNamespace:
    base = {
        "id": "player-item-1",
        "player_id": "player-1",
        "item_id": "item-1",
        "quantity": 1,
        "obtained_from_type": "mission_reward",
        "obtained_from_id": "mission-1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _mission(**overrides) -> SimpleNamespace:
    base = {
        "id": "mission-1",
        "slug": "mission-slug",
        "title": "Миссия",
        "mission_type": "geo",
        "status": "published",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _pm(status: str, completed: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"player-mission-{status}",
        player_id="player-1",
        mission_id="mission-1",
        status=status,
        attempt_count=2,
        progress={},
        started_at=_dt(1),
        completed_at=_dt(2) if completed else None,
    )


def _restriction(**overrides) -> SimpleNamespace:
    base = {
        "id": "restr-1",
        "restriction_type": "transfer_restricted",
        "status": "active",
        "reason": "причина",
        "evidence": "скрин",
        "admin_id": "admin-1",
        "starts_at": _dt(1),
        "expires_at": None,
        "approval_request_id": "ar-1",
        "revoked_at": None,
        "revocation_reason": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _tx(**overrides) -> SimpleNamespace:
    base = {
        "id": "tx-1",
        "wallet_id": "wallet-1",
        "amount": 3000,
        "balance_after": 3500,
        "transaction_type": "credit",
        "reason": "mission_reward",
        "reference_type": "player_mission",
        "reference_id": "pm-1",
        "metadata_json": {"missionId": "m1"},
        "created_at": _dt(1),
    }
    base.update(overrides)
    return SimpleNamespace(**base)

class FakeSession:
    """Fake-сессия ровно для тех вызовов, что делает _serialize_player_card."""

    def __init__(self, *, player=None, wallet=None, inventory=(), active=(),
                 history=(), restrictions=(), transactions=(),
                 completed_count=0, earned=0, spent=0):
        self._player = player
        self._wallet = wallet
        self._inventory = list(inventory)
        self._active = list(active)
        self._history = list(history)
        self._restrictions = list(restrictions)
        self._transactions = list(transactions)
        self._completed_count = completed_count
        self._earned = earned
        self._spent = spent
        self.executed = []

    def get(self, model, player_id):  # noqa: ARG002
        return self._player if self._player and player_id == self._player.id else None

    def execute(self, statement):
        self.executed.append(statement)
        text = _literal_sql(statement)
        if "player_items" in text:
            rows = self._inventory
        elif "status IN (" in text:
            rows = self._active
        else:
            rows = self._history
        return SimpleNamespace(all=lambda: rows)

    def scalars(self, statement):
        self.executed.append(statement)
        text = _literal_sql(statement)
        rows = (
            self._restrictions
            if "player_restrictions" in text
            else self._transactions
        )
        return SimpleNamespace(all=lambda: rows)

    def scalar(self, statement):
        self.executed.append(statement)
        text = _literal_sql(statement)
        if "wallets" in text:
            return self._wallet
        if "coalesce" in text:
            return self._earned if "credit" in text else self._spent
        return self._completed_count


class AdminPlayerCardTests(unittest.TestCase):
    def test_get_player_returns_404_for_unknown_player(self):
        session = SimpleNamespace(get=lambda model, player_id: None)  # noqa: ARG005
        with self.assertRaises(HTTPException) as ctx:
            _get_player_or_404(session, "player-unknown")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_serialize_player_card_contains_all_top_level_blocks(self):
        fake = FakeSession(
            player=_player(),
            wallet=_wallet(),
            inventory=[(_player_item(), _item())],
            active=[(_pm("in_progress"), _mission())],
            history=[(_pm("completed", completed=True), _mission())],
            restrictions=[_restriction()],
            transactions=[_tx()],
            completed_count=1,
            earned=3000,
            spent=350,
        )
        card = _serialize_player_card(fake, fake._player)
        self.assertEqual(
            set(card.keys()),
            {
                "player",
                "wallet",
                "gasBalance",
                "inventory",
                "activeMissions",
                "missionHistory",
                "restrictions",
                "recentTransactions",
                "stats",
            },
        )

    def test_card_player_block_includes_external_id(self):
        fake = FakeSession(player=_player(external_id="987654321"), wallet=_wallet())
        card = _serialize_player_card(fake, fake._player)
        self.assertEqual(card["player"]["externalId"], "987654321")
        self.assertEqual(card["player"]["telegram"]["normalizedUsername"], "ivan")
        self.assertEqual(card["player"]["registeredAt"], "2026-10-01T10:00:00")
        self.assertEqual(card["player"]["lastActivityAt"], "2026-10-02T10:00:00")

    def test_serialize_summary_excludes_external_id(self):
        summary = _serialize_player_summary(_player(), _wallet())
        self.assertNotIn("externalId", summary)
        self.assertNotIn("external_id", summary)
        self.assertEqual(summary["id"], "player-1")
        self.assertEqual(summary["rootBalance"], 1500)
        self.assertEqual(summary["status"], "active")

    def test_card_returns_zero_wallet_when_missing(self):
        fake = FakeSession(player=_player(), wallet=None, completed_count=2)
        card = _serialize_player_card(fake, fake._player)
        self.assertEqual(
            card["wallet"],
            {"currency": "ROOT", "availableBalance": 0, "lockedBalance": 0},
        )
        self.assertEqual(card["recentTransactions"], [])
        self.assertEqual(card["stats"]["totalRootEarned"], 0)
        self.assertEqual(card["stats"]["totalRootSpent"], 0)
        self.assertEqual(card["stats"]["totalMissionsCompleted"], 2)

    def test_card_inventory_joins_item_details(self):
        fake = FakeSession(
            player=_player(),
            wallet=_wallet(),
            inventory=[
                (_player_item(quantity=5), _item(title="Ключ", slug="key-1"))
            ],
        )
        card = _serialize_player_card(fake, fake._player)
        row = card["inventory"][0]
        self.assertEqual(row["id"], "player-item-1")
        self.assertEqual(row["itemId"], "item-1")
        self.assertEqual(row["slug"], "key-1")
        self.assertEqual(row["title"], "Ключ")
        self.assertEqual(row["code"], "ITEM")
        self.assertEqual(row["quantity"], 5)
        self.assertEqual(row["obtainedFromType"], "mission_reward")
        self.assertEqual(row["obtainedFromId"], "mission-1")

    def test_card_active_missions_excludes_completed(self):
        fake = FakeSession(
            player=_player(),
            wallet=_wallet(),
            active=[
                (_pm("in_progress"), _mission(id="m-a")),
                (_pm("available"), _mission(id="m-b")),
            ],
            history=[(_pm("completed", completed=True), _mission(id="m-c"))],
        )
        card = _serialize_player_card(fake, fake._player)
        self.assertEqual(
            {m["missionId"] for m in card["activeMissions"]}, {"m-a", "m-b"}
        )
        self.assertEqual(
            [m["missionId"] for m in card["missionHistory"]], ["m-c"]
        )
        self.assertEqual(card["missionHistory"][0]["status"], "completed")
        self.assertEqual(
            card["missionHistory"][0]["completedAt"], "2026-10-02T10:00:00"
        )

    def test_card_transactions_redact_sensitive_metadata(self):
        tx = _tx(metadata_json={
            "password": "secret",
            "missionId": "m1",
            "nested": {"token": "tok", "itemId": "i1"},
        })
        fake = FakeSession(
            player=_player(), wallet=_wallet(), transactions=[tx]
        )
        card = _serialize_player_card(fake, fake._player)
        meta = card["recentTransactions"][0]["metadata"]
        self.assertEqual(meta["password"], "[REDACTED]")
        self.assertEqual(meta["missionId"], "m1")
        self.assertEqual(meta["nested"]["token"], "[REDACTED]")
        self.assertEqual(meta["nested"]["itemId"], "i1")

    def test_card_stats_aggregate_earned_spent(self):
        fake = FakeSession(
            player=_player(),
            wallet=_wallet(),
            completed_count=7,
            earned=5050,
            spent=1234,
        )
        card = _serialize_player_card(fake, fake._player)
        self.assertEqual(
            card["stats"],
            {
                "totalMissionsCompleted": 7,
                "totalRootEarned": 5050,
                "totalRootSpent": 1234,
            },
        )

    def test_card_mission_history_limited(self):
        fake = FakeSession(
            player=_player(),
            wallet=None,
            history=[(_pm("completed", completed=True), _mission())],
        )
        _serialize_player_card(fake, fake._player)
        history_sql = [
            _literal_sql(stmt)
            for stmt in fake.executed
            if "player_missions" in _literal_sql(stmt)
            and "ORDER BY" in _literal_sql(stmt)
        ]
        self.assertTrue(history_sql, "запрос истории миссий должен исполняться")
        self.assertIn(f"LIMIT {MISSION_HISTORY_LIMIT}", history_sql[0])

    def test_card_player_block_includes_profile_fields(self):
        player = _player(
            nickname="roman#123-456-789",
            country="RU",
            gender="male",
            age=30,
        )
        fake = FakeSession(player=player, wallet=_wallet())
        card = _serialize_player_card(fake, fake._player)
        self.assertEqual(card["player"]["nickname"], "roman#123-456-789")
        self.assertEqual(card["player"]["country"], "RU")
        self.assertEqual(card["player"]["gender"], "male")
        self.assertEqual(card["player"]["age"], 30)

        summary = _serialize_player_summary(player, _wallet())
        self.assertEqual(summary["nickname"], "roman#123-456-789")
        self.assertEqual(summary["country"], "RU")
        self.assertEqual(summary["gender"], "male")
        self.assertEqual(summary["age"], 30)

    def test_profile_fields_endpoint(self):
        result = get_profile_fields(_admin=SimpleNamespace())
        fields = result["fields"]
        self.assertEqual(
            {field["key"] for field in fields},
            {"nickname", "country", "gender", "age"},
        )
        by_key = {field["key"]: field for field in fields}
        self.assertEqual(by_key["nickname"]["readOnly"], True)
        self.assertEqual(by_key["country"]["maxLength"], 2)
        self.assertEqual(by_key["gender"]["type"], "select")
        self.assertEqual(set(by_key["gender"]["options"]), VALID_GENDERS)
        self.assertEqual(by_key["age"]["type"], "number")
        self.assertEqual(by_key["age"]["min"], AGE_MIN)
        self.assertEqual(by_key["age"]["max"], AGE_MAX)


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


class AdminPlayerListSearchTests(unittest.TestCase):
    """Поиск по нику в списке игроков (10.0.1, часть 1).

    Живая SQLite + alembic upgrade head (паттерн test_admin_economy.py):
    FakeSession диспатчит только карточные запросы, а list_admin_players
    исполняет select(func.count()) и outerjoin — нужна реальная схема.
    Каждый тест получает свежую disposable БД.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from app import admin_players

        cls.admin_players = admin_players
        cls._session_local_patch = None

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-players-search-"
        )
        self.database_path = Path(self._temporary_directory.name) / "players.sqlite3"
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

        @event.listens_for(self.engine, "connect")
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
        self._session_local_patch = patch.object(
            self.admin_players, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

    def tearDown(self) -> None:
        self._session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы ---------------------------------------------

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

    def _make_player(self, nickname: str) -> str:
        """Игрок с заполненными nickname/nickname_lower (как после 10.0)."""
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=f"Игрок {nickname}",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                    nickname=nickname,
                    nickname_lower=nickname.lower(),
                )
            )
        return player_id

    def test_list_players_search_by_nickname(self) -> None:
        admin = self._make_admin()
        roman_id = self._make_player("roman#123-456-789")
        other_id = self._make_player("other#999-888-777")

        def hit_ids(search_value: str) -> list[str]:
            result = self.admin_players.list_admin_players(
                search=search_value,
                _admin=admin,
            )
            return [player["id"] for player in result["players"]]

        # По нику целиком (case-insensitive, латиница).
        self.assertEqual(hit_ids("roman"), [roman_id])
        # Подстрока ника — тоже находится.
        self.assertEqual(hit_ids("123"), [roman_id])
        # Другой игрок находится по своему нику.
        self.assertEqual(hit_ids("other"), [other_id])
        # Несуществующий ник — пусто.
        self.assertEqual(hit_ids("nonexistent"), [])


class AdminPlayerProfilePatchTests(unittest.TestCase):
    """PATCH профиля (10.0.4, часть 1): country/gender/age + аудит.

    Живая SQLite + alembic upgrade head: PATCH пишет в БД (row lock),
    поэтому FakeSession не подходит. Прямой вызов
    update_admin_player_profile с request=None (fallback audit "cli:").
    """

    @classmethod
    def setUpClass(cls) -> None:
        from app import admin_players

        cls.admin_players = admin_players
        cls._session_local_patch = None

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-players-patch-"
        )
        self.database_path = Path(self._temporary_directory.name) / "players.sqlite3"
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

        @event.listens_for(self.engine, "connect")
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
        self._session_local_patch = patch.object(
            self.admin_players, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

    def tearDown(self) -> None:
        self._session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы ---------------------------------------------

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


    def _make_player(self) -> str:
        """Игрок без профиля (country/gender/age = None)."""
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="PATCH-игрок",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _get_player(self, player_id: str):
        from app.models import GamePlayer

        with self.SessionLocal() as session:
            return session.get(GamePlayer, player_id)

    def _call_patch(self, player_id, payload, admin):
        return self.admin_players.update_admin_player_profile(
            player_id, payload, request=None, admin=admin
        )

    def _find_profile_audits(self):
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return session.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "player.profile_updated"
                )
            ).all()

    def test_patch_player_profile(self) -> None:
        admin = self._make_admin()
        player_id = self._make_player()

        result = self._call_patch(
            player_id,
            self.admin_players.PlayerProfileUpdatePayload(
                country="ru", gender="male", age=30
            ),
            admin,
        )

        # Ответ — тот же формат, что у GET-карточки: {"player": card},
        # где card["player"] — блок игрока.
        card_player = result["player"]["player"]

        # Нормализация country: strip + upper.
        self.assertEqual(card_player["country"], "RU")
        self.assertEqual(card_player["gender"], "male")
        self.assertEqual(card_player["age"], 30)

        # Значения записались в БД.
        player = self._get_player(player_id)
        self.assertEqual(player.country, "RU")
        self.assertEqual(player.gender, "male")
        self.assertEqual(player.age, 30)

        # Audit: одна запись, before/after, changedFields.
        audits = self._find_profile_audits()
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.entity_id, player_id)
        self.assertEqual(audit.permission_code, "players.manage")
        self.assertEqual(
            audit.before_json, {"country": None, "gender": None, "age": None}
        )
        self.assertEqual(
            audit.after_json, {"country": "RU", "gender": "male", "age": 30}
        )
        self.assertEqual(
            audit.metadata_json,
            {"changedFields": ["country", "gender", "age"]},
        )


    def test_patch_player_profile_invalid_gender(self) -> None:
        admin = self._make_admin()
        player_id = self._make_player()

        with self.assertRaises(HTTPException) as ctx:
            self._call_patch(
                player_id,
                self.admin_players.PlayerProfileUpdatePayload(gender="unknown"),
                admin,
            )
        self.assertEqual(ctx.exception.status_code, 422)

        # Проверка не записана, аудит отсутствует.
        player = self._get_player(player_id)
        self.assertIsNone(player.gender)
        self.assertEqual(self._find_profile_audits(), [])

    def test_patch_player_profile_invalid_country(self) -> None:
        # "RUS" (3 буквы) не проходит Pydantic max_length=2 → 422 на маршруте.
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            self.admin_players.PlayerProfileUpdatePayload(country="RUS")

        # "A1" (ISO-2-форма, но не буквы) — 422 уже в эндпоинте.
        admin = self._make_admin()
        player_id = self._make_player()

        with self.assertRaises(HTTPException) as ctx:
            self._call_patch(
                player_id,
                self.admin_players.PlayerProfileUpdatePayload(country="a1"),
                admin,
            )
        self.assertEqual(ctx.exception.status_code, 422)

        player = self._get_player(player_id)
        self.assertIsNone(player.country)
        self.assertEqual(self._find_profile_audits(), [])

    def test_patch_player_profile_extra_field(self) -> None:
        # nickname (нередактируемое поле) запрещено extra=forbid → 422.
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            self.admin_players.PlayerProfileUpdatePayload(nickname="newnick")

        admin = self._make_admin()
        player_id = self._make_player()

        player = self._get_player(player_id)
        self.assertIsNone(player.nickname)
        self.assertEqual(self._find_profile_audits(), [])


class AdminPlayerGasPatchTests(unittest.TestCase):
    """PATCH газа (10.4-c-2): начислить/списать + аудит + проводки.

    Живая SQLite + alembic upgrade head (как AdminPlayerProfilePatchTests):
    update_admin_player_gas пишет в БД (row-lock GasWallet, создание
    проводки, аудит), поэтому FakeSession не подходит.

    Баланс газа — Numeric(18,4): в SQLite хранится как float и читается
    как Decimal("10.0"), в PostgreSQL — со scale 4 ("10.0000"). Строковая
    форма зависит от диалекта, поэтому балансы сравниваем через Decimal()
    от строки, а не точным строковым равенством.
    """

    @classmethod
    def setUpClass(cls) -> None:
        from app import admin_players

        cls.admin_players = admin_players
        cls._session_local_patch = None

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-players-gas-"
        )
        self.database_path = Path(self._temporary_directory.name) / "gas.sqlite3"
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

        @event.listens_for(self.engine, "connect")
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
        self._session_local_patch = patch.object(
            self.admin_players, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

    def tearDown(self) -> None:
        self._session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы ---------------------------------------------

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

    def _make_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="Gas-игрок",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_gas_wallet(self, player_id: str, balance: Decimal) -> str:
        from app.models import GasWallet

        wallet_id = f"gas-wallet-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GasWallet(id=wallet_id, player_id=player_id, balance=balance)
            )
        return wallet_id

    def _get_gas_wallet(self, player_id: str):
        from app.models import GasWallet

        with self.SessionLocal() as session:
            return session.scalar(
                select(GasWallet).where(GasWallet.player_id == player_id)
            )

    def _get_gas_transactions(self, gas_wallet_id: str):
        from app.models import GasTransaction

        with self.SessionLocal() as session:
            return session.scalars(
                select(GasTransaction).where(
                    GasTransaction.gas_wallet_id == gas_wallet_id
                )
            ).all()

    def _find_gas_audits(self):
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return session.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "player.gas_adjusted"
                )
            ).all()

    def _call_gas_patch(
        self, player_id: str, amount: Decimal, reason: str, admin
    ) -> dict:
        return self.admin_players.update_admin_player_gas(
            player_id,
            self.admin_players.GasAdjustmentPayload(amount=amount, reason=reason),
            request=None,
            admin=admin,
        )

    # ---- Сценарии --------------------------------------------------------

    def test_patch_gas_credit(self) -> None:
        admin = self._make_admin()
        player_id = self._make_player()
        wallet_id = self._make_gas_wallet(player_id, Decimal("10"))

        result = self._call_gas_patch(player_id, Decimal("5"), "bonus", admin)

        # Баланс в карточке: 10 + 5 = 15.
        self.assertEqual(Decimal(result["player"]["gasBalance"]), Decimal("15"))

        # Проводка: credit, amount, balance_after.
        txs = self._get_gas_transactions(wallet_id)
        self.assertEqual(len(txs), 1)
        tx = txs[0]
        self.assertEqual(tx.transaction_type, "credit")
        self.assertEqual(Decimal(tx.amount), Decimal("5"))
        self.assertEqual(Decimal(tx.balance_after), Decimal("15"))
        self.assertEqual(tx.reason, "bonus")
        self.assertEqual(tx.reference_type, "admin_gas_adjustment")
        self.assertIsNotNone(tx.reference_id)
        self.assertEqual(tx.metadata_json, {"adminId": admin.id})

        # Аудит: action зафиксирован фильтром, before/after в строках,
        # metadata-amount = str(Decimal).
        audits = self._find_gas_audits()
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.entity_id, player_id)
        self.assertEqual(audit.permission_code, "players.manage")
        self.assertEqual(
            Decimal(audit.before_json["gasBalance"]), Decimal("10")
        )
        self.assertEqual(
            Decimal(audit.after_json["gasBalance"]), Decimal("15")
        )
        self.assertEqual(
            audit.metadata_json, {"amount": "5", "reason": "bonus"}
        )

    def test_patch_gas_debit(self) -> None:
        admin = self._make_admin()
        player_id = self._make_player()
        wallet_id = self._make_gas_wallet(player_id, Decimal("10"))

        result = self._call_gas_patch(player_id, Decimal("-3"), "spend", admin)

        # Баланс в карточке: 10 - 3 = 7.
        self.assertEqual(Decimal(result["player"]["gasBalance"]), Decimal("7"))

        txs = self._get_gas_transactions(wallet_id)
        self.assertEqual(len(txs), 1)
        tx = txs[0]
        self.assertEqual(tx.transaction_type, "debit")
        self.assertEqual(Decimal(tx.amount), Decimal("3"))
        self.assertEqual(Decimal(tx.balance_after), Decimal("7"))
        self.assertEqual(tx.reason, "spend")

    def test_patch_gas_insufficient(self) -> None:
        admin = self._make_admin()
        player_id = self._make_player()
        wallet_id = self._make_gas_wallet(player_id, Decimal("10"))

        with self.assertRaises(HTTPException) as ctx:
            self._call_gas_patch(player_id, Decimal("-100"), "spend", admin)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "Недостаточно газа для списания.")

        # Транзакция откатилась: баланс не изменился, проводок и аудита нет.
        wallet = self._get_gas_wallet(player_id)
        self.assertEqual(Decimal(wallet.balance), Decimal("10"))
        self.assertEqual(self._get_gas_transactions(wallet_id), [])
        self.assertEqual(self._find_gas_audits(), [])

    def test_patch_gas_zero_amount(self) -> None:
        admin = self._make_admin()

        # Проверка amount != 0 идёт до обращения к БД, игрок не нужен.
        with self.assertRaises(HTTPException) as ctx:
            self._call_gas_patch("player-unknown", Decimal("0"), "noop", admin)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "Сумма газа должна быть ненулевой.")

    def test_patch_gas_creates_wallet(self) -> None:
        admin = self._make_admin()
        player_id = self._make_player()

        result = self._call_gas_patch(player_id, Decimal("5"), "first bonus", admin)

        self.assertEqual(Decimal(result["player"]["gasBalance"]), Decimal("5"))

        # Кошелёк создан (у игрока его не было) + проводка credit.
        gas_wallet = self._get_gas_wallet(player_id)
        self.assertIsNotNone(gas_wallet)
        self.assertEqual(Decimal(gas_wallet.balance), Decimal("5"))

        txs = self._get_gas_transactions(gas_wallet.id)
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0].transaction_type, "credit")
        self.assertEqual(Decimal(txs[0].amount), Decimal("5"))
        self.assertEqual(Decimal(txs[0].balance_after), Decimal("5"))


if __name__ == "__main__":
    unittest.main()
