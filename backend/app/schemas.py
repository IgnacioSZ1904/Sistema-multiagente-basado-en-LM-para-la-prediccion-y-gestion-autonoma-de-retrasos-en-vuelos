from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)


class QueryResponse(BaseModel):
    final_response: str
    next_agent: str
    iteration: int
    analytics_result: dict[str, Any] | None = None
    delay_prediction: dict[str, Any] | None = None
    disruption_proposal: dict[str, Any] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    model: str
    db_path: str
