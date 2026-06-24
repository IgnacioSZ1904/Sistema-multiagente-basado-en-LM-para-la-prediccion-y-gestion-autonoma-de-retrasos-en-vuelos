from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas import HealthResponse
from config.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model=Settings.OLLAMA_MODEL,
        db_path=Settings.DB_PATH,
    )
