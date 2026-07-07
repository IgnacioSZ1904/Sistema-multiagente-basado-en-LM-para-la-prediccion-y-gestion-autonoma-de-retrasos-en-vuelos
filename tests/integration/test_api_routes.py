"""
tests/integration/test_api_routes.py
=======================================
Smoke tests de las rutas de la API con FastAPI TestClient.

Se mockea `backend.app.services.query_service.run_query` para no
depender del grafo real ni de Ollama — esta suite valida el WIRING de
la API (schemas, rutas, history_service), no la lógica de los agentes
(ya cubierta por sus propios tests de integración).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api.app import app
from backend.app.services import history_service


@pytest.fixture(autouse=True)
def _reset_history():
    history_service._history.clear()
    yield
    history_service._history.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _fake_state(**overrides):
    state = {
        "final_response": "Respuesta de prueba.",
        "next_agent": "END",
        "iteration": 2,
        "analytics_result": None,
        "delay_prediction": None,
        "disruption_proposal": None,
        "draft_notifications": [],
        "optimization_criterion": "min_passengers",
        "flight_context": None,
        "error": None,
    }
    state.update(overrides)
    return state


class TestHealthRoute:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestQueryRoute:
    @patch("backend.app.services.query_service.run_query")
    def test_query_returns_final_response_and_draft_notifications(self, mock_run_query, client):
        mock_run_query.return_value = _fake_state(
            draft_notifications=[
                {"recipient_type": "operator", "channel": "operator_dashboard",
                 "message": "Borrador.", "flight_reference": ""},
            ],
        )

        response = client.post("/api/query", json={"query": "¿Qué aeropuertos tienen más retrasos?"})

        assert response.status_code == 200
        data = response.json()
        assert data["final_response"] == "Respuesta de prueba."
        assert data["draft_notifications"][0]["recipient_type"] == "operator"

    @patch("backend.app.services.query_service.run_query")
    def test_query_passes_optimization_criterion_through(self, mock_run_query, client):
        mock_run_query.return_value = _fake_state()

        client.post("/api/query", json={
            "query": "consulta de prueba", "optimization_criterion": "min_cost",
        })

        args, _ = mock_run_query.call_args
        assert args[1] == "min_cost"

    @patch("backend.app.services.query_service.run_query")
    def test_query_records_activity_in_history(self, mock_run_query, client):
        mock_run_query.return_value = _fake_state()

        client.post("/api/query", json={"query": "consulta de prueba"})

        dashboard = client.get("/api/dashboard").json()
        assert dashboard["metrics"]["total_queries"] == 1


class TestDashboardRoute:
    def test_dashboard_returns_empty_state_when_no_activity(self, client):
        response = client.get("/api/dashboard")

        assert response.status_code == 200
        data = response.json()
        assert data["recent_activity"] == []
        assert data["metrics"]["total_queries"] == 0
        assert data["notifications"] == []


class TestNotificationsRoute:
    def test_send_notification_returns_sent_status(self, client, tmp_path, monkeypatch):
        import tools.communication_tools as comm_tools

        temp_log_dir = tmp_path / "notifications_log"
        monkeypatch.setattr(comm_tools, "_LOG_DIR", temp_log_dir)
        monkeypatch.setattr(comm_tools, "_LOG_FILE", temp_log_dir / "notifications.jsonl")

        response = client.post("/api/notifications/send", json={
            "recipient_type": "passenger",
            "message": "Su vuelo sufre un retraso.",
            "flight_reference": "AA1234",
            "channel": "email",
        })

        assert response.status_code == 200
        assert response.json()["status"] == "sent"
