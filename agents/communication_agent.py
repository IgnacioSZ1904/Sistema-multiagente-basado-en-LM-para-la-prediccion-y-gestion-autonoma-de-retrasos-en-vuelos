"""
agents/communication_agent.py
================================
Agente de Comunicación de SGIDA.

Responsabilidad: traducir los resultados de los agentes analítico y de
disrupciones (ya presentes en el estado) a una respuesta en lenguaje
natural para el operador, y registrar notificaciones simuladas cuando
la severidad de una disrupción lo justifique.

Patrón distinto a los otros dos agentes (ver docstring de
prompts/communication_prompt.py): no hay fase de exploración de datos
propia, así que se usa un único bucle ReAct acotado (máximo 1-2 llamadas
a `send_passenger_notification`) sin fase de síntesis estructurada
posterior — la salida estructurada AQUÍ es simplemente el texto final,
que no necesita Pydantic porque `final_response` es un str.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from config.settings import Settings, get_llm
from graph.state import SGIDAState
from prompts.communication_prompt import COMMUNICATION_SYSTEM_PROMPT
from tools.communication_tools import COMMUNICATION_TOOLS

_MAX_TOOL_CALLS = 2

_TOOLS_BY_NAME = {t.name: t for t in COMMUNICATION_TOOLS}


# ---------------------------------------------------------------------------
# Construcción del contexto a partir del estado
# ---------------------------------------------------------------------------

def _build_context_block(state: SGIDAState) -> str:
    """Construye el bloque de contexto textual a partir de los campos del estado."""
    lines = [f"Consulta original del operador: {state['user_query']}"]

    if state.get("error"):
        lines.append(f"Error reportado por un agente previo: {state['error']}")
    if state.get("analytics_result"):
        lines.append(f"Resultado analítico exploratorio: {state['analytics_result']}")
    if state.get("delay_prediction"):
        lines.append(f"Predicción de retraso: {state['delay_prediction']}")
    if state.get("disruption_proposal"):
        lines.append(f"Propuesta de disrupción: {state['disruption_proposal']}")

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
    delay_prediction, disruption_proposal, error) y genera una respuesta
    final en lenguaje natural. Si la propuesta de disrupción es de
    severidad alta o crítica, registra una notificación simulada antes
    de devolver la respuesta.

    A diferencia de los otros agentes, un fallo aquí no debe dejar al
    operador sin respuesta: si algo falla, se devuelve un mensaje de
    fallback genérico en lugar de propagar el error sin texto visible.
    """
    messages: list = [
        SystemMessage(content=COMMUNICATION_SYSTEM_PROMPT),
        HumanMessage(content=_build_context_block(state)),
    ]

    final_text: str | None = None

    try:
        llm_with_tools = get_llm().bind_tools(COMMUNICATION_TOOLS)

        for _ in range(_MAX_TOOL_CALLS):
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                final_text = response.content if isinstance(response.content, str) else str(response.content)
                break

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_fn = _TOOLS_BY_NAME.get(tool_name)

                if tool_fn is None:
                    result_content = f"Error: herramienta '{tool_name}' no existe."
                else:
                    try:
                        result_content = tool_fn.invoke(tool_args)
                    except Exception as exc:  # noqa: BLE001
                        result_content = f"Error ejecutando '{tool_name}': {exc}"

                messages.append(
                    ToolMessage(content=str(result_content), tool_call_id=tool_call["id"])
                )

        if final_text is None:
            # Se agotaron los intentos sin respuesta final en texto: forzamos
            # una última llamada sin herramientas para garantizar una respuesta.
            plain_llm = get_llm()
            forced = plain_llm.invoke(messages + [
                HumanMessage(content="Responde ahora con el texto final para el operador, sin usar más herramientas.")
            ])
            final_text = forced.content if isinstance(forced.content, str) else str(forced.content)

    except Exception as exc:  # noqa: BLE001
        if Settings.DEBUG_MODE:
            print(f"[communication_agent] Error: {exc}")
        final_text = (
            "No se ha podido generar una respuesta completa debido a un "
            "problema interno. Por favor, reformula tu consulta o inténtalo "
            "de nuevo en unos momentos."
        )

    return {
        "final_response": final_text,
        "messages": [AIMessage(content=final_text)],
    }