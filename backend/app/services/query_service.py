from __future__ import annotations

from graph.supervisor import run_query

from backend.app.schemas import QueryResponse


class QueryService:
    def execute(self, query: str) -> QueryResponse:
        state = run_query(query)
        return QueryResponse(
            final_response=state.get("final_response") or "",
            next_agent=state.get("next_agent", "END"),
            iteration=state.get("iteration", 0),
            analytics_result=state.get("analytics_result"),
            delay_prediction=state.get("delay_prediction"),
            disruption_proposal=state.get("disruption_proposal"),
            error=state.get("error"),
        )
