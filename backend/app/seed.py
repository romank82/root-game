from app.db import SessionLocal
from app.models import (
    Chapter,
    GamePlayer,
    Item,
    Mission,
    MissionRequirement,
    MissionReward,
    Season,
    Segment,
    SegmentMission,
    StoryNode,
    Wallet,
)


def seed_content() -> None:
    """Создать начальный контент CHIMERA. Безопасно для повторного запуска."""

    with SessionLocal.begin() as session:
        session.merge(
            Season(
                id="season-protocol-01",
                slug="protocol-01",
                title="CHIMERA: PROTOCOL 01",
                description=(
                    "Первый цикл восстановления повреждённого "
                    "архивного контура CHIMERA."
                ),
                status="published",
                sort_order=1,
            )
        )

        # Season must exist before its child chapters (required by PostgreSQL FK).
        session.flush()

        session.merge(
            Chapter(
                id="chapter-archive-recovery",
                season_id="season-protocol-01",
                slug="archive-recovery",
                title="ВОССТАНОВЛЕНИЕ АРХИВА",
                description=(
                    "Оператор получает доступ к повреждённым сегментам "
                    "и восстанавливает связь с архивным контуром."
                ),
                status="published",
                sort_order=1,
            )
        )

        # Chapter must exist before content attached to it.
        session.flush()

        session.merge(
            Item(
                id="item-key-a01",
                slug="key-a01",
                code="KEY_A01",
                title="КЛЮЧ A-01",
                description=(
                    "Повреждённый ключ доступа, извлечённый из первого "
                    "архивного пакета."
                ),
                symbol="⌘",
                category="KEY",
                rarity="common",
                is_unique=True,
                content={},
                status="published",
            )
        )

        session.merge(
            Item(
                id="item-archive-a17",
                slug="archive-a17",
                code="ARCHIVE_A17",
                title="АРХИВНЫЙ СЕГМЕНТ A-17",
                description=(
                    "Связанный с исчезнувшей записью фрагмент. Его данные "
                    "повреждены, но структура указывает на внешний архивный контур."
                ),
                symbol="◈",
                category="ARCHIVE",
                rarity="rare",
                is_unique=True,
                content={},
                status="published",
            )
        )

        # Items are referenced later by mission rewards.
        session.flush()

        session.merge(
            StoryNode(
                id="story-node-a17",
                chapter_id="chapter-archive-recovery",
                slug="fragment-a17",
                title="ФРАГМЕНТ A-17",
                body=(
                    "Архивный контур откликнулся. В извлечённых данных найдено "
                    "упоминание Оператора и координат следующего Сегмента."
                ),
                presentation_type="archive",
                content={},
                status="published",
                sort_order=1,
            )
        )

        # Story nodes reference chapters and may be referenced by missions/rewards.
        session.flush()

        session.merge(
            Mission(
                id="mission-puzzle-a-01",
                chapter_id="chapter-archive-recovery",
                story_node_id=None,
                slug="puzzle-a-01",
                mission_type="text_answer",
                title="АРХИВНЫЙ ПАКЕТ A-01",
                description=(
                    "Восстановите первый повреждённый пакет и извлеките "
                    "ключ доступа."
                ),
                content={
                    "schemaVersion": 1,
                    "ui": {
                        "label": "ПЕРВАЯ ПРОВЕРКА",
                        "question": "Что остаётся, когда исчезает шум?",
                        "inputPlaceholder": "Введите ответ...",
                        "successTitle": "✓ ФРАГМЕНТ РАСШИФРОВАН",
                        "successText": (
                            "Получено: 3 ROOT. Найден сюжетный предмет: КЛЮЧ A-01."
                        ),
                        "rewardPreview": {
                            "text": "3 ROOT и сюжетный предмет: КЛЮЧ A-01.",
                        },
                    },
                },
                validation_config={
                    "validator": "normalized_text_match",
                    "acceptedAnswers": ["сигнал"],
                },
                status="published",
                sort_order=1,
            )
        )

        session.merge(
            Mission(
                id="mission-puzzle-a-02",
                chapter_id="chapter-archive-recovery",
                story_node_id=None,
                slug="puzzle-a-02",
                mission_type="text_answer",
                title="АРХИВНЫЙ ПАКЕТ A-02",
                description=(
                    "Обработайте второй повреждённый пакет архивного контура."
                ),
                content={
                    "schemaVersion": 1,
                    "ui": {
                        "label": "ВТОРАЯ ПРОВЕРКА",
                        "question": "Где сохраняются следы исчезнувших записей?",
                        "inputPlaceholder": "Введите ответ...",
                        "successTitle": "✓ ФРАГМЕНТ A-02 РАСШИФРОВАН",
                        "successText": (
                            "Получено: 4 ROOT. Найден доступ к архивному узлу."
                        ),
                        "rewardPreview": {
                            "text": "4 ROOT и доступ к архивному узлу.",
                        },
                    },
                },
                validation_config={
                    "validator": "normalized_text_match",
                    "acceptedAnswers": ["архив"],
                },
                status="published",
                sort_order=2,
            )
        )

        session.merge(
            Mission(
                id="mission-archive-017",
                chapter_id="chapter-archive-recovery",
                story_node_id="story-node-a17",
                slug="segment-archive-017",
                mission_type="code_repair",
                title="ИЗВЛЕЧЕНИЕ ARCHIVE_NODE_017",
                description=(
                    "Зафиксируйте грань AR-куба, извлеките виртуальный QR-маркер "
                    "и восстановите повреждённый пакет."
                ),
                content={
                    "schemaVersion": 1,
                    "ui": {
                        "label": "МИНИ-ИГРА / CODE REPAIR",
                        "instruction": (
                            "Архивный пакет потерял порядок трёх блоков. "
                            "Соберите корректную команду извлечения подписи."
                        ),
                        "blocks": ["packet.", "signature", "return "],
                        "maxBlocks": 3,
                        "lineNumber": "017",
                        "placeholder": "// выберите блоки ниже",
                        "wrongAnswerText": (
                            "СТРУКТУРА ПАКЕТА НАРУШЕНА. ОЧИСТИТЕ СТРОКУ "
                            "И ВОССТАНОВИТЕ ЕЁ ЗАНОВО."
                        ),
                        "rewardPreview": {
                            "text": "10 ROOT и предмет: АРХИВНЫЙ СЕГМЕНТ A-17.",
                        },
                    },
                },
                validation_config={
                    "validator": "ordered_blocks_match",
                    "correctSequence": ["return ", "packet.", "signature"],
                },
                status="published",
                sort_order=3,
            )
        )

        # Missions must exist before requirements and rewards can reference them.
        session.flush()

        # CMS seed additions are create-only. Existing Segment and SegmentMission
        # records, including archived link history, are never overwritten or revived.
        segment = session.get(Segment, "segment-archive-017")
        if segment is None:
            segment = Segment(
                id="segment-archive-017",
                chapter_id="chapter-archive-recovery",
                slug="archive-node-017",
                title="ARCHIVE_NODE_017",
                description=(
                    "Повреждённый AR-сегмент архивного контура. "
                    "Найдите безопасную точку и восстановите пакет."
                ),
                content={
                    "schemaVersion": 1,
                    "presentation": {
                        "code": "ARCHIVE_NODE_017",
                        "type": "ARCHIVE_SEGMENT",
                    },
                    "location": {
                        "searchRadiusMeters": 250,
                        "safeScanRadiusMeters": 15,
                        # Illustrative contract coordinates only; not a real game point.
                        "safeScanPoint": {
                            "latitude": 54.0,
                            "longitude": 82.0,
                        },
                    },
                    "arScene": {
                        "scenePreset": "archive_cube_damaged_v1",
                        "scanHoldDurationMs": 1800,
                    },
                },
                status="published",
                sort_order=1,
            )
            session.add(segment)
            session.flush()

        existing_segment_link = (
            session.query(SegmentMission)
            .filter(
                SegmentMission.segment_id == "segment-archive-017",
                SegmentMission.mission_id == "mission-archive-017",
            )
            .first()
        )
        if existing_segment_link is None:
            session.add(
                SegmentMission(
                    id="segment-mission-archive-017",
                    segment_id="segment-archive-017",
                    mission_id="mission-archive-017",
                    status="active",
                    sort_order=1,
                )
            )
            session.flush()

        session.merge(
            MissionRequirement(
                id="requirement-a02-after-a01",
                mission_id="mission-puzzle-a-02",
                requirement_type="mission_completed",
                requirement_value={"missionId": "mission-puzzle-a-01"},
                sort_order=1,
            )
        )

        session.merge(
            MissionRequirement(
                id="requirement-a17-after-a02",
                mission_id="mission-archive-017",
                requirement_type="mission_completed",
                requirement_value={"missionId": "mission-puzzle-a-02"},
                sort_order=1,
            )
        )

        # Requirements are now persisted; rewards reference missions/items/story nodes.
        session.flush()

        session.merge(
            MissionReward(
                id="reward-a01-root",
                mission_id="mission-puzzle-a-01",
                reward_type="currency",
                amount=3,
                item_id=None,
                story_node_id=None,
                reward_value={"currency": "ROOT"},
                sort_order=1,
            )
        )

        session.merge(
            MissionReward(
                id="reward-a01-key",
                mission_id="mission-puzzle-a-01",
                reward_type="item",
                amount=1,
                item_id="item-key-a01",
                story_node_id=None,
                reward_value={},
                sort_order=2,
            )
        )

        session.merge(
            MissionReward(
                id="reward-a02-root",
                mission_id="mission-puzzle-a-02",
                reward_type="currency",
                amount=4,
                item_id=None,
                story_node_id=None,
                reward_value={"currency": "ROOT"},
                sort_order=1,
            )
        )

        session.merge(
            MissionReward(
                id="reward-a17-root",
                mission_id="mission-archive-017",
                reward_type="currency",
                amount=10,
                item_id=None,
                story_node_id=None,
                reward_value={"currency": "ROOT"},
                sort_order=1,
            )
        )

        session.merge(
            MissionReward(
                id="reward-a17-item",
                mission_id="mission-archive-017",
                reward_type="item",
                amount=1,
                item_id="item-archive-a17",
                story_node_id=None,
                reward_value={},
                sort_order=2,
            )
        )

        session.merge(
            MissionReward(
                id="reward-a17-story",
                mission_id="mission-archive-017",
                reward_type="story_node",
                amount=None,
                item_id=None,
                story_node_id="story-node-a17",
                reward_value={},
                sort_order=3,
            )
        )

        # Persist all mission rewards before creating player-owned state.
        session.flush()

        # Development demo state is create-only. Never use merge() here:
        # seed runs on every container start, and merge would overwrite real
        # player fields or reset a wallet balance to zero.
        demo_player = session.get(GamePlayer, "demo-player")
        if demo_player is None:
            demo_player = GamePlayer(
                id="demo-player",
                display_name="Demo Operator",
                auth_provider="demo",
                external_id="demo-player",
                status="active",
            )
            session.add(demo_player)
            session.flush()

        demo_wallet = (
            session.query(Wallet)
            .filter(
                Wallet.player_id == "demo-player",
                Wallet.currency == "ROOT",
            )
            .first()
        )
        if demo_wallet is None:
            session.add(
                Wallet(
                    id="wallet-demo-player-root",
                    player_id="demo-player",
                    currency="ROOT",
                    available_balance=0,
                    locked_balance=0,
                )
            )

    print("✓ Seed completed successfully.")
    print("  Season: protocol-01")
    print("  Chapter: archive-recovery")
    print("  Missions: puzzle-a-01, puzzle-a-02, segment-archive-017")
    print("  Items: KEY_A01, ARCHIVE_A17")


if __name__ == "__main__":
    seed_content()
