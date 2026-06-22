"""
tests/integration/test_communication_agent.py
==================================================
Tests de integración del agente de comunicación CON EL LLM MOCKEADO.

A diferencia de los otros dos agentes, communication_agent no tiene
fase de síntesis estructurada separada (su salida es texto plano), así
que solo se mockea bind_tools(...).invoke(...) y, en el caso del
fallback, una llamada adicional sin tools.

No requiere analytical_db.duckdb (usa el log de notificaciones propio
en un directorio temporal aislado), así que NO se marca con requires_db.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agents.communication_agent import communication_agent
from graph.state import DisruptionProposal, SGIDAState


def _copy_state(state: dict) -> SGIDAState:
    """Copia con el tipo correcto para el comprobador estático (ver test_analytical_agent.py)."""
    return cast(SGIDAState, dict(state))


def _make_ai_message_with_tool_call(tool_name: str, tool_args: dict, call_id: str = "call_1"):
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": tool_name, "args": tool_args, "id": call_id}]
    return msg


def _make_ai_message_no_tool_call(content: str):
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


@pytest.fixture(autouse=True)
def _isolated_log_file(tmp_path, monkeypatch):
    """Redirige el log de notificaciones a un fichero temporal por test."""
    import tools.communication_tools as mod

    temp_log_dir = tmp_path / "notifications_log"
    temp_log_file = temp_log_dir / "notifications.jsonl"

    monkeypatch.setattr(mod, "_LOG_DIR", temp_log_dir)
    monkeypatch.setattr(mod, "_LOG_FILE", temp_log_file)
    yield temp_log_file


class TestCommunicationAgentTextOnlyResponses:
    """Integración: respuestas sin necesidad de notificar."""

    @patch("agents.communication_agent.get_llm")
    def test_exploratory_result_produces_final_response_text(
        self, mock_get_llm, state_with_exploratory_result
    ):
        llm_with_tools = MagicMock()
        llm_with_tools.invoke.return_value = _make_ai_message_no_tool_call(
            "Chicago es el aeropuerto con mayor retraso medio histórico."
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = llm_with_tools
        mock_get_llm.return_value = base_llm

        result = communication_agent(_copy_state(state_with_exploratory_result))

        assert result["final_response"] == "Chicago es el aeropuerto con mayor retraso medio histórico."
        assert "messages" in result

    @patch("agents.communication_agent.get_llm")
    def test_low_severity_proposal_does_not_trigger_notification(
        self, mock_get_llm, state_with_disruption_proposal, _isolated_log_file
    ):
        # Aunque el fixture trae severity="high", forzamos "low" para este test.
        state = _copy_state(state_with_disruption_proposal)
        original_proposal = cast(DisruptionProposal, state["disruption_proposal"])
        modified_proposal: DisruptionProposal = cast(DisruptionProposal, dict(original_proposal))
        modified_proposal["severity"] = "low"
        state["disruption_proposal"] = modified_proposal

        llm_with_tools = MagicMock()
        llm_with_tools.invoke.return_value = _make_ai_message_no_tool_call(
            "Retraso leve detectado; no se requiere acción inmediata."
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = llm_with_tools
        mock_get_llm.return_value = base_llm

        communication_agent(state)

        assert not _isolated_log_file.exists()


class TestCommunicationAgentNotificationFlow:
    """Integración: severidad alta/crítica debe poder registrar notificación."""

    @patch("agents.communication_agent.get_llm")
    def test_high_severity_proposal_can_trigger_notification_tool(
        self, mock_get_llm, state_with_disruption_proposal, _isolated_log_file
    ):
        llm_with_tools = MagicMock()
        llm_with_tools.invoke.side_effect = [
            _make_ai_message_with_tool_call(
                "send_passenger_notification",
                {
                    "recipient_type": "operator",
                    "message": "Disrupción de severidad alta detectada en vuelo AA.",
                    "flight_reference": "AA - Chicago,IL-Denver,CO",
                },
            ),
            _make_ai_message_no_tool_call(
                "Se ha detectado una disrupción de severidad alta y se ha notificado al operador."
            ),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = llm_with_tools
        mock_get_llm.return_value = base_llm

        result = communication_agent(_copy_state(state_with_disruption_proposal))

        assert _isolated_log_file.exists()
        assert "notificado" in result["final_response"]

    @patch("agents.communication_agent.get_llm")
    def test_notification_tool_call_count_respects_max_tool_calls(
        self, mock_get_llm, state_with_disruption_proposal
    ):
        llm_with_tools = MagicMock()
        # El LLM "insiste" en llamar a la tool indefinidamente.
        llm_with_tools.invoke.return_value = _make_ai_message_with_tool_call(
            "send_passenger_notification",
            {"recipient_type": "operator", "message": "Mensaje repetido."},
        )

        # Tras agotar _MAX_TOOL_CALLS, se hace una llamada adicional sin tools.
        plain_llm = MagicMock()
        plain_llm.invoke.return_value = AIMessage(content="Respuesta forzada final.")

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = llm_with_tools
        mock_get_llm.return_value = base_llm

        # get_llm() se llama dos veces: una para bind_tools, otra para el fallback plano.
        # Configuramos el mock para devolver el mismo base_llm ambas veces,
        # y comprobamos que el propio base_llm (sin bind_tools) se usa de fallback.
        base_llm.invoke = plain_llm.invoke

        result = communication_agent(_copy_state(state_with_disruption_proposal))

        assert llm_with_tools.invoke.call_count == 2  # _MAX_TOOL_CALLS del agente
        assert result["final_response"] == "Respuesta forzada final."


class TestCommunicationAgentErrorHandling:
    """Integración: comportamiento ante errores previos o fallos del LLM."""

    @patch("agents.communication_agent.get_llm")
    def test_state_with_error_produces_user_friendly_message(
        self, mock_get_llm, state_with_error
    ):
        llm_with_tools = MagicMock()
        llm_with_tools.invoke.return_value = _make_ai_message_no_tool_call(
            "No se ha podido completar tu solicitud debido a un problema técnico."
        )

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = llm_with_tools
        mock_get_llm.return_value = base_llm

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

    def test_empty_state_does_not_crash_context_builder(self, state_fresh):
        # No debe lanzar excepción solo por construir el bloque de contexto,
        # incluso si no hay ningún resultado de agentes previos.
        from agents.communication_agent import _build_context_block

        context = _build_context_block(_copy_state(state_fresh))
        assert isinstance(context, str)
        assert "Consulta original" in context