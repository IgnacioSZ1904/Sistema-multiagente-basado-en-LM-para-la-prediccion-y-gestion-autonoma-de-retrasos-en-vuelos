from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas import QueryRequest, QueryResponse
from backend.app.services.query_service import QueryService

router = APIRouter(tags=["query"])
service = QueryService()


@router.post("/query", response_model=QueryResponse)
def execute_query(payload: QueryRequest) -> QueryResponse:
    return service.execute(payload.query)
