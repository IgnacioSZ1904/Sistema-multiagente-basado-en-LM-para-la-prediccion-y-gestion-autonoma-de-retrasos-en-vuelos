from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas import RoutesResponse
from backend.app.services import routes_service

router = APIRouter(tags=["routes"])


@router.get("/routes", response_model=RoutesResponse)
def get_routes() -> RoutesResponse:
    return RoutesResponse(**routes_service.get_routes())
