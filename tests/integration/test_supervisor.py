"""
tests/integration/test_supervisor.py
=========================================
Tests de integración del supervisor y del StateGraph completo.

El supervisor es 100% determinista (ver `revision-supervisor`): ya no
consulta ningún LLM, así que `TestSupervisorNodeIsolated` no mockea
nada — llama directamente a `supervisor(state)` y comprueba `next_agent`
según las reglas de `graph/router.py`.

`TestFullGraphEndToEnd` sigue mockeando `get_llm()` de los tres agentes
especializados (analítico, disrupción, comunicación), que sí lo usan.
"""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agents.communication_agent import CommunicationOutput
from graph.state import SGIDAState, initial_state
from graph.supervisor import build_graph, supervisor


def _copy_state(state: dict) -> SGIDAState:
    """Copia con el tipo correcto para el comprobador estático (ver test_analytical_agent.py)."""
    return cast(SGIDAState, dict(state))


def _make_ai_message_no_tool_call(content: str = "Respuesta de prueba."):
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


def _make_ai_message_with_tool_call(tool_name: str, tool_args: dict, call_id: str = "call_1"):
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": tool_name, "args": tool_args, "id": call_id}]
    return msg


class TestSupervisorNodeIsolated:
    """Tests del nodo supervisor() de forma aislada. Enteramente determinista, sin LLM."""

    def test_routes_to_analytical_agent_when_state_is_fresh(self, state_fresh):
        result = supervisor(_copy_state(state_fresh))
        assert result["next_agent"] == "analytical_agent"

    def test_increments_iteration_counter(self, state_fresh):
        state = _copy_state(state_fresh)
        state["iteration"] = 3

        result = supervisor(state)

        assert result["iteration"] == 4

    def test_routes_to_communication_agent_when_exploratory_result_present(
        self, state_with_exploratory_result
    ):
        result = supervisor(_copy_state(state_with_exploratory_result))
        assert result["next_agent"] == "communication_agent"

    def test_routes_to_disruption_agent_when_disruption_detected(
        self, state_with_disruption_prediction
    ):
        result = supervisor(_copy_state(state_with_disruption_prediction))
        assert result["next_agent"] == "disruption_agent"

    def test_routes_to_communication_agent_when_disruption_proposal_present(
        self, state_with_disruption_proposal
    ):
        result = supervisor(_copy_state(state_with_disruption_proposal))
        assert result["next_agent"] == "communication_agent"

    def test_routes_to_communication_agent_when_error_present(self, state_with_error):
        result = supervisor(_copy_state(state_with_error))
        assert result["next_agent"] == "communication_agent"

    def test_routes_to_end_when_final_response_exists(self, state_with_final_response):
        result = supervisor(_copy_state(state_with_final_response))
        assert result["next_agent"] == "END"

    @patch("config.settings.Settings.GRAPH_MAX_ITERATIONS", 2)
    def test_respects_iteration_limit(self, state_fresh):
        state = _copy_state(state_fresh)
        state["iteration"] = 2

        result = supervisor(state)

        assert result["next_agent"] == "communication_agent"


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
    Integración de extremo a extremo: grafo completo con el LLM de los
    tres agentes especializados mockeado (el supervisor ya no usa LLM).
    """

    @patch("agents.communication_agent.get_llm")
    @patch("agents.disruption_agent.get_llm")
    @patch("agents.analytical_agent.get_llm")
    def test_exploratory_flow_reaches_end_with_final_response(
        self, mock_analytical_llm, mock_disruption_llm, mock_communication_llm,
    ):
        # --- Agente analítico: sin tool calls, ensamblaje determinista directo ---
        analytical_react = MagicMock()
        analytical_react.invoke.return_value = _make_ai_message_no_tool_call()
        analytical_base = MagicMock()
        analytical_base.bind_tools.return_value = analytical_react
        mock_analytical_llm.return_value = analytical_base

        # --- Agente de comunicación: única llamada with_structured_output ---
        communication_structured = MagicMock()
        communication_structured.invoke.return_value = CommunicationOutput(
            final_response="Chicago es el aeropuerto con mayor retraso medio histórico.",
            draft_notifications=[],
        )
        communication_base = MagicMock()
        communication_base.with_structured_output.return_value = communication_structured
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

    @patch("agents.communication_agent.get_llm")
    @patch("agents.disruption_agent.get_llm")
    @patch("agents.analytical_agent.get_llm")
    def test_iteration_limit_forces_early_termination_before_disruption_agent(
        self, mock_analytical_llm, mock_disruption_llm, mock_communication_llm,
    ):
        # El agente analítico detecta una disrupción (tool mockeada con
        # datos garantizados, sin depender del contenido real de la BD).
        analytical_react = MagicMock()
        analytical_react.invoke.side_effect = [
            _make_ai_message_with_tool_call(
                "get_flight_historical_stats",
                {"airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
                 "month": 3, "scheduled_dep": 1400},
            ),
            _make_ai_message_no_tool_call(),
        ]
        analytical_base = MagicMock()
        analytical_base.bind_tools.return_value = analytical_react
        mock_analytical_llm.return_value = analytical_base

        fake_stats_tool = MagicMock()
        fake_stats_tool.invoke.return_value = json.dumps({
            "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
            "month": 3, "scheduled_dep": 1400,
            "avg_dep_delay_min": 90.0, "avg_arr_delay_min": 95.0,
            "pct_over_threshold": 80.0, "sample_size": 250,
            "dominant_delay_cause": "weather",
        })

        communication_structured = MagicMock()
        communication_structured.invoke.return_value = CommunicationOutput(
            final_response="Respuesta forzada por límite de iteraciones.",
            draft_notifications=[],
        )
        communication_base = MagicMock()
        communication_base.with_structured_output.return_value = communication_structured
        mock_communication_llm.return_value = communication_base

        # disruption_agent NO debería llegar a ejecutarse: el límite de
        # iteraciones debe forzar la salida antes de que el supervisor lo alcance,
        # aunque el estado ya indique una disrupción.
        mock_disruption_llm.side_effect = AssertionError(
            "disruption_agent no debería ejecutarse: el límite de iteraciones debe cortar el flujo antes."
        )

        with patch.dict(
            "agents.analytical_agent._TOOLS_BY_NAME",
            {"get_flight_historical_stats": fake_stats_tool},
        ), patch("config.settings.Settings.GRAPH_MAX_ITERATIONS", 1):
            app = build_graph()
            final_state = app.invoke(
                initial_state("Predice el retraso del vuelo AA Chicago-Denver en marzo a las 14:00")
            )

        assert final_state["final_response"] == "Respuesta forzada por límite de iteraciones."
        assert final_state["disruption_proposal"] is None
        assert final_state["delay_prediction"]["is_disruption"] is True
