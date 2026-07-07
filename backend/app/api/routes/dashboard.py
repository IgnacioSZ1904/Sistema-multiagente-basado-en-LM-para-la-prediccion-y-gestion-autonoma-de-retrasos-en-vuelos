from __future__ import annotations

import json

from fastapi import APIRouter

from backend.app.schemas import DashboardResponse
from backend.app.services import history_service
from tools.communication_tools import get_notification_history

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard() -> DashboardResponse:
    notifications = json.loads(get_notification_history.invoke({"limit": 20}))
    return DashboardResponse(
        recent_activity=history_service.get_recent_activity(),
        metrics=history_service.get_metrics(),
        notifications=notifications,
    )
