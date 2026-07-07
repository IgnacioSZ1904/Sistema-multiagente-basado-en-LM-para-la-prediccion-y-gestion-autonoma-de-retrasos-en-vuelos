from __future__ import annotations

from graph.supervisor import run_query

from backend.app.schemas import QueryResponse
from backend.app.services import history_service


class QueryService:
    def execute(self, query: str, optimization_criterion: str | None = None) -> QueryResponse:
        state = run_query(query, optimization_criterion)

        effective_criterion = state.get("optimization_criterion") or optimization_criterion or ""
        history_service.record_activity(query, effective_criterion, state)

        return QueryResponse(
            final_response=state.get("final_response") or "",
            next_agent=state.get("next_agent", "END"),
            iteration=state.get("iteration", 0),
            analytics_result=state.get("analytics_result"),
            delay_prediction=state.get("delay_prediction"),
            disruption_proposal=state.get("disruption_proposal"),
            draft_notifications=state.get("draft_notifications"),
            error=state.get("error"),
        )
