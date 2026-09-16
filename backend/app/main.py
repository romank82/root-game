from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.mission_engine import (
    MissionEngineError,
    get_bootstrap as get_engine_bootstrap,
    reset_demo_engine_progress,
    submit_mission,
)

DEMO_PLAYER_ID = "demo-player"

app = FastAPI(
    title="CHIMERA Protocol API",
    version="0.4.0",
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


class MissionSubmitPayload(BaseModel):
    answer: str | None = None
    sequence: list[str] | None = None


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "chimera-api",
        "version": "0.4.0",
        "storage": "sqlalchemy",
    }


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
