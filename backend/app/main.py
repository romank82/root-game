from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

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
# После перезапуска backend значение снова станет 0.
demo_player_root_balance = 0


class RootBalanceUpdate(BaseModel):
    rootBalance: int

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
    }
@app.get("/api/v1/game/root-balance")
def get_root_balance():
    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
    }


@app.put("/api/v1/game/root-balance")
def update_root_balance(update: RootBalanceUpdate):
    global demo_player_root_balance

    demo_player_root_balance = max(0, update.rootBalance)

    return {
        "playerId": "demo-player",
        "rootBalance": demo_player_root_balance,
    }