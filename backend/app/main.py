from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="CHIMERA Protocol API",
    version="0.2.0",
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

# ----------------------------------------------------------------
# Временное серверное состояние одного demo-игрока.
# После перезапуска backend оно сбрасывается.
#
# Позднее эти данные будут храниться в PostgreSQL и привязываться
# к авторизованному игроку.
# ----------------------------------------------------------------

demo_player_root_balance = 0
demo_completed_rewards: set[str] = set()

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


def get_player_inventory():
    item_ids = [
        reward["inventoryItemId"]
        for action, reward in REWARD_ACTIONS.items()
        if action in demo_completed_rewards
        and reward["inventoryItemId"] is not None
    ]

    return [INVENTORY_ITEMS[item_id] for item_id in item_ids]


def get_unlocked_story_nodes():
    node_ids = [
        reward["unlocksStoryNodeId"]
        for action, reward in REWARD_ACTIONS.items()
        if action in demo_completed_rewards
        and reward["unlocksStoryNodeId"] is not None
    ]

    return [STORY_NODES[node_id] for node_id in node_ids]


def get_active_mission():
    if "segment-archive-017" in demo_completed_rewards:
        return None

    return ACTIVE_MISSION


def claim_reward(action: str):
    global demo_player_root_balance

    reward = REWARD_ACTIONS[action]
    already_completed = action in demo_completed_rewards

    if not already_completed:
        demo_completed_rewards.add(action)
        demo_player_root_balance += reward["root"]

    return {
        "playerId": "demo-player",
        "action": action,
        "awarded": 0 if already_completed else reward["root"],
        "alreadyCompleted": already_completed,
        "rootBalance": demo_player_root_balance,
        "inventory": get_player_inventory(),
        "storyNodes": get_unlocked_story_nodes(),
        "activeMission": get_active_mission(),
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "chimera-api",
        "version": "0.2.0",
    }


@app.get("/api/v1/game/bootstrap")
def get_game_bootstrap():
    return {
        "player": {
            "id": "demo-player",
            "rootBalance": demo_player_root_balance,
        },
        "activeMission": get_active_mission(),
        "inventory": get_player_inventory(),
        "storyNodes": get_unlocked_story_nodes(),
        "completedRewards": sorted(demo_completed_rewards),
    }


@app.get("/api/v1/game/root-balance")
def get_root_balance():
    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
    }


@app.post("/api/v1/game/reset-demo-progress")
def reset_demo_progress():
    global demo_player_root_balance

    demo_player_root_balance = 0
    demo_completed_rewards.clear()

    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
        "completedRewards": [],
        "inventory": [],
        "storyNodes": [],
        "activeMission": get_active_mission(),
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