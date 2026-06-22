"""
tests/integration/test_analytical_agent.py
==============================================
Tests de integración del agente analítico CON EL LLM MOCKEADO.

No requieren Ollama corriendo. Se mockea get_llm() para devolver un
doble que simula tanto la fase ReAct (bind_tools + tool_calls) como la
fase de síntesis estructurada (with_structured_output), validando que
analytical_agent() integra correctamente ambas fases con el estado del
grafo y con tools/analytical_tools.py.

Nota: estos tests SÍ ejecutan las herramientas reales contra DuckDB
(no se mockean las tools), porque son deterministas y rápidas; lo que
se mockea es únicamente el LLM, que es la fuente de no determinismo y
de dependencia de un servicio externo.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agents.analytical_agent import AnalyticalOutput, analytical_agent
from graph.state import SGIDAState


def _copy_state(state: dict) -> SGIDAState:
    """
    Copia superficial de un estado de prueba con el tipo correcto para
    el comprobador estático (Pylance/mypy). dict(state) en tiempo de
    ejecución ya produce un objeto perfectamente válido como SGIDAState
    (un TypedDict es un dict normal); este cast solo informa al analizador
    estático, no cambia el comportamiento en tiempo de ejecución.
    """
    return cast(SGIDAState, dict(state))


pytestmark = pytest.mark.requires_db


def _make_ai_message_with_tool_call(tool_name: str, tool_args: dict, call_id: str = "call_1"):
    """Construye un AIMessage que simula que el LLM decidió llamar a una tool."""
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": tool_name, "args": tool_args, "id": call_id}]
    return msg


def _make_ai_message_no_tool_call(content: str = ""):
    """Construye un AIMessage que simula que el LLM ya no necesita más tools."""
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


class TestAnalyticalAgentExploratoryMode:
    """Integración: consulta exploratoria de extremo a extremo, LLM mockeado."""

    @patch("agents.analytical_agent.get_llm")
    def test_exploratory_query_fills_analytics_result(self, mock_get_llm, state_fresh):
        # --- Mock de la fase ReAct (llm.bind_tools(...).invoke(...)) ---
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_call("get_top_delay_airports", {"limit": 5}),
            _make_ai_message_no_tool_call(),
        ]

        # --- Mock de la fase de síntesis (llm.with_structured_output(...).invoke(...)) ---
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="exploratory",
            exploratory_summary={"top_delay_airports": "Chicago presenta el mayor retraso medio."},
            narrative_summary="Chicago es el aeropuerto con mayor retraso medio histórico.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        state["user_query"] = "¿Qué aeropuertos tienen más retrasos?"

        result = analytical_agent(state)

        assert result["analytics_result"] is not None
        assert "messages" in result
        assert result["analytics_result"]["summary_stats"] == {
            "top_delay_airports": "Chicago presenta el mayor retraso medio."
        }

    @patch("agents.analytical_agent.get_llm")
    def test_exploratory_query_does_not_fill_delay_prediction(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="exploratory",
            exploratory_summary={},
            narrative_summary="Sin hallazgos relevantes.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert "delay_prediction" not in result


class TestAnalyticalAgentPredictionMode:
    """Integración: consulta de predicción de un vuelo concreto, LLM mockeado."""

    @patch("agents.analytical_agent.get_llm")
    def test_prediction_query_fills_delay_prediction(
        self, mock_get_llm, state_fresh, sample_flight_context
    ):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_call(
                "predict_flight_delay",
                {
                    "airline": "AA", "origin": "Chicago, IL",
                    "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
                },
            ),
            _make_ai_message_no_tool_call(),
        ]

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="prediction",
            expected_dep_delay_min=42.0,
            expected_arr_delay_min=48.0,
            is_disruption=True,
            confidence=0.7,
            main_cause="weather",
            narrative_summary="Se espera un retraso significativo por causas meteorológicas.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        state["flight_context"] = sample_flight_context
        state["user_query"] = "Predice el retraso del vuelo AA Chicago-Denver en marzo a las 14:00"

        result = analytical_agent(state)

        assert result["delay_prediction"]["is_disruption"] is True
        assert result["delay_prediction"]["main_cause"] == "weather"
        assert result["delay_prediction"]["confidence"] == 0.7

    @patch("agents.analytical_agent.get_llm")
    def test_prediction_with_no_disruption(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="prediction",
            expected_dep_delay_min=5.0,
            expected_arr_delay_min=3.0,
            is_disruption=False,
            confidence=0.9,
            main_cause="unknown",
            narrative_summary="No se espera disrupción significativa.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert result["delay_prediction"]["is_disruption"] is False


class TestAnalyticalAgentReactLoopBehavior:
    """Integración: comportamiento del bucle ReAct ante distintos escenarios del LLM."""

    @patch("agents.analytical_agent.get_llm")
    def test_stops_loop_when_llm_requests_no_tool_calls(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="exploratory",
            narrative_summary="Sin datos.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        analytical_agent(_copy_state(state_fresh))

        # El bucle debe parar tras la primera invocación, sin más llamadas.
        assert react_llm.invoke.call_count == 1

    @patch("agents.analytical_agent.get_llm")
    def test_respects_max_tool_calls_limit(self, mock_get_llm, state_fresh):
        # El LLM "insiste" en pedir tools indefinidamente; el bucle debe
        # detenerse tras _MAX_TOOL_CALLS iteraciones (5), no continuar para siempre.
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_with_tool_call(
            "get_delay_by_month", {}
        )

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="exploratory",
            narrative_summary="Resultado forzado tras agotar el límite.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert react_llm.invoke.call_count == 5  # _MAX_TOOL_CALLS
        assert "error" not in result  # debe sintetizar igualmente, no fallar

    @patch("agents.analytical_agent.get_llm")
    def test_unknown_tool_name_does_not_crash_the_agent(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_call("herramienta_inexistente", {}),
            _make_ai_message_no_tool_call(),
        ]

        structured_llm = MagicMock()
        structured_llm.invoke.return_value = AnalyticalOutput(
            response_mode="exploratory",
            narrative_summary="Se gestionó el error de herramienta correctamente.",
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert "error" not in result
        assert result["analytics_result"] is not None


class TestAnalyticalAgentErrorHandling:
    """Integración: el agente debe degradar a state['error'], no lanzar excepción."""

    @patch("agents.analytical_agent.get_llm")
    def test_llm_exception_is_captured_as_state_error(self, mock_get_llm, state_fresh):
        mock_get_llm.side_effect = RuntimeError("Ollama no responde")

        result = analytical_agent(_copy_state(state_fresh))

        assert "error" in result
        assert "analytical_agent" in result["error"]

    @patch("agents.analytical_agent.get_llm")
    def test_agent_does_not_raise_on_synthesis_failure(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        structured_llm = MagicMock()
        structured_llm.invoke.side_effect = ValueError("Esquema inválido devuelto por el LLM")

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        # No debe lanzar; debe devolver un dict con 'error'.
        result = analytical_agent(_copy_state(state_fresh))
        assert "error" in result