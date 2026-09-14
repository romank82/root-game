from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="CHIMERA Protocol API",
    version="0.1.0",
    description="Backend API for the CHIMERA game.",
)

# Временно разрешаем обращения React-приложения к API на локальном ПК.
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

# Временное серверное состояние для одного демо-игрока.
# После перезапуска backend эти данные снова станут начальными.
demo_player_root_balance = 0
demo_completed_rewards: set[str] = set()

REWARD_ACTIONS = {
    "puzzle-a-01": 3,
    "puzzle-a-02": 4,
    "segment-archive-017": 10,
}


class RootBalanceUpdate(BaseModel):
    rootBalance: int


def claim_reward(action: str):
    global demo_player_root_balance

    reward = REWARD_ACTIONS[action]
    already_completed = action in demo_completed_rewards

    if not already_completed:
        demo_completed_rewards.add(action)
        demo_player_root_balance += reward

    return {
        "playerId": "demo-player",
        "action": action,
        "awarded": 0 if already_completed else reward,
        "alreadyCompleted": already_completed,
        "rootBalance": demo_player_root_balance,
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "chimera-api",
        "version": "0.1.0",
    }


@app.get("/api/v1/game/bootstrap")
def get_game_bootstrap():
    """
    Временный API-контракт.

    Позднее эти данные будут извлекаться из PostgreSQL
    и зависеть от авторизованного игрока.
    """
    return {
        "player": {
            "id": "demo-player",
            "rootBalance": demo_player_root_balance,
        },
        "activeMission": None,
        "inventory": [],
        "storyNodes": [],
        "completedRewards": sorted(demo_completed_rewards),
    }


@app.get("/api/v1/game/root-balance")
def get_root_balance():
    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
    }


@app.put("/api/v1/game/root-balance")
def update_root_balance(update: RootBalanceUpdate):
    """
    Временный технический endpoint.

    На следующем этапе React перестанет использовать его для наград:
    награды будут начисляться только через POST /rewards/...
    """
    global demo_player_root_balance

    demo_player_root_balance = max(0, update.rootBalance)

    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
    }


@app.post("/api/v1/game/rewards/puzzle-a-01")
def claim_puzzle_a_01_reward():
    return claim_reward("puzzle-a-01")
@app.post("/api/v1/game/reset-demo-progress")
def reset_demo_progress():
    global demo_player_root_balance

    demo_player_root_balance = 0
    demo_completed_rewards.clear()

    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
        "completedRewards": [],
    }




@app.post("/api/v1/game/rewards/puzzle-a-02")
def claim_puzzle_a_02_reward():
    return claim_reward("puzzle-a-02")


@app.post("/api/v1/game/rewards/segment-archive-017")
def claim_segment_archive_017_reward():
    return claim_reward("segment-archive-017")