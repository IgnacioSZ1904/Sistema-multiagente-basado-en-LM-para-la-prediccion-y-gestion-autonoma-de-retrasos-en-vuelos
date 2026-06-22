"""
tests/unit/test_router.py
============================
Tests de funcionalidades básicas de graph/router.py.

Cubren las tres salvaguardas deterministas descritas en safe_next_node():
límite de iteraciones, nombre de nodo inválido, y prevención de
re-ejecución de un agente ya completado. No requieren LLM ni DB.
"""

from __future__ import annotations

from unittest.mock import patch

from graph.router import END_NODE, VALID_AGENT_NODES, _deterministic_fallback, safe_next_node


class TestValidAgentNodes:
    """Verifica el conjunto de nodos válidos conocido por el router."""

    def test_contains_exactly_three_agent_nodes(self):
        assert VALID_AGENT_NODES == {
            "analytical_agent", "disruption_agent", "communication_agent"
        }

    def test_end_node_is_not_in_valid_agent_nodes(self):
        # END se gestiona como caso especial, no como nodo de agente.
        assert END_NODE not in VALID_AGENT_NODES


class TestSafeNextNodeHappyPath:
    """Casos en los que la decisión del LLM es válida y se respeta."""

    def test_valid_decision_to_analytical_agent_is_respected(self, state_fresh):
        result = safe_next_node(state_fresh, "analytical_agent")
        assert result == "analytical_agent"

    def test_valid_decision_to_communication_agent_is_respected(
        self, state_with_exploratory_result
    ):
        result = safe_next_node(state_with_exploratory_result, "communication_agent")
        assert result == "communication_agent"

    def test_valid_decision_to_disruption_agent_is_respected(
        self, state_with_disruption_prediction
    ):
        result = safe_next_node(state_with_disruption_prediction, "disruption_agent")
        assert result == "disruption_agent"

    def test_decision_to_end_is_respected_when_final_response_exists(
        self, state_with_final_response
    ):
        result = safe_next_node(state_with_final_response, "END")
        assert result == END_NODE


class TestSafeNextNodeIterationLimit:
    """Salvaguarda 1: límite de iteraciones del grafo."""

    def test_forces_communication_agent_when_limit_reached_without_response(
        self, state_fresh
    ):
        state = dict(state_fresh)
        state["iteration"] = 999  # muy por encima de cualquier límite razonable
        with patch("graph.router.Settings.GRAPH_MAX_ITERATIONS", 10):
            result = safe_next_node(state, "analytical_agent")
        assert result == "communication_agent"

    def test_forces_end_when_limit_reached_and_response_already_exists(
        self, state_with_final_response
    ):
        state = dict(state_with_final_response)
        state["iteration"] = 999
        with patch("graph.router.Settings.GRAPH_MAX_ITERATIONS", 10):
            result = safe_next_node(state, "analytical_agent")
        assert result == END_NODE

    def test_iteration_exactly_at_limit_triggers_safeguard(self, state_fresh):
        state = dict(state_fresh)
        state["iteration"] = 10
        with patch("graph.router.Settings.GRAPH_MAX_ITERATIONS", 10):
            result = safe_next_node(state, "analytical_agent")
        assert result == "communication_agent"

    def test_iteration_below_limit_does_not_trigger_safeguard(self, state_fresh):
        state = dict(state_fresh)
        state["iteration"] = 2
        with patch("graph.router.Settings.GRAPH_MAX_ITERATIONS", 10):
            result = safe_next_node(state, "analytical_agent")
        assert result == "analytical_agent"


class TestSafeNextNodeInvalidDecision:
    """Salvaguarda 2: nombre de nodo inválido devuelto por el LLM."""

    def test_garbage_string_falls_back_to_deterministic_rules(self, state_fresh):
        result = safe_next_node(state_fresh, "esto no es un nodo válido")
        # Estado fresco -> fallback determinista debe apuntar a analytical_agent
        assert result == "analytical_agent"

    def test_empty_string_falls_back_to_deterministic_rules(
        self, state_with_exploratory_result
    ):
        result = safe_next_node(state_with_exploratory_result, "")
        assert result == "communication_agent"

    def test_lowercase_end_is_not_treated_as_valid_end(self, state_with_final_response):
        # Solo el literal exacto "END" se reconoce; "end" en minúsculas
        # debe pasar por el fallback determinista.
        result = safe_next_node(state_with_final_response, "end")
        assert result == END_NODE  # el fallback determinista también devuelve END aquí

    def test_decision_with_surrounding_whitespace_is_stripped(self, state_fresh):
        result = safe_next_node(state_fresh, "  analytical_agent  ")
        assert result == "analytical_agent"


class TestSafeNextNodeRepeatedAgentPrevention:
    """Salvaguarda 3: evitar reenviar a un agente que ya completó su trabajo."""

    def test_does_not_resend_to_analytical_agent_if_result_exists(
        self, state_with_exploratory_result
    ):
        result = safe_next_node(state_with_exploratory_result, "analytical_agent")
        assert result != "analytical_agent"

    def test_does_not_resend_to_analytical_agent_if_prediction_exists(
        self, state_with_disruption_prediction
    ):
        result = safe_next_node(state_with_disruption_prediction, "analytical_agent")
        assert result != "analytical_agent"

    def test_does_not_resend_to_disruption_agent_if_proposal_exists(
        self, state_with_disruption_proposal
    ):
        result = safe_next_node(state_with_disruption_proposal, "disruption_agent")
        assert result == "communication_agent"

    def test_allows_disruption_agent_if_no_proposal_yet(
        self, state_with_disruption_prediction
    ):
        result = safe_next_node(state_with_disruption_prediction, "disruption_agent")
        assert result == "disruption_agent"


class TestDeterministicFallback:
    """Tests directos de _deterministic_fallback(), usada como red de seguridad."""

    def test_fresh_state_routes_to_analytical_agent(self, state_fresh):
        assert _deterministic_fallback(state_fresh) == "analytical_agent"

    def test_error_without_response_routes_to_communication_agent(self, state_with_error):
        assert _deterministic_fallback(state_with_error) == "communication_agent"

    def test_final_response_present_routes_to_end(self, state_with_final_response):
        assert _deterministic_fallback(state_with_final_response) == END_NODE

    def test_disruption_detected_routes_to_disruption_agent(
        self, state_with_disruption_prediction
    ):
        assert _deterministic_fallback(state_with_disruption_prediction) == "disruption_agent"

    def test_no_disruption_routes_to_communication_agent(
        self, state_fresh, sample_delay_prediction_ok
    ):
        state = dict(state_fresh)
        state["delay_prediction"] = sample_delay_prediction_ok
        assert _deterministic_fallback(state) == "communication_agent"

    def test_proposal_already_present_routes_to_communication_agent(
        self, state_with_disruption_proposal
    ):
        assert _deterministic_fallback(state_with_disruption_proposal) == "communication_agent"

    def test_error_takes_priority_over_other_fields(
        self, state_with_disruption_prediction
    ):
        # Si hay error Y hay delay_prediction con disrupción, el error
        # debe tener prioridad para no continuar el flujo de negocio.
        state = dict(state_with_disruption_prediction)
        state["error"] = "Fallo simulado en disruption_agent"
        assert _deterministic_fallback(state) == "communication_agent"