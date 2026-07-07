"""
agents/communication_agent.py
================================
Agente de Comunicación de SGIDA.

Responsabilidad: traducir los resultados de los agentes analítico y de
disrupciones (ya presentes en el estado) a una respuesta en lenguaje
natural para el operador (`final_response`), y redactar borradores de
notificación para operador y/o pasajeros afectados (`draft_notifications`)
cuando corresponda. Los borradores NUNCA se envían automáticamente —
el envío (simulado) es una acción explícita del operador desde el
frontend, no una decisión del LLM.

Diseño (decisión documentada en la memoria del TFG):
-------------------------------------------------------------------
Redactar texto no requiere ninguna tool, así que ya no hay bucle de
tool-calling: una única llamada `with_structured_output` produce tanto
`final_response` como `draft_notifications` a partir del mismo bloque
de contexto JSON. Mismo espíritu de simplificación ya aplicado a
`analytical_agent` y `disruption_agent` (menos llamadas LLM = más
rápido y fiable).
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from config.settings import Settings, get_llm
from graph.state import SGIDAState
from prompts.communication_prompt import COMMUNICATION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Esquema de salida estructurada (única llamada LLM)
# ---------------------------------------------------------------------------

class NotificationDraftModel(BaseModel):
    """Borrador de notificación — ver graph.state.NotificationDraft."""

    recipient_type: str = Field(description='"operator" | "passenger" | "ground_staff"')
    channel: str = Field(description='"email" | "sms" | "push" | "operator_dashboard"')
    message: str = Field(description="Texto completo del borrador, ya redactado.")
    flight_reference: str = Field(default="", description="Identificador del vuelo, si aplica.")


class CommunicationOutput(BaseModel):
    """Salida estructurada del agente de comunicación."""

    final_response: str = Field(description="Texto final en lenguaje natural para el operador.")
    draft_notifications: list[NotificationDraftModel] = Field(
        default_factory=list,
        description="Borradores de notificación (operador y/o pasajero). Vacío si no aplica.",
    )


# ---------------------------------------------------------------------------
# Construcción del contexto a partir del estado
# ---------------------------------------------------------------------------

def _build_context_block(state: SGIDAState) -> str:
    """Construye el bloque de contexto textual a partir de los campos del estado."""
    lines = [f"Consulta original del operador: {state['user_query']}"]

    if state.get("error"):
        lines.append(f"Error reportado por un agente previo: {state['error']}")
    if state.get("analytics_result"):
        lines.append(f"analytics_result (JSON): {json.dumps(state['analytics_result'], ensure_ascii=False)}")
    if state.get("delay_prediction"):
        lines.append(f"delay_prediction (JSON): {json.dumps(state['delay_prediction'], ensure_ascii=False)}")
    if state.get("disruption_proposal"):
        lines.append(f"disruption_proposal (JSON): {json.dumps(state['disruption_proposal'], ensure_ascii=False)}")

    if len(lines) == 1:
        lines.append(
            "No hay resultados de agentes previos disponibles; informa al "
            "operador de que no se generó información suficiente."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nodo del grafo
# ---------------------------------------------------------------------------

def communication_agent(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del agente de comunicación.

    Lee los resultados disponibles en el estado (analytics_result,
    delay_prediction, disruption_proposal, error) y hace una única
    llamada LLM que produce `final_response` y `draft_notifications`.

    A diferencia de los otros agentes, un fallo aquí no debe dejar al
    operador sin respuesta: si algo falla, se devuelve un mensaje de
    fallback genérico en lugar de propagar el error sin texto visible.
    """
    if not Settings.ollama_available() and not any(
        [
            state.get("analytics_result"),
            state.get("delay_prediction"),
            state.get("disruption_proposal"),
            state.get("error"),
        ]
    ):
        final_text = "Sistema en modo degradado: Ollama no está disponible. Revisa la configuración del modelo local o copia .env.example a .env antes de lanzar consultas complejas."
        return {
            "final_response": final_text,
            "draft_notifications": [],
            "messages": [AIMessage(content=final_text)],
        }

    final_text: str | None = None
    draft_notifications: list[dict] = []

    try:
        structured_llm = get_llm().with_structured_output(CommunicationOutput)

        result = structured_llm.invoke([
            SystemMessage(content=COMMUNICATION_SYSTEM_PROMPT),
            HumanMessage(content=_build_context_block(state)),
        ])

        if not isinstance(result, CommunicationOutput):
            model_dump_fn = getattr(result, "model_dump", None)
            result = model_dump_fn() if callable(model_dump_fn) else dict(result)
            result = CommunicationOutput.model_validate(result)

        final_text = result.final_response
        draft_notifications = [draft.model_dump() for draft in result.draft_notifications]

    except Exception as exc:  # noqa: BLE001
        if Settings.DEBUG_MODE:
            print(f"[communication_agent] Error: {exc}")
        final_text = (
            "No se ha podido generar una respuesta completa debido a un "
            "problema interno. Por favor, reformula tu consulta o inténtalo "
            "de nuevo en unos momentos."
        )
        draft_notifications = []

    return {
        "final_response": final_text,
        "draft_notifications": draft_notifications,
        "messages": [AIMessage(content=final_text)],
    }
