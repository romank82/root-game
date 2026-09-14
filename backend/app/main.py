from fastapi import FastAPI
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
            "rootBalance": 0,
        },
        "activeMission": None,
        "inventory": [],
        "storyNodes": [],
    }