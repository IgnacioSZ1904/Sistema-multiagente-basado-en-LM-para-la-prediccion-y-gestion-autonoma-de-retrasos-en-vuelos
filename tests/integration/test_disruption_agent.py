"""
tests/integration/test_disruption_agent.py
==============================================
Tests de integración del agente de disrupciones.

El agente ya no tiene bucle ReAct: las 3 tools de disrupción se
ejecutan directamente (reales, contra DuckDB) desde código, y la
ÚNICA llamada LLM que queda (`with_structured_output`) se mockea para
no depender de Ollama. Los cálculos deterministas (severity, selección
de alternativa, coste estimado) se prueban también de forma unitaria
pura, sin mocks ni DB, en las clases `TestComputeSeverity`,
`TestSelectBestAlternative` y `TestEstimateOperationalCost`.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from agents.disruption_agent import (
    DisruptionNarrative,
    _compute_severity,
    _estimate_operational_cost,
    _select_best_alternative,
    disruption_agent,
)
from graph.state import SGIDAState


def _copy_state(state: dict) -> SGIDAState:
    """Copia con el tipo correcto para el comprobador estático (ver test_analytical_agent.py)."""
    return cast(SGIDAState, dict(state))


class TestComputeSeverity:
    """Unitarios puros (sin DB, sin LLM) de la regla de severidad por rangos."""

    def test_low_between_15_and_30(self):
        assert _compute_severity(20.0, has_reliable_alternative=True) == "low"

    def test_medium_between_30_and_60(self):
        assert _compute_severity(45.0, has_reliable_alternative=True) == "medium"

    def test_high_between_60_and_120(self):
        assert _compute_severity(90.0, has_reliable_alternative=True) == "high"

    def test_critical_above_120(self):
        assert _compute_severity(150.0, has_reliable_alternative=True) == "critical"

    def test_critical_when_no_reliable_alternative_even_if_delay_is_low(self):
        assert _compute_severity(20.0, has_reliable_alternative=False) == "critical"


class TestSelectBestAlternative:
    """Unitarios puros de la selección determinista de la mejor alternativa."""

    _CANDIDATES = [
        {"airline": "AA", "scheduled_dep": 1400, "avg_arr_delay_min": 5.0,
         "reliability_pct": 60.0, "total_flights": 100},
        {"airline": "UA", "scheduled_dep": 1500, "avg_arr_delay_min": 20.0,
         "reliability_pct": 95.0, "total_flights": 80},
    ]

    def test_empty_candidates_returns_none_and_empty_list(self):
        best, evaluated = _select_best_alternative([], "min_passengers")
        assert best is None
        assert evaluated == []

    def test_min_passengers_prefers_highest_reliability(self):
        best, evaluated = _select_best_alternative(self._CANDIDATES, "min_passengers")
        assert best["airline"] == "UA"
        selected = [c for c in evaluated if c["selected"]]
        assert len(selected) == 1
        assert selected[0]["airline"] == "UA"

    def test_min_cost_prefers_lowest_avg_delay(self):
        best, _ = _select_best_alternative(self._CANDIDATES, "min_cost")
        assert best["airline"] == "AA"

    def test_criteria_can_choose_different_candidates(self):
        best_passengers, _ = _select_best_alternative(self._CANDIDATES, "min_passengers")
        best_cost, _ = _select_best_alternative(self._CANDIDATES, "min_cost")
        assert best_passengers["airline"] != best_cost["airline"]

    def test_all_candidates_are_present_in_evaluated_list(self):
        _, evaluated = _select_best_alternative(self._CANDIDATES, "min_passengers")
        assert len(evaluated) == len(self._CANDIDATES)


class TestEstimateOperationalCost:
    """Unitarios puros del proxy determinista de coste operativo."""

    def test_more_congestion_increases_cost(self):
        low = _estimate_operational_cost(
            {"avg_taxi_out_min": 10.0, "avg_departures_in_hour": 5.0}, num_alternatives_available=5
        )
        high = _estimate_operational_cost(
            {"avg_taxi_out_min": 40.0, "avg_departures_in_hour": 20.0}, num_alternatives_available=5
        )
        assert high > low

    def test_fewer_alternatives_increases_cost(self):
        many = _estimate_operational_cost(
            {"avg_taxi_out_min": 10.0, "avg_departures_in_hour": 5.0}, num_alternatives_available=10
        )
        none_available = _estimate_operational_cost(
            {"avg_taxi_out_min": 10.0, "avg_departures_in_hour": 5.0}, num_alternatives_available=0
        )
        assert none_available > many

    def test_missing_fields_default_to_zero_congestion(self):
        cost = _estimate_operational_cost({}, num_alternatives_available=5)
        assert cost >= 0


@pytest.mark.requires_db
class TestDisruptionAgentHappyPath:
    """Integración: generación de una propuesta completa de extremo a extremo."""

    @patch("agents.disruption_agent.get_llm")
    def test_fills_disruption_proposal_with_expected_fields(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionNarrative(
            actions=["Reasignar pasajeros a la mejor alternativa disponible",
                     "Notificar a personal de tierra"],
            reasoning="Retraso de 52 minutos por causa meteorológica; se prioriza "
            "la alternativa más fiable según el criterio activo.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = disruption_agent(_copy_state(state_with_disruption_prediction))

        proposal = result["disruption_proposal"]
        assert len(proposal["actions"]) == 2
        assert proposal["proposal_id"].startswith("PROP-")
        assert proposal["optimization_criterion"] == "min_passengers"
        assert proposal["source_context"]["flight_context"]["airline"] == "AA"

    @patch("agents.disruption_agent.get_llm")
    def test_each_call_generates_a_unique_proposal_id(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionNarrative(
            actions=["Acción de prueba"], reasoning="Razonamiento de prueba.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result1 = disruption_agent(_copy_state(state_with_disruption_prediction))
        result2 = disruption_agent(_copy_state(state_with_disruption_prediction))

        assert result1["disruption_proposal"]["proposal_id"] != result2["disruption_proposal"]["proposal_id"]

    @patch("agents.disruption_agent.get_llm")
    def test_uses_optimization_criterion_from_state(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionNarrative(
            actions=["Acción de prueba"], reasoning="Razonamiento de prueba.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_with_disruption_prediction)
        state["optimization_criterion"] = "min_cost"

        result = disruption_agent(state)

        assert result["disruption_proposal"]["optimization_criterion"] == "min_cost"


@pytest.mark.requires_db
class TestDisruptionAgentSingleLLMCall:
    """Integración: el agente ya no tiene bucle ReAct, solo una llamada LLM."""

    @patch("agents.disruption_agent.get_llm")
    def test_only_one_llm_call_is_made(self, mock_get_llm, state_with_disruption_prediction):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionNarrative(
            actions=["Acción de prueba"], reasoning="Razonamiento de prueba.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        disruption_agent(_copy_state(state_with_disruption_prediction))

        assert base_llm.with_structured_output.call_count == 1
        assert structured_llm.invoke.call_count == 1
        assert base_llm.bind_tools.called is False


@pytest.mark.requires_db
class TestDisruptionAgentJSONContext:
    """Integración: el contexto pasado al LLM va serializado como JSON explícito."""

    @patch("agents.disruption_agent.get_llm")
    def test_context_is_serialized_as_json_in_the_prompt(
        self, mock_get_llm, state_with_disruption_prediction, sample_analytics_result
    ):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionNarrative(
            actions=["Acción de prueba"], reasoning="Razonamiento de prueba.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_with_disruption_prediction)
        state["analytics_result"] = sample_analytics_result

        disruption_agent(state)

        human_message = structured_llm.invoke.call_args.args[0][1]
        assert '"optimization_criterion"' in human_message.content
        assert "{'optimization_criterion'" not in human_message.content  # no es un repr() de dict


@pytest.mark.requires_db
class TestDisruptionAgentErrorHandling:
    """Integración: degradación a state['error'] en caso de fallo, sin romper por datos faltantes."""

    @patch("agents.disruption_agent.get_llm")
    def test_llm_exception_is_captured_as_state_error(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        mock_get_llm.side_effect = RuntimeError("Ollama no responde")

        result = disruption_agent(_copy_state(state_with_disruption_prediction))

        assert "error" in result
        assert "disruption_agent" in result["error"]

    def test_missing_flight_context_does_not_crash(self, state_fresh, sample_delay_prediction_disrupted):
        # Sin flight_context, las 3 tools se omiten (defaults vacíos);
        # el agente debe seguir funcionando en vez de fallar.
        state = _copy_state(state_fresh)
        state["delay_prediction"] = sample_delay_prediction_disrupted

        with patch("agents.disruption_agent.get_llm") as mock_get_llm:
            structured_llm = MagicMock()
            structured_llm.invoke.return_value = DisruptionNarrative(
                actions=["Revisar manualmente"],
                reasoning="Sin datos de vuelo concreto disponibles.",
            )
            base_llm = MagicMock()
            base_llm.with_structured_output.return_value = structured_llm
            mock_get_llm.return_value = base_llm

            result = disruption_agent(state)

        assert "error" not in result
        assert result["disruption_proposal"]["alternative_flights"] == []


class TestDisruptionAgentDegradedMode:
    """Modo degradado: Ollama no disponible."""

    @patch("agents.disruption_agent.Settings.ollama_available", return_value=False)
    def test_degraded_mode_returns_minimal_proposal_without_calling_llm(
        self, mock_ollama_available, state_with_disruption_prediction
    ):
        with patch("agents.disruption_agent.get_llm") as mock_get_llm:
            result = disruption_agent(_copy_state(state_with_disruption_prediction))
            mock_get_llm.assert_not_called()

        proposal = result["disruption_proposal"]
        assert proposal["severity"] == "medium"
        assert proposal["alternatives_considered"] == []
        assert proposal["estimated_operational_cost"] is None
