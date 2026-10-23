"""Unit-тесты read-only админ-эндпоинтов игроков (шаг 5.3).

Unit-style: fake-объекты (SimpleNamespace) вместо реальной БД и TestClient
(по образцу test_admin_reward_pools.py). FakeSession диспатчит запросы по
скомпиленному SQL c literal binds и не имеет методов записи — любой write
в read-only карточке упал бы с AttributeError.
"""
from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException

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


if __name__ == "__main__":
    unittest.main()
