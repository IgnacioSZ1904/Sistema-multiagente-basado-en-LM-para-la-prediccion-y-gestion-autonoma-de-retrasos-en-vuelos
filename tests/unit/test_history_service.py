"""
tests/unit/test_history_service.py
=====================================
Tests de backend/app/services/history_service.py.

El historial es un módulo con estado global en memoria (por diseño:
ver 02_planificacion.md de refactor-agente-comunicacion), así que cada
test limpia la lista interna antes de ejecutarse para no depender del
orden de ejecución de otros tests.
"""

from __future__ import annotations

import pytest

from backend.app.services import history_service


@pytest.fixture(autouse=True)
def _reset_history():
    history_service._history.clear()
    yield
    history_service._history.clear()


class TestRecordActivity:
    def test_record_activity_appends_entry(self):
        history_service.record_activity("consulta 1", "min_passengers", {})
        assert len(history_service.get_recent_activity()) == 1

    def test_record_activity_caps_at_max_history(self):
        for i in range(60):
            history_service.record_activity(f"consulta {i}", "min_passengers", {})
        assert len(history_service._history) == history_service._MAX_HISTORY

    def test_record_activity_stores_relevant_state_fields(self):
        state = {
            "flight_context": {"airline": "AA"},
            "delay_prediction": {"is_disruption": True},
            "disruption_proposal": {"severity": "high"},
            "error": None,
        }
        history_service.record_activity("consulta", "min_cost", state)

        entry = history_service.get_recent_activity()[0]
        assert entry["flight_context"] == {"airline": "AA"}
        assert entry["delay_prediction"] == {"is_disruption": True}
        assert entry["disruption_proposal"] == {"severity": "high"}
        assert entry["optimization_criterion"] == "min_cost"


class TestGetRecentActivity:
    def test_returns_most_recent_first(self):
        history_service.record_activity("primera", "min_passengers", {})
        history_service.record_activity("segunda", "min_passengers", {})

        recent = history_service.get_recent_activity()
        assert recent[0]["query"] == "segunda"
        assert recent[1]["query"] == "primera"

    def test_respects_limit(self):
        for i in range(10):
            history_service.record_activity(f"consulta {i}", "min_passengers", {})

        assert len(history_service.get_recent_activity(limit=3)) == 3


class TestGetMetrics:
    def test_empty_history_has_zeroed_metrics(self):
        metrics = history_service.get_metrics()
        assert metrics == {
            "total_queries": 0,
            "total_disruptions": 0,
            "severity_distribution": {},
        }

    def test_counts_total_queries_and_disruptions(self):
        history_service.record_activity("sin disrupcion", "min_passengers", {
            "delay_prediction": {"is_disruption": False},
        })
        history_service.record_activity("con disrupcion", "min_passengers", {
            "delay_prediction": {"is_disruption": True},
            "disruption_proposal": {"severity": "critical"},
        })

        metrics = history_service.get_metrics()
        assert metrics["total_queries"] == 2
        assert metrics["total_disruptions"] == 1
        assert metrics["severity_distribution"] == {"critical": 1}

    def test_severity_distribution_counts_multiple_entries(self):
        for severity in ["high", "high", "low"]:
            history_service.record_activity("consulta", "min_passengers", {
                "disruption_proposal": {"severity": severity},
            })

        metrics = history_service.get_metrics()
        assert metrics["severity_distribution"] == {"high": 2, "low": 1}
