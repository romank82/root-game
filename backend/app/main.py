import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="CHIMERA Protocol API",
    version="0.3.0",
    description="Backend API for the CHIMERA game.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# База создаётся рядом с папкой app:
# root-game/backend/chimera.db
DATABASE_PATH = Path(__file__).resolve().parent.parent / "chimera.db"
DEMO_PLAYER_ID = "demo-player"

REWARD_ACTIONS = {
    "puzzle-a-01": {
        "root": 3,
        "inventoryItemId": "item-key-a01",
        "unlocksStoryNodeId": None,
    },
    "puzzle-a-02": {
        "root": 4,
        "inventoryItemId": None,
        "unlocksStoryNodeId": None,
    },
    "segment-archive-017": {
        "root": 10,
        "inventoryItemId": "item-archive-a17",
        "unlocksStoryNodeId": "story-node-a17",
    },
}

INVENTORY_ITEMS = {
    "item-key-a01": {
        "id": "item-key-a01",
        "code": "KEY_A01",
        "title": "КЛЮЧ A-01",
        "description": (
            "Повреждённый ключ доступа, извлечённый из первого "
            "архивного пакета."
        ),
        "symbol": "⌘",
        "category": "KEY",
        "isUnique": True,
    },
    "item-archive-a17": {
        "id": "item-archive-a17",
        "code": "ARCHIVE_A17",
        "title": "АРХИВНЫЙ СЕГМЕНТ A-17",
        "description": (
            "Связанный с исчезнувшей записью фрагмент. Его данные "
            "повреждены, но структура указывает на внешний архивный контур."
        ),
        "symbol": "◈",
        "category": "ARCHIVE",
        "isUnique": True,
    },
}

STORY_NODES = {
    "story-node-a17": {
        "id": "story-node-a17",
        "title": "ФРАГМЕНТ A-17",
        "body": (
            "Архивный контур откликнулся. В извлечённых данных найдено "
            "упоминание Оператора и координат следующего Сегмента."
        ),
        "requiredMissionIds": ["mission-archive-017"],
    },
}

ACTIVE_MISSION = {
    "id": "mission-archive-017",
    "segmentId": "segment-archive-017",
    "title": "ИЗВЛЕЧЕНИЕ ARCHIVE_NODE_017",
    "description": (
        "Зафиксируйте грань AR-куба, извлеките виртуальный QR-маркер "
        "и восстановите повреждённый пакет."
    ),
    "puzzleId": "puzzle-code-repair-a17",
    "reward": {
        "root": 10,
        "inventoryItemId": "item-archive-a17",
        "unlocksStoryNodeId": "story-node-a17",
    },
}


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id TEXT PRIMARY KEY,
                root_balance INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS completed_rewards (
                player_id TEXT NOT NULL,
                action TEXT NOT NULL,
                PRIMARY KEY (player_id, action),
                FOREIGN KEY (player_id) REFERENCES players(id)
            )
            """
        )

        connection.execute(
            """
            INSERT OR IGNORE INTO players (id, root_balance)
            VALUES (?, 0)
            """,
            (DEMO_PLAYER_ID,),
        )


def get_completed_rewards(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT action
        FROM completed_rewards
        WHERE player_id = ?
        """,
        (DEMO_PLAYER_ID,),
    ).fetchall()

    return {row["action"] for row in rows}


def get_player_inventory(completed_rewards: set[str]) -> list[dict]:
    item_ids = [
        reward["inventoryItemId"]
        for action, reward in REWARD_ACTIONS.items()
        if action in completed_rewards
        and reward["inventoryItemId"] is not None
    ]

    return [INVENTORY_ITEMS[item_id] for item_id in item_ids]


def get_unlocked_story_nodes(completed_rewards: set[str]) -> list[dict]:
    node_ids = [
        reward["unlocksStoryNodeId"]
        for action, reward in REWARD_ACTIONS.items()
        if action in completed_rewards
        and reward["unlocksStoryNodeId"] is not None
    ]

    return [STORY_NODES[node_id] for node_id in node_ids]


def get_active_mission(completed_rewards: set[str]) -> dict | None:
    if "segment-archive-017" in completed_rewards:
        return None

    return ACTIVE_MISSION


def get_game_state(connection: sqlite3.Connection) -> dict:
    player = connection.execute(
        """
        SELECT id, root_balance
        FROM players
        WHERE id = ?
        """,
        (DEMO_PLAYER_ID,),
    ).fetchone()

    completed_rewards = get_completed_rewards(connection)

    return {
        "player": {
            "id": player["id"],
            "rootBalance": player["root_balance"],
        },
        "activeMission": get_active_mission(completed_rewards),
        "inventory": get_player_inventory(completed_rewards),
        "storyNodes": get_unlocked_story_nodes(completed_rewards),
        "completedRewards": sorted(completed_rewards),
    }


def claim_reward(action: str) -> dict:
    reward = REWARD_ACTIONS[action]

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        result = connection.execute(
            """
            INSERT OR IGNORE INTO completed_rewards (player_id, action)
            VALUES (?, ?)
            """,
            (DEMO_PLAYER_ID, action),
        )

        already_completed = result.rowcount == 0
        awarded = 0 if already_completed else reward["root"]

        if awarded > 0:
            connection.execute(
                """
                UPDATE players
                SET root_balance = root_balance + ?
                WHERE id = ?
                """,
                (awarded, DEMO_PLAYER_ID),
            )

        game_state = get_game_state(connection)

    return {
        "playerId": DEMO_PLAYER_ID,
        "action": action,
        "awarded": awarded,
        "alreadyCompleted": already_completed,
        "rootBalance": game_state["player"]["rootBalance"],
        "inventory": game_state["inventory"],
        "storyNodes": game_state["storyNodes"],
        "activeMission": game_state["activeMission"],
    }


initialize_database()


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "chimera-api",
        "version": "0.3.0",
        "storage": "sqlite",
    }


@app.get("/api/v1/game/bootstrap")
def get_game_bootstrap():
    with get_connection() as connection:
        return get_game_state(connection)


@app.get("/api/v1/game/root-balance")
def get_root_balance():
    with get_connection() as connection:
        player = connection.execute(
            """
            SELECT root_balance
            FROM players
            WHERE id = ?
            """,
            (DEMO_PLAYER_ID,),
        ).fetchone()

    return {
        "playerId": DEMO_PLAYER_ID,
        "rootBalance": player["root_balance"],
    }


@app.post("/api/v1/game/reset-demo-progress")
def reset_demo_progress():
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE players
            SET root_balance = 0
            WHERE id = ?
            """,
            (DEMO_PLAYER_ID,),
        )

        connection.execute(
            """
            DELETE FROM completed_rewards
            WHERE player_id = ?
            """,
            (DEMO_PLAYER_ID,),
        )

        game_state = get_game_state(connection)

    return {
        "playerId": DEMO_PLAYER_ID,
        "rootBalance": game_state["player"]["rootBalance"],
        "completedRewards": game_state["completedRewards"],
        "inventory": game_state["inventory"],
        "storyNodes": game_state["storyNodes"],
        "activeMission": game_state["activeMission"],
    }


@app.post("/api/v1/game/rewards/puzzle-a-01")
def claim_puzzle_a_01_reward():
    return claim_reward("puzzle-a-01")


@app.post("/api/v1/game/rewards/puzzle-a-02")
def claim_puzzle_a_02_reward():
    return claim_reward("puzzle-a-02")


@app.post("/api/v1/game/rewards/segment-archive-017")
def claim_segment_archive_017_reward():
    return claim_reward("segment-archive-017")

# --- SQLALCHEMY MISSION ENGINE ROUTES ---
# Новый SQLAlchemy engine работает параллельно с legacy /api/v1/game/* API.

from fastapi import HTTPException
from pydantic import BaseModel

from app.mission_engine import (
    MissionEngineError,
    get_bootstrap as get_engine_bootstrap,
    reset_demo_engine_progress,
    submit_mission,
)


class MissionSubmitPayload(BaseModel):
    answer: str | None = None
    sequence: list[str] | None = None


@app.get("/api/v1/engine/bootstrap")
def get_engine_bootstrap_route():
    try:
        return get_engine_bootstrap(DEMO_PLAYER_ID)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@app.post("/api/v1/engine/missions/{mission_id}/submit")
def submit_engine_mission(
    mission_id: str,
    payload: MissionSubmitPayload,
):
    try:
        return submit_mission(
            player_id=DEMO_PLAYER_ID,
            mission_id=mission_id,
            answer=payload.answer,
            sequence=payload.sequence,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@app.post("/api/v1/engine/reset-demo-progress")
def reset_engine_demo_progress():
    try:
        return reset_demo_engine_progress(DEMO_PLAYER_ID)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
