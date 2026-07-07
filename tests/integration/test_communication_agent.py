"""
tests/integration/test_communication_agent.py
==================================================
Tests de integración del agente de comunicación CON EL LLM MOCKEADO.

Ya no hay bucle de tool-calling: una única llamada `with_structured_output`
produce `final_response` y `draft_notifications`. El agente nunca
invoca `send_passenger_notification` por sí mismo (eso ahora es una
ruta de la API, ver tests/integration/test_api_routes.py) — por eso
estos tests no necesitan aislar ningún fichero de log.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

from agents.communication_agent import CommunicationOutput, communication_agent
from graph.state import DisruptionProposal, SGIDAState


def _copy_state(state: dict) -> SGIDAState:
    """Copia con el tipo correcto para el comprobador estático (ver test_analytical_agent.py)."""
    return cast(SGIDAState, dict(state))


def _mock_structured_llm(mock_get_llm, output: CommunicationOutput) -> MagicMock:
    structured_llm = MagicMock()
    structured_llm.invoke.return_value = output
    base_llm = MagicMock()
    base_llm.with_structured_output.return_value = structured_llm
    mock_get_llm.return_value = base_llm
    return base_llm


class TestCommunicationAgentTextOnlyResponses:
    """Integración: respuestas sin necesidad de borradores de notificación."""

    @patch("agents.communication_agent.get_llm")
    def test_exploratory_result_produces_final_response_text(
        self, mock_get_llm, state_with_exploratory_result
    ):
        _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="Chicago es el aeropuerto con mayor retraso medio histórico.",
            draft_notifications=[],
        ))

        result = communication_agent(_copy_state(state_with_exploratory_result))

        assert result["final_response"] == "Chicago es el aeropuerto con mayor retraso medio histórico."
        assert result["draft_notifications"] == []
        assert "messages" in result

    @patch("agents.communication_agent.get_llm")
    def test_only_one_llm_call_is_made(self, mock_get_llm, state_with_exploratory_result):
        base_llm = _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="Resumen exploratorio.", draft_notifications=[],
        ))

        communication_agent(_copy_state(state_with_exploratory_result))

        assert base_llm.with_structured_output.call_count == 1
        assert base_llm.bind_tools.called is False


class TestCommunicationAgentDraftNotifications:
    """Integración: reglas de generación de borradores de notificación."""

    @patch("agents.communication_agent.get_llm")
    def test_no_disruption_proposal_means_no_drafts(self, mock_get_llm, state_with_exploratory_result):
        _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="Sin disrupciones detectadas.", draft_notifications=[],
        ))

        result = communication_agent(_copy_state(state_with_exploratory_result))

        assert result["draft_notifications"] == []

    @patch("agents.communication_agent.get_llm")
    def test_low_severity_produces_only_operator_draft(
        self, mock_get_llm, state_with_disruption_proposal
    ):
        state = _copy_state(state_with_disruption_proposal)
        proposal = cast(DisruptionProposal, dict(state["disruption_proposal"]))
        proposal["severity"] = "low"
        state["disruption_proposal"] = proposal

        _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="Retraso leve detectado.",
            draft_notifications=[
                {"recipient_type": "operator", "channel": "operator_dashboard",
                 "message": "Retraso leve, sin acción urgente.", "flight_reference": "UA890"},
            ],
        ))

        result = communication_agent(state)

        recipients = {draft["recipient_type"] for draft in result["draft_notifications"]}
        assert recipients == {"operator"}

    @patch("agents.communication_agent.get_llm")
    def test_high_severity_produces_operator_and_passenger_drafts(
        self, mock_get_llm, state_with_disruption_proposal
    ):
        _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="Disrupción de severidad alta detectada.",
            draft_notifications=[
                {"recipient_type": "operator", "channel": "operator_dashboard",
                 "message": "Severidad alta; reasignar pasajeros a UA890.", "flight_reference": "UA890"},
                {"recipient_type": "passenger", "channel": "email",
                 "message": "Su vuelo sufre un retraso; le hemos reasignado a UA890.", "flight_reference": "UA890"},
            ],
        ))

        result = communication_agent(_copy_state(state_with_disruption_proposal))

        recipients = {draft["recipient_type"] for draft in result["draft_notifications"]}
        assert recipients == {"operator", "passenger"}

    @patch("agents.communication_agent.get_llm")
    def test_drafts_are_not_sent_only_returned_as_data(
        self, mock_get_llm, state_with_disruption_proposal
    ):
        # No debe existir ninguna interacción con tools de envío: el
        # agente solo devuelve los borradores como datos.
        _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="Disrupción detectada.",
            draft_notifications=[
                {"recipient_type": "operator", "channel": "operator_dashboard",
                 "message": "Borrador.", "flight_reference": ""},
            ],
        ))

        result = communication_agent(_copy_state(state_with_disruption_proposal))

        assert isinstance(result["draft_notifications"], list)
        assert isinstance(result["draft_notifications"][0], dict)


class TestCommunicationAgentDegradedMode:
    """Modo degradado: Ollama no disponible y sin resultados previos."""

    @patch("agents.communication_agent.Settings.ollama_available", return_value=False)
    def test_degraded_mode_without_prior_results(self, mock_ollama_available, state_fresh):
        with patch("agents.communication_agent.get_llm") as mock_get_llm:
            result = communication_agent(_copy_state(state_fresh))
            mock_get_llm.assert_not_called()

        assert result["draft_notifications"] == []
        assert "Ollama no está disponible" in result["final_response"]


class TestCommunicationAgentErrorHandling:
    """Integración: comportamiento ante errores previos o fallos del LLM."""

    @patch("agents.communication_agent.get_llm")
    def test_state_with_error_produces_user_friendly_message(
        self, mock_get_llm, state_with_error
    ):
        _mock_structured_llm(mock_get_llm, CommunicationOutput(
            final_response="No se ha podido completar tu solicitud debido a un problema técnico.",
            draft_notifications=[],
        ))

        result = communication_agent(_copy_state(state_with_error))

        assert result["final_response"]
        # No debe filtrar detalles internos como nombres de excepción de Python.
        assert "Exception" not in result["final_response"]
        assert "Traceback" not in result["final_response"]

    @patch("agents.communication_agent.get_llm")
    def test_llm_exception_falls_back_to_generic_message_not_crash(
        self, mock_get_llm, state_with_exploratory_result
    ):
        mock_get_llm.side_effect = RuntimeError("Ollama no responde")

        # No debe lanzar excepción: communication_agent siempre debe
        # devolver un final_response, incluso ante fallo total del LLM.
        result = communication_agent(_copy_state(state_with_exploratory_result))

        assert result["final_response"]
        assert isinstance(result["final_response"], str)
        assert result["draft_notifications"] == []

    def test_empty_state_does_not_crash_context_builder(self, state_fresh):
        # No debe lanzar excepción solo por construir el bloque de contexto,
        # incluso si no hay ningún resultado de agentes previos.
        from agents.communication_agent import _build_context_block

        context = _build_context_block(_copy_state(state_fresh))
        assert isinstance(context, str)
        assert "Consulta original" in context
