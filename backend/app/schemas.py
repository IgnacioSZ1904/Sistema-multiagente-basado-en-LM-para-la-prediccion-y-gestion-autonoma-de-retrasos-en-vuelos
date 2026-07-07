from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    optimization_criterion: str | None = Field(
        default=None,
        description='Criterio de optimización para el agente de disrupciones: '
        '"min_passengers" | "min_cost". Si se omite, se usa el valor por '
        "defecto configurado en el sistema.",
    )


class QueryResponse(BaseModel):
    final_response: str
    next_agent: str
    iteration: int
    analytics_result: dict[str, Any] | None = None
    delay_prediction: dict[str, Any] | None = None
    disruption_proposal: dict[str, Any] | None = None
    draft_notifications: list[dict[str, Any]] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    model: str
    db_path: str


class NotificationSendRequest(BaseModel):
    recipient_type: str = Field(description='"operator" | "passenger" | "ground_staff"')
    message: str = Field(min_length=1)
    flight_reference: str = ""
    channel: str = "email"


class DashboardResponse(BaseModel):
    recent_activity: list[dict[str, Any]]
    metrics: dict[str, Any]
    notifications: list[dict[str, Any]]
