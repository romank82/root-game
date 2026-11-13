"""Sprint 8.x-attempt-deadline: серверный дедлайн ОДНОЙ попытки мини-игры.

Зачем этот файл: клиентский таймер попытки жил только на фронте, поэтому
кнопка «ЗАНОВО» (и повторный вход на экран) перезапускала отсчёт без
обращения к серверу — игрок получал неограниченное время внутри одной
попытки, не теряя попыток. Теперь сервер хранит абсолютный момент окончания
текущей попытки (player_missions.attempt_deadline_at), проверяет его при
submit с grace 3 сек и авто-истекает попытку в
_synchronize_player_missions.

Фикстуры (изолированная SQLite-база через Alembic, игрок/миссии/политика)
переиспользуются из test_mission_engine_integration, но БЕЗ наследования
класса: иначе вместе с этими тестами прогонялись бы все тесты родителя.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import select

# Импортируем МОДУЛЬ, а не класс: unittest собирает все TestCase-классы из
# пространства имён загруженного модуля, поэтому импортированный класс родителя
# добавил бы к нашим 8 тестам все тесты интеграционного файла.
from tests import test_mission_engine_integration as engine_tests


class AttemptDeadlineTests(unittest.TestCase):
    """Проверки серверного дедлайна попытки (attempt_deadline_at)."""

    # ---- Фикстуры движка (reuse без наследования тестов родителя) --------

    @classmethod
    def setUpClass(cls) -> None:
        engine_tests.MissionEngineIntegrationTests.setUpClass()
        base = engine_tests.MissionEngineIntegrationTests
        cls.SessionLocal = base.SessionLocal
        cls.engine = base.engine
        cls.mission_engine = base.mission_engine

    @classmethod
    def tearDownClass(cls) -> None:
        engine_tests.MissionEngineIntegrationTests.tearDownClass()

    # Готовые хелперы интеграционных тестов.
    _fixture = engine_tests.MissionEngineIntegrationTests._fixture
    _seed_policy = engine_tests.MissionEngineIntegrationTests._seed_policy
    _create_cipher_mission = (
        engine_tests.MissionEngineIntegrationTests._create_cipher_mission
    )
    _read_cipher_session = (
        engine_tests.MissionEngineIntegrationTests._read_cipher_session
    )
    _as_naive_utc = staticmethod(
        engine_tests.MissionEngineIntegrationTests._as_naive_utc
    )
    _mission_by_id = staticmethod(
        engine_tests.MissionEngineIntegrationTests._mission_by_id
    )

    # ---- Локальные хелперы шага 3A --------------------------------------

    def _read_player_mission(self, player_id: str, mission_id: str):
        """Свежее состояние PlayerMission (новое соединение, без кэша)."""
        from app.models import PlayerMission

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            )
            self.assertIsNotNone(player_mission)
            return player_mission

    def _attach_minigame_profile(
        self,
        mission_id: str,
        *,
        settings: dict,
        game_type: str = "cipher",
    ) -> str:
        """Published MinigameProfile + привязка к миссии (источник лимита)."""
        from app.models import MinigameProfile, Mission

        suffix = uuid.uuid4().hex
        profile_id = f"minigame-profile-{suffix}"
        with self.SessionLocal.begin() as session:
            session.add(
                MinigameProfile(
                    id=profile_id,
                    name=f"attempt-deadline-{suffix}",
                    game_type=game_type,
                    settings=settings,
                    status="published",
                )
            )
            session.flush()
            mission = session.get(Mission, mission_id)
            self.assertIsNotNone(mission)
            mission.minigame_profile_id = profile_id
        return profile_id

    def _create_cipher_mission_with_limit(
        self,
        ids: dict[str, str],
        *,
        time_limit_seconds: int = 60,
        max_attempts: int | None = None,
    ) -> str:
        """Cipher-миссия с лимитом попытки (timeLimitSeconds из профиля)."""
        mission_id = self._create_cipher_mission(ids)
        self._attach_minigame_profile(
            mission_id,
            settings={
                "drumCount": 4,
                "falseChoicesPerDrum": 2,
                "timeLimitSeconds": time_limit_seconds,
            },
        )
        if max_attempts is not None:
            # Хелпер родителя создаёт published policy (max_attempts=3),
            # затем сужаем лимит до нужного тесту значения.
            self._seed_policy(mission_id)
            self._pin_max_attempts(mission_id, max_attempts)
        return mission_id

    def _pin_max_attempts(self, mission_id: str, max_attempts: int) -> None:
        """Сузить max_attempts у published policy (хелпер родителя ставит 3)."""
        from app.geo_team_runtime_models import MissionRuntimePolicy

        with self.SessionLocal.begin() as session:
            policy = session.scalar(
                select(MissionRuntimePolicy).where(
                    MissionRuntimePolicy.mission_id == mission_id,
                    MissionRuntimePolicy.status == "published",
                )
            )
            self.assertIsNotNone(policy)
            policy.max_attempts = max_attempts

    def _expire_attempt_deadline(
        self,
        player_id: str,
        mission_id: str,
        *,
        seconds_ago: int = 10,
    ) -> None:
        """Сдвинуть attempt_deadline_at в прошлое (симуляция «время вышло»).

        freezegun в окружении нет, поэтому вместо подмены системного времени
        правим абсолютный дедлайн напрямую: сервер сравнивает его с _utcnow().
        """
        from app import mission_engine
        from app.models import PlayerMission

        deadline = mission_engine._utcnow() - timedelta(seconds=seconds_ago)
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            )
            self.assertIsNotNone(player_mission)
            player_mission.attempt_deadline_at = deadline

    def _synchronize(self, player_id: str) -> None:
        """Прогнать sync (то же, что делает bootstrap при чтении прогресса)."""
        with self.SessionLocal.begin() as session:
            self.mission_engine._synchronize_player_missions(session, player_id)

    def _create_text_answer_mission(self, ids: dict[str, str]) -> str:
        """Published text_answer-миссия без серверной сессии мини-игры."""
        from app.models import GeoZone, Mission

        suffix = uuid.uuid4().hex
        mission_id = f"text-answer-{suffix}"
        zone_id = f"text-answer-zone-{suffix}"
        with self.SessionLocal.begin() as session:
            session.add(
                GeoZone(
                    id=zone_id,
                    slug=f"text-answer-zone-{suffix}",
                    title="Text answer fixture geo zone",
                    description="Text answer accept fixture geo zone",
                    zone_type="radius",
                    status="published",
                    sort_order=60,
                    latitude=55.751244,
                    longitude=37.618423,
                    radius_meters=500,
                    search_radius_meters=1500,
                    location_constraints={},
                )
            )
            session.flush()
            session.add(
                Mission(
                    id=mission_id,
                    season_id=ids["season"],
                    slug=f"text-answer-{suffix}",
                    mission_type="text_answer",
                    title="Text answer mission",
                    description="Mission without minigame session",
                    content={"schemaVersion": 1, "ui": {"label": "Answer"}},
                    validation_config={
                        "validator": "normalized_text_match",
                        "acceptedAnswers": ["complete"],
                    },
                    status="published",
                    sort_order=45,
                    geo_zone_id=zone_id,
                )
            )
        return mission_id

    def _accept(self, player_id: str, mission_id: str) -> dict:
        return self.mission_engine.accept_mission(
            player_id,
            mission_id,
            latitude=55.751244,
            longitude=37.618423,
        )

    # @deprecated: после фикса 8.x-attempt-deadline-fix тесты переведены на
    # обычный submit_mission (реальный sync). Оставлен как legacy-хелпер на
    # случай, если понадобится изолировать ветку attempt_expired без sync.
    def _submit_isolated_from_sync(
        self,
        player_id: str,
        mission_id: str,
        *,
        answer: str | None = None,
        sequence: list[str] | None = None,
    ) -> dict:
        """Submit с заглушкой sync — изолированно проверяем ветку дедлайна.

        В обычном потоке submit сначала вызывает _synchronize_player_missions,
        а тот сам сжигает просроченную попытку и выдаёт новую сессию (см.
        test_sync_auto_expires_attempt_without_submit). Чтобы проверить именно
        ветку attempt_expired в _submit_mission_once, подменяем sync на
        «прочитать прогресс без побочных эффектов».
        """
        from app.models import PlayerMission

        def _read_only_sync(session, current_player_id: str) -> dict:
            rows = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == current_player_id
                )
            ).all()
            return {row.mission_id: row for row in rows}

        with patch.object(
            self.mission_engine,
            "_synchronize_player_missions",
            _read_only_sync,
        ):
            return self.mission_engine.submit_mission(
                player_id,
                mission_id,
                answer=answer,
                sequence=sequence,
            )

    # ---- Тесты ----------------------------------------------------------

    def test_attempt_deadline_set_on_accept(self) -> None:
        """Accept с timeLimitSeconds=60 → attempt_deadline_at = start + 60."""
        ids = self._fixture()
        mission_id = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60
        )

        accepted = self._accept(ids["player"], mission_id)
        self.assertTrue(accepted["accepted"])

        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertIsNotNone(player_mission.attempt_deadline_at)

        delta = (
            self._as_naive_utc(player_mission.attempt_deadline_at)
            - self._as_naive_utc(player_mission.started_at)
        ).total_seconds()
        self.assertAlmostEqual(delta, 60, delta=5)

        # Публичный bootstrap отдаёт абсолютный дедлайн попытки фронту.
        bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        self.assertIsNotNone(
            self._mission_by_id(bootstrap, mission_id)["attemptDeadlineAt"]
        )

    def test_attempt_deadline_null_without_limit(self) -> None:
        """Cipher без MinigameProfile → legacy-поведение (дедлайн NULL)."""
        ids = self._fixture()
        mission_id = self._create_cipher_mission(ids)

        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])

        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertIsNone(player_mission.attempt_deadline_at)
        self.assertIsNotNone(
            (player_mission.progress or {}).get("cipher_session")
        )

        bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        self.assertIsNone(
            self._mission_by_id(bootstrap, mission_id)["attemptDeadlineAt"]
        )

    def test_submit_after_attempt_deadline_consumes_attempt(self) -> None:
        """Просрочка: ответ валится, попытка сгорает, выдаётся новая."""
        from app import mission_engine

        ids = self._fixture()
        mission_id = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60
        )
        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])
        before = self._read_cipher_session(ids["player"], mission_id)

        # «Время вышло»: дедлайн попытки в прошлом (за пределами grace).
        self._expire_attempt_deadline(ids["player"], mission_id, seconds_ago=10)

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            mission_id,
            sequence=before["correct_code"],  # код верный, но время вышло
        )
        self.assertFalse(rejected["accepted"])
        self.assertTrue(rejected["timedOut"])
        self.assertEqual(rejected["missionStatus"], "in_progress")

        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(player_mission.attempt_count, 1)
        self.assertEqual(player_mission.status, "in_progress")
        self.assertIsNotNone(player_mission.attempt_deadline_at)
        self.assertGreater(
            self._as_naive_utc(player_mission.attempt_deadline_at),
            self._as_naive_utc(mission_engine._utcnow()),
        )

        # Новая сессия: код перегенерирован, старый ответ уже не подходит.
        after = self._read_cipher_session(ids["player"], mission_id)
        self.assertNotEqual(after["correct_code"], before["correct_code"])

    def test_submit_after_attempt_deadline_on_last_attempt_expires(self) -> None:
        """max_attempts=1: просрочка сжигает последнюю попытку → 409 + expired.

        Порядок в engine: инкремент attempt_count идёт ДО проверки дедлайна,
        поэтому первый просроченный submit возвращает accepted=False (попытка
        сгорела), а 409 «Попытки исчерпаны» приходит на следующем submit —
        это существующая семантика enforcement max_attempts.
        """
        ids = self._fixture()
        mission_id = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60, max_attempts=1
        )
        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])
        before = self._read_cipher_session(ids["player"], mission_id)
        self._expire_attempt_deadline(ids["player"], mission_id, seconds_ago=10)

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            mission_id,
            sequence=before["correct_code"],
        )
        self.assertFalse(rejected["accepted"])
        self.assertTrue(rejected["timedOut"])
        self.assertEqual(
            self._read_player_mission(ids["player"], mission_id).attempt_count, 1
        )

        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                mission_id,
                answer=None,
                sequence=["X"],
            )
        self.assertEqual(error.exception.status_code, 409)

        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(player_mission.status, "expired")
        self.assertIsNone(player_mission.attempt_deadline_at)
        # reentry_cooldown_seconds у тестовой миссии = 0 → без окна возврата.
        self.assertIsNone(player_mission.available_again_at)

    def test_late_submit_consumes_exactly_one_attempt(self) -> None:
        """Поздний submit сжигает РОВНО одну попытку (регресс на двойное списание).

        До фикса: sync сжигал попытку №1, затем submit валил старый ответ на
        новой сессии → попытка №2. Теперь должен сжигаться только №1, а
        ответ помечается timedOut=true.
        """
        ids = self._fixture()
        mission_id = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60
        )
        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])
        before = self._read_cipher_session(ids["player"], mission_id)
        # Убедимся, что попыток ещё не было.
        self.assertEqual(
            self._read_player_mission(ids["player"], mission_id).attempt_count, 0
        )
        # Просрочили попытку (дедлайн в прошлом, за пределами grace).
        self._expire_attempt_deadline(ids["player"], mission_id, seconds_ago=10)
        # Обычный submit (не изолированный) — с реальным sync.
        rejected = self.mission_engine.submit_mission(
            ids["player"],
            mission_id,
            sequence=before["correct_code"],
        )
        self.assertFalse(rejected["accepted"])
        self.assertTrue(rejected["timedOut"])
        # Главное: ровно ОДНА попытка сожжена (а не две).
        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(player_mission.attempt_count, 1)
        self.assertEqual(player_mission.status, "in_progress")
        self.assertIsNotNone(player_mission.attempt_deadline_at)
        # Новая сессия: код перегенерирован.
        after = self._read_cipher_session(ids["player"], mission_id)
        self.assertNotEqual(after["correct_code"], before["correct_code"])

    def test_repeated_bootstrap_does_not_extend_attempt_deadline(self) -> None:
        """Повторный bootstrap/sync НЕ продлевает время попытки (ядро бага).

        Раньше «ЗАНОВО»/повторный вход на экран запускали клиентский таймер
        заново. Теперь дедлайн попытки — абсолютный момент в БД, и чтение
        прогресса его не трогает.
        """
        ids = self._fixture()
        mission_id = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60
        )
        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])

        deadline_before = self._as_naive_utc(
            self._read_player_mission(ids["player"], mission_id).attempt_deadline_at
        )
        self.assertIsNotNone(deadline_before)

        # Два «захода» игрока на экран + прямой sync.
        self.mission_engine.get_bootstrap(ids["player"])
        self.mission_engine.get_bootstrap(ids["player"])
        self._synchronize(ids["player"])

        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(
            self._as_naive_utc(player_mission.attempt_deadline_at), deadline_before
        )
        self.assertEqual(player_mission.attempt_count, 0)
        self.assertEqual(player_mission.status, "in_progress")

    def test_attempt_deadline_cleared_on_completed_and_expired(self) -> None:
        """Успешный submit и ручной expire очищают attempt_deadline_at."""
        ids = self._fixture()

        # (а) Успех внутри дедлайна → completed + NULL.
        completed_mission = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60
        )
        self.assertTrue(self._accept(ids["player"], completed_mission)["accepted"])
        session_data = self._read_cipher_session(ids["player"], completed_mission)
        accepted = self.mission_engine.submit_mission(
            ids["player"],
            completed_mission,
            answer=None,
            sequence=session_data["correct_code"],
        )
        self.assertTrue(accepted["accepted"])
        completed_pm = self._read_player_mission(ids["player"], completed_mission)
        self.assertEqual(completed_pm.status, "completed")
        self.assertIsNone(completed_pm.attempt_deadline_at)

        # (б) Ручной expire (отказ игрока) → expired + NULL. Отдельный игрок:
        # движок разрешает только одну активную solo-миссию одновременно.
        expired_ids = self._fixture()
        expired_mission = self._create_cipher_mission_with_limit(
            expired_ids, time_limit_seconds=60
        )
        self.assertTrue(
            self._accept(expired_ids["player"], expired_mission)["accepted"]
        )
        expired_result = self.mission_engine.expire_mission(
            expired_ids["player"], expired_mission
        )
        self.assertTrue(expired_result["expired"])
        expired_pm = self._read_player_mission(
            expired_ids["player"], expired_mission
        )
        self.assertEqual(expired_pm.status, "expired")
        self.assertIsNone(expired_pm.attempt_deadline_at)

    def test_sync_auto_expires_attempt_without_submit(self) -> None:
        """Sync сам сжигает просроченную попытку (игрок не прислал submit)."""
        ids = self._fixture()

        # (а) Лимит не исчерпан → новая сессия и новый дедлайн.
        mission_id = self._create_cipher_mission_with_limit(
            ids, time_limit_seconds=60
        )
        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])
        before = self._read_cipher_session(ids["player"], mission_id)
        self._expire_attempt_deadline(ids["player"], mission_id, seconds_ago=10)

        self._synchronize(ids["player"])

        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(player_mission.attempt_count, 1)
        self.assertEqual(player_mission.status, "in_progress")
        self.assertIsNotNone(player_mission.attempt_deadline_at)
        after = self._read_cipher_session(ids["player"], mission_id)
        self.assertNotEqual(after["correct_code"], before["correct_code"])

        # (б) max_attempts=1 → статус expired, дедлайн очищен. Отдельный игрок:
        # движок разрешает только одну активную solo-миссию одновременно.
        single_ids = self._fixture()
        single_attempt_mission = self._create_cipher_mission_with_limit(
            single_ids, time_limit_seconds=60, max_attempts=1
        )
        self.assertTrue(
            self._accept(single_ids["player"], single_attempt_mission)["accepted"]
        )
        self._expire_attempt_deadline(
            single_ids["player"], single_attempt_mission, seconds_ago=10
        )

        self._synchronize(single_ids["player"])

        expired_pm = self._read_player_mission(
            single_ids["player"], single_attempt_mission
        )
        self.assertEqual(expired_pm.attempt_count, 1)
        self.assertEqual(expired_pm.status, "expired")
        self.assertIsNone(expired_pm.attempt_deadline_at)

    def test_team_mission_not_affected(self) -> None:
        """Миссии без сессии мини-игры не получают дедлайн попытки.

        Team-миссии обслуживает team_missions_service, cipher/memory-сессию они
        не создают; эквивалентный solo-случай без серверной сессии —
        text_answer. Проверяем, что attempt_deadline_at остаётся NULL и флоу
        accept/submit не падает.
        """
        ids = self._fixture()
        mission_id = self._create_text_answer_mission(ids)

        self.assertTrue(self._accept(ids["player"], mission_id)["accepted"])
        player_mission = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(player_mission.status, "in_progress")
        self.assertIsNone(player_mission.attempt_deadline_at)

        submitted = self.mission_engine.submit_mission(
            ids["player"],
            mission_id,
            answer="complete",
            sequence=None,
        )
        self.assertTrue(submitted["accepted"])

        completed = self._read_player_mission(ids["player"], mission_id)
        self.assertEqual(completed.status, "completed")
        self.assertIsNone(completed.attempt_deadline_at)

        bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        self.assertIsNone(
            self._mission_by_id(bootstrap, mission_id)["attemptDeadlineAt"]
        )


if __name__ == "__main__":
    unittest.main()
