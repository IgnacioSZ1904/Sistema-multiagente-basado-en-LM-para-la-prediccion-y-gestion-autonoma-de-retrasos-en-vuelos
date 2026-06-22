"""
tests/integration/test_supervisor.py
=========================================
Tests de integración del supervisor y del StateGraph completo,
CON EL LLM MOCKEADO.

Dos niveles de integración cubiertos:
  1. supervisor() de forma aislada: la decisión de routing del LLM se
     traduce correctamente en next_agent, pasando por safe_next_node().
  2. build_graph() completo: se mockea get_llm() globalmente (afecta a
     supervisor Y a los tres agentes) para ejecutar un flujo de extremo
     a extremo sin Ollama, verificando que la topología del grafo
     conecta correctamente los nodos.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from graph.state import SGIDAState, initial_state
from graph.supervisor import RoutingDecision, build_graph, supervisor


def _copy_state(state: dict) -> SGIDAState:
    """Copia con el tipo correcto para el comprobador estático (ver test_analytical_agent.py)."""
    return cast(SGIDAState, dict(state))


def _make_ai_message_no_tool_call(content: str = "Respuesta de prueba."):
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


class TestSupervisorNodeIsolated:
    """Tests del nodo supervisor() de forma aislada (sin el resto del grafo)."""

    @patch("graph.supervisor.get_llm")
    def test_valid_llm_decision_sets_next_agent(self, mock_get_llm, state_fresh):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = RoutingDecision(
            next_node="analytical_agent",
            rationale="No hay resultados previos; se necesita analizar datos.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = supervisor(_copy_state(state_fresh))

        assert result["next_agent"] == "analytical_agent"

    @patch("graph.supervisor.get_llm")
    def test_increments_iteration_counter(self, mock_get_llm, state_fresh):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = RoutingDecision(
            next_node="analytical_agent", rationale="Test."
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        state["iteration"] = 3

        result = supervisor(state)

        assert result["iteration"] == 4

    @patch("graph.supervisor.get_llm")
    def test_routing_decision_passes_through_safety_net(
        self, mock_get_llm, state_with_exploratory_result
    ):
        # El LLM decide (incorrectamente) volver a analytical_agent aunque
        # ya hay analytics_result; safe_next_node debe corregirlo.
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = RoutingDecision(
            next_node="analytical_agent",
            rationale="Decisión incorrecta simulada del LLM.",
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = supervisor(_copy_state(state_with_exploratory_result))

        # La salvaguarda debe redirigir a communication_agent, no analytical_agent.
        assert result["next_agent"] == "communication_agent"

    @patch("graph.supervisor.get_llm")
    def test_llm_exception_falls_back_to_communication_agent(
        self, mock_get_llm, state_fresh
    ):
        mock_get_llm.side_effect = RuntimeError("Ollama no responde")

        result = supervisor(_copy_state(state_fresh))

        # No debe lanzar excepción; debe degradar a communication_agent
        # para que el operador reciba algún tipo de respuesta.
        assert result["next_agent"] == "communication_agent"

    @patch("graph.supervisor.get_llm")
    def test_routing_to_end_when_final_response_exists(
        self, mock_get_llm, state_with_final_response
    ):
        structured_llm = MagicMock()
        structured_llm.invoke.return_value = RoutingDecision(
            next_node="END", rationale="La respuesta final ya está lista."
        )
        base_llm = MagicMock()
        base_llm.with_structured_output.return_value = structured_llm
        mock_get_llm.return_value = base_llm

        result = supervisor(_copy_state(state_with_final_response))

        assert result["next_agent"] == "END"


class TestGraphTopology:
    """Tests de la estructura del grafo compilado, sin invocar al LLM."""

    def test_graph_compiles_without_errors(self):
        app = build_graph()
        assert app is not None

    def test_graph_contains_all_expected_nodes(self):
        app = build_graph()
        nodes = set(app.get_graph().nodes.keys())
        expected = {
            "__start__", "supervisor", "analytical_agent",
            "disruption_agent", "communication_agent", "__end__",
        }
        assert expected.issubset(nodes)

    def test_entry_point_is_supervisor(self):
        app = build_graph()
        graph_repr = app.get_graph()
        start_edges = [e for e in graph_repr.edges if e.source == "__start__"]
        assert len(start_edges) == 1
        assert start_edges[0].target == "supervisor"


@pytest.mark.requires_db
class TestFullGraphEndToEnd:
    """
    Integración de extremo a extremo: grafo completo con LLM mockeado
    globalmente (afecta a supervisor y a los tres agentes, que importan
    get_llm desde config.settings o lo usan vía sus propios módulos).

    Marcado con requires_db porque analytical_agent y disruption_agent
    ejecutan tools reales contra DuckDB durante su fase ReAct.
    """

    @patch("agents.communication_agent.get_llm")
    @patch("agents.disruption_agent.get_llm")
    @patch("agents.analytical_agent.get_llm")
    @patch("graph.supervisor.get_llm")
    def test_exploratory_flow_reaches_end_with_final_response(
        self, mock_supervisor_llm, mock_analytical_llm,
        mock_disruption_llm, mock_communication_llm,
    ):
        # --- Supervisor: analytical_agent -> communication_agent -> END ---
        supervisor_structured = MagicMock()
        supervisor_structured.invoke.side_effect = [
            RoutingDecision(next_node="analytical_agent", rationale="Falta analizar."),
            RoutingDecision(next_node="communication_agent", rationale="Ya hay resultado."),
            RoutingDecision(next_node="END", rationale="Respuesta lista."),
        ]
        supervisor_base = MagicMock()
        supervisor_base.with_structured_output.return_value = supervisor_structured
        mock_supervisor_llm.return_value = supervisor_base

        # --- Agente analítico: sin tool calls, síntesis exploratoria directa ---
        from agents.analytical_agent import AnalyticalOutput

        analytical_react = MagicMock()
        analytical_react.invoke.return_value = _make_ai_message_no_tool_call()
        analytical_structured = MagicMock()
        analytical_structured.invoke.return_value = AnalyticalOutput(
            response_mode="exploratory",
            exploratory_summary={"insight": "Chicago tiene el mayor retraso medio."},
            narrative_summary="Chicago presenta el mayor retraso medio histórico.",
        )
        analytical_base = MagicMock()
        analytical_base.bind_tools.return_value = analytical_react
        analytical_base.with_structured_output.return_value = analytical_structured
        mock_analytical_llm.return_value = analytical_base

        # --- Agente de comunicación: redacta la respuesta final ---
        communication_llm = MagicMock()
        communication_llm.invoke.return_value = _make_ai_message_no_tool_call(
            "Chicago es el aeropuerto con mayor retraso medio histórico."
        )
        communication_base = MagicMock()
        communication_base.bind_tools.return_value = communication_llm
        mock_communication_llm.return_value = communication_base

        # disruption_agent no debería llegar a invocarse en este flujo.
        mock_disruption_llm.side_effect = AssertionError(
            "disruption_agent no debería ejecutarse en un flujo puramente exploratorio."
        )

        app = build_graph()
        final_state = app.invoke(initial_state("¿Qué aeropuertos tienen más retrasos?"))

        assert final_state["final_response"] == (
            "Chicago es el aeropuerto con mayor retraso medio histórico."
        )
        assert final_state["analytics_result"] is not None
        assert final_state["disruption_proposal"] is None

    @patch("graph.supervisor.get_llm")
    def test_graph_terminates_via_iteration_limit_if_llm_loops(self, mock_supervisor_llm):
        # El supervisor siempre "decide" volver a analytical_agent, simulando
        # una decisión defectuosa persistente del LLM. El límite de
        # iteraciones (vía safe_next_node) debe forzar la terminación.
        from agents.analytical_agent import AnalyticalOutput

        supervisor_structured = MagicMock()
        supervisor_structured.invoke.return_value = RoutingDecision(
            next_node="analytical_agent", rationale="Decisión repetida simulada."
        )
        supervisor_base = MagicMock()
        supervisor_base.with_structured_output.return_value = supervisor_structured
        mock_supervisor_llm.return_value = supervisor_base

        with patch("agents.analytical_agent.get_llm") as mock_analytical_llm, \
             patch("agents.communication_agent.get_llm") as mock_communication_llm, \
             patch("config.settings.Settings.GRAPH_MAX_ITERATIONS", 3):

            analytical_react = MagicMock()
            analytical_react.invoke.return_value = _make_ai_message_no_tool_call()
            analytical_structured = MagicMock()
            analytical_structured.invoke.return_value = AnalyticalOutput(
                response_mode="exploratory", narrative_summary="Resultado parcial.",
            )
            analytical_base = MagicMock()
            analytical_base.bind_tools.return_value = analytical_react
            analytical_base.with_structured_output.return_value = analytical_structured
            mock_analytical_llm.return_value = analytical_base

            communication_llm = MagicMock()
            communication_llm.invoke.return_value = _make_ai_message_no_tool_call(
                "Respuesta forzada por límite de iteraciones."
            )
            communication_base = MagicMock()
            communication_base.bind_tools.return_value = communication_llm
            mock_communication_llm.return_value = communication_base

            app = build_graph()
            final_state = app.invoke(initial_state("consulta de prueba"))

        # El grafo debe terminar (no colgarse en bucle infinito) y producir
        # una respuesta final gracias a la salvaguarda de iteraciones.
        assert final_state["final_response"] is not None