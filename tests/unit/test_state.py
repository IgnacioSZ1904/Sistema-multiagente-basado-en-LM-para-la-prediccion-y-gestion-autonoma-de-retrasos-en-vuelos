"""
tests/unit/test_state.py
===========================
Tests de funcionalidades básicas de graph/state.py.

Cubren la construcción del estado inicial y la coherencia de los tipos
TypedDict definidos, sin dependencias externas (sin LLM, sin DB).
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from graph.state import (
    AnalyticsResult,
    DelayPrediction,
    DisruptionProposal,
    FlightContext,
    SGIDAState,
    initial_state,
)


class TestInitialState:
    """Tests de la factoría initial_state()."""

    def test_initial_state_sets_user_query(self):
        state = initial_state("¿Qué aeropuertos tienen más retrasos?")
        assert state["user_query"] == "¿Qué aeropuertos tienen más retrasos?"

    def test_initial_state_starts_with_supervisor_as_next_agent(self):
        state = initial_state("consulta de prueba")
        assert state["next_agent"] == "supervisor"

    def test_initial_state_iteration_starts_at_zero(self):
        state = initial_state("consulta de prueba")
        assert state["iteration"] == 0

    def test_initial_state_optional_fields_are_none(self):
        state = initial_state("consulta de prueba")
        assert state["flight_context"] is None
        assert state["analytics_result"] is None
        assert state["delay_prediction"] is None
        assert state["disruption_proposal"] is None
        assert state["final_response"] is None
        assert state["error"] is None

    def test_initial_state_messages_is_empty_list(self):
        state = initial_state("consulta de prueba")
        assert state["messages"] == []

    def test_initial_state_contains_all_required_keys(self):
        state = initial_state("consulta de prueba")
        expected_keys = {
            "messages", "user_query", "flight_context", "next_agent",
            "iteration", "analytics_result", "delay_prediction",
            "disruption_proposal", "final_response", "error",
        }
        assert expected_keys.issubset(state.keys())

    def test_initial_state_with_empty_query_string(self):
        # No debe lanzar excepción aunque la consulta esté vacía;
        # la validación de "consulta no vacía" es responsabilidad de main.py.
        state = initial_state("")
        assert state["user_query"] == ""


class TestFlightContext:
    """Tests de construcción del TypedDict FlightContext."""

    def test_flight_context_accepts_partial_data(self):
        # total=False permite construir con solo algunos campos.
        ctx = FlightContext(airline="AA", origin="Chicago, IL")
        assert ctx["airline"] == "AA"
        assert ctx["origin"] == "Chicago, IL"

    def test_flight_context_accepts_full_data(self):
        ctx = FlightContext(
            airline="DL",
            origin="New York, NY",
            destination="Los Angeles, CA",
            flight_date="2018-06-01",
            year=2018,
            month=6,
            day=1,
            scheduled_dep=830,
            scheduled_arr=1145,
            distance=2475.0,
        )
        assert ctx["scheduled_dep"] == 830
        assert ctx["distance"] == 2475.0


class TestDelayPrediction:
    """Tests de construcción del TypedDict DelayPrediction."""

    def test_delay_prediction_requires_all_fields(self):
        # DelayPrediction es total=True (por defecto): todos los campos
        # son obligatorios al construirlo explícitamente.
        prediction = DelayPrediction(
            expected_dep_delay_min=10.0,
            expected_arr_delay_min=8.0,
            is_disruption=False,
            confidence=0.85,
            main_cause="unknown",
        )
        assert prediction["is_disruption"] is False
        assert prediction["main_cause"] == "unknown"

    def test_delay_prediction_disruption_flag_is_boolean(self):
        prediction = DelayPrediction(
            expected_dep_delay_min=60.0,
            expected_arr_delay_min=65.0,
            is_disruption=True,
            confidence=0.7,
            main_cause="weather",
        )
        assert isinstance(prediction["is_disruption"], bool)


class TestDisruptionProposal:
    """Tests de construcción del TypedDict DisruptionProposal."""

    def test_disruption_proposal_actions_is_list(self):
        proposal = DisruptionProposal(
            proposal_id="PROP-abc123",
            severity="medium",
            actions=["Acción 1", "Acción 2"],
            affected_passengers_est=80,
            alternative_flights=[],
            reasoning="Razonamiento de prueba.",
        )
        assert isinstance(proposal["actions"], list)
        assert len(proposal["actions"]) == 2

    def test_disruption_proposal_allows_empty_alternatives(self):
        proposal = DisruptionProposal(
            proposal_id="PROP-abc124",
            severity="critical",
            actions=["Notificar a todos los pasajeros"],
            affected_passengers_est=200,
            alternative_flights=[],
            reasoning="No hay vuelos alternativos fiables disponibles.",
        )
        assert proposal["alternative_flights"] == []


class TestAnalyticsResult:
    """Tests de construcción del TypedDict AnalyticsResult (total=False)."""

    def test_analytics_result_accepts_partial_fields(self):
        result = AnalyticsResult(delay_causes_pct={"weather": 20.0})
        assert result["delay_causes_pct"]["weather"] == 20.0

    def test_analytics_result_accepts_empty_construction(self):
        # total=False permite incluso un diccionario vacío.
        result = AnalyticsResult()
        assert result == {}


class TestSGIDAStateTypeStructure:
    """Tests de que el estado es compatible con lo que espera LangGraph."""

    def test_messages_field_accepts_base_message_list(self, state_fresh):
        assert isinstance(state_fresh["messages"], list)
        # No debe contener nada que no sea BaseMessage si se le añaden mensajes.
        for msg in state_fresh["messages"]:
            assert isinstance(msg, BaseMessage)

    def test_state_is_plain_dict_at_runtime(self, state_fresh):
        # TypedDict no crea una clase real en tiempo de ejecución;
        # debe comportarse como un dict normal para que LangGraph pueda
        # hacer merge de actualizaciones parciales sin problemas.
        assert isinstance(state_fresh, dict)