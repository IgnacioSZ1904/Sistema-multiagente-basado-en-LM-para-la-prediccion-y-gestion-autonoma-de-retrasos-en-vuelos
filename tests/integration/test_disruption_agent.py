"""
tests/integration/test_disruption_agent.py
==============================================
Tests de integración del agente de disrupciones CON EL LLM MOCKEADO.

Mismo enfoque que test_analytical_agent.py: las herramientas reales se
ejecutan contra DuckDB, pero el LLM se mockea para no depender de Ollama.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agents.disruption_agent import DisruptionOutput, disruption_agent
from graph.state import SGIDAState


def _copy_state(state: dict) -> SGIDAState:
    """Copia con el tipo correcto para el comprobador estático (ver test_analytical_agent.py)."""
    return cast(SGIDAState, dict(state))


pytestmark = pytest.mark.requires_db


def _make_ai_message_with_tool_call(tool_name: str, tool_args: dict, call_id: str = "call_1"):
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": tool_name, "args": tool_args, "id": call_id}]
    return msg


def _make_ai_message_no_tool_call(content: str = ""):
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


class TestDisruptionAgentHappyPath:
    """Integración: generación de una propuesta completa de extremo a extremo."""

    @patch("agents.disruption_agent.get_llm")
    def test_fills_disruption_proposal_with_expected_fields(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_call(
                "find_alternative_flights",
                {"origin": "Chicago, IL", "destination": "Denver, CO", "scheduled_dep": 1400},
            ),
            _make_ai_message_no_tool_call(),
        ]

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionOutput(
            severity="high",
            actions=["Reasignar pasajeros al vuelo UA890", "Notificar a personal de tierra"],
            affected_passengers_est=150,
            alternative_flights=["UA890 - 16:10"],
            reasoning="Retraso de 52 minutos por causa meteorológica con baja fiabilidad histórica.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = disruption_agent(_copy_state(state_with_disruption_prediction))

        proposal = result["disruption_proposal"]
        assert proposal["severity"] == "high"
        assert len(proposal["actions"]) == 2
        assert proposal["affected_passengers_est"] == 150
        assert proposal["proposal_id"].startswith("PROP-")

    @patch("agents.disruption_agent.get_llm")
    def test_each_call_generates_a_unique_proposal_id(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionOutput(
            severity="medium",
            actions=["Acción de prueba"],
            affected_passengers_est=50,
            alternative_flights=[],
            reasoning="Razonamiento de prueba.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result1 = disruption_agent(_copy_state(state_with_disruption_prediction))
        result2 = disruption_agent(_copy_state(state_with_disruption_prediction))

        assert result1["disruption_proposal"]["proposal_id"] != result2["disruption_proposal"]["proposal_id"]

    @patch("agents.disruption_agent.get_llm")
    def test_empty_alternative_flights_is_handled(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionOutput(
            severity="critical",
            actions=["Notificar a todos los pasajeros afectados"],
            affected_passengers_est=200,
            alternative_flights=[],
            reasoning="No hay vuelos alternativos fiables disponibles en la ventana horaria.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = disruption_agent(_copy_state(state_with_disruption_prediction))

        assert result["disruption_proposal"]["alternative_flights"] == []
        assert result["disruption_proposal"]["severity"] == "critical"


class TestDisruptionAgentToolUsage:
    """Integración: uso correcto de las tres herramientas de disrupción."""

    @patch("agents.disruption_agent.get_llm")
    def test_can_call_multiple_tools_in_sequence(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_call(
                "find_alternative_flights",
                {"origin": "Chicago, IL", "destination": "Denver, CO", "scheduled_dep": 1400},
                call_id="call_1",
            ),
            _make_ai_message_with_tool_call(
                "estimate_affected_passengers",
                {"airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO", "month": 3},
                call_id="call_2",
            ),
            _make_ai_message_no_tool_call(),
        ]

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionOutput(
            severity="high",
            actions=["Acción combinada"],
            affected_passengers_est=150,
            alternative_flights=[],
            reasoning="Basado en dos fuentes de datos.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        disruption_agent(_copy_state(state_with_disruption_prediction))

        assert react_llm.invoke.call_count == 3

    @patch("agents.disruption_agent.get_llm")
    def test_respects_max_tool_calls_limit_of_four(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_with_tool_call(
            "get_airport_ground_activity", {"origin": "Chicago, IL", "scheduled_dep": 1400}
        )

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionOutput(
            severity="medium", actions=["Acción"], affected_passengers_est=0,
            alternative_flights=[], reasoning="Forzado por límite.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        disruption_agent(_copy_state(state_with_disruption_prediction))

        assert react_llm.invoke.call_count == 4  # _MAX_TOOL_CALLS del agente


class TestDisruptionAgentErrorHandling:
    """Integración: degradación a state['error'] en caso de fallo."""

    @patch("agents.disruption_agent.get_llm")
    def test_llm_exception_is_captured_as_state_error(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        mock_get_llm.side_effect = RuntimeError("Ollama no responde")

        result = disruption_agent(_copy_state(state_with_disruption_prediction))

        assert "error" in result
        assert "disruption_agent" in result["error"]

    @patch("agents.disruption_agent.get_llm")
    def test_tool_execution_error_does_not_crash_agent(
        self, mock_get_llm, state_with_disruption_prediction
    ):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_call(
                "find_alternative_flights",
                {"origin": None, "destination": None, "scheduled_dep": "no_es_un_entero"},
            ),
            _make_ai_message_no_tool_call(),
        ]

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = DisruptionOutput(
            severity="low", actions=["Acción mínima"], affected_passengers_est=0,
            alternative_flights=[], reasoning="Datos insuficientes tras error de herramienta.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = disruption_agent(_copy_state(state_with_disruption_prediction))

        # El agente debe seguir funcionando aunque la tool falle internamente.
        assert "error" not in result
        assert result["disruption_proposal"] is not None