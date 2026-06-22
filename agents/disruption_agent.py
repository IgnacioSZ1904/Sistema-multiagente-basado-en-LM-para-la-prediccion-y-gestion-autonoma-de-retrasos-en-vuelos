"""
agents/disruption_agent.py
=============================
Agente de Gestión de Disrupciones de SGIDA.

Responsabilidad: una vez que el Agente Analítico ha detectado o
predicho una disrupción (state["delay_prediction"]["is_disruption"]
es True), este agente razona sobre las opciones disponibles y propone
una actuación concreta: reasignación de pasajeros a vuelos alternativos
y/o priorización de recursos en tierra.

Mismo patrón de dos fases que analytical_agent.py (ver docstring de
ese módulo para la justificación de diseño): bucle ReAct manual sobre
herramientas de solo lectura, seguido de una síntesis estructurada
independiente con `with_structured_output`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from config.settings import Settings, get_llm
from graph.state import DisruptionProposal, SGIDAState
from prompts.disruption_prompt import (
    DISRUPTION_REACT_SYSTEM_PROMPT,
    DISRUPTION_STRUCTURED_SYSTEM_PROMPT,
)
from tools.disruption_tools import DISRUPTION_TOOLS

_MAX_TOOL_CALLS = 4

_TOOLS_BY_NAME = {t.name: t for t in DISRUPTION_TOOLS}


# ---------------------------------------------------------------------------
# Esquema de salida estructurada (Fase 2)
# ---------------------------------------------------------------------------

class DisruptionOutput(BaseModel):
    """Salida estructurada del agente de disrupciones."""

    severity: str = Field(
        description='Severidad de la disrupción: "low" | "medium" | '
        '"high" | "critical".'
    )
    actions: list[str] = Field(
        description="Lista de 2 a 5 acciones concretas y accionables propuestas."
    )
    affected_passengers_est: int = Field(
        description="Estimación de pasajeros afectados (0 si no se pudo estimar)."
    )
    alternative_flights: list[str] = Field(
        default_factory=list,
        description="Hasta 3 identificadores de vuelos alternativos "
        '(formato libre, ej. "DL456 - 14:20"). Vacío si no hay candidatos.',
    )
    reasoning: str = Field(
        description="Razonamiento breve (2-4 frases) que justifica la "
        "propuesta con datos concretos observados."
    )


# ---------------------------------------------------------------------------
# Fase 1 — Bucle ReAct manual
# ---------------------------------------------------------------------------

def _run_react_loop(user_query: str, flight_context: Any, delay_prediction: Any = None) -> list:
    """
    Ejecuta el bucle ReAct manual sobre las herramientas de disrupción.
    Ver analytical_agent._run_react_loop para la justificación del patrón.
    """
    llm_with_tools = get_llm().bind_tools(DISRUPTION_TOOLS)

    context_lines = [f"Consulta original del operador: {user_query}"]
    if flight_context:
        context_lines.append(f"Contexto del vuelo: {flight_context}")
    if delay_prediction:
        context_lines.append(f"Predicción del Agente Analítico: {delay_prediction}")

    messages: list = [
        SystemMessage(content=DISRUPTION_REACT_SYSTEM_PROMPT),
        HumanMessage(content="\n".join(context_lines)),
    ]

    for _ in range(_MAX_TOOL_CALLS):
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
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
    else:
        if Settings.DEBUG_MODE:
            print(
                f"[disruption_agent] Límite de {_MAX_TOOL_CALLS} llamadas "
                "a herramientas alcanzado; forzando síntesis con lo disponible."
            )

    return messages


# ---------------------------------------------------------------------------
# Fase 2 — Síntesis estructurada
# ---------------------------------------------------------------------------

def _synthesize(messages: list, delay_prediction: Any = None) -> DisruptionOutput:
    """Sintetiza las observaciones de la fase ReAct en una propuesta estructurada."""
    structured_llm = get_llm().with_structured_output(DisruptionOutput)

    observations = [f"- {msg.content}" for msg in messages if isinstance(msg, ToolMessage)]
    observations_text = (
        "\n".join(observations) if observations
        else "No se obtuvieron resultados de ninguna herramienta de disrupción."
    )

    synthesis_prompt = (
        f"Predicción del Agente Analítico: {delay_prediction or 'no disponible'}\n\n"
        f"Resultados obtenidos de las herramientas de disrupción consultadas:\n"
        f"{observations_text}\n\n"
        "Sintetiza una propuesta de actuación estructurada."
    )

    result = structured_llm.invoke([
        SystemMessage(content=DISRUPTION_STRUCTURED_SYSTEM_PROMPT),
        HumanMessage(content=synthesis_prompt),
    ])

    if isinstance(result, DisruptionOutput):
        return result

    model_dump_fn = getattr(result, "model_dump", None)
    if callable(model_dump_fn):
        result = model_dump_fn()
    elif not isinstance(result, dict):
        result = dict(result)

    return DisruptionOutput.model_validate(result)


# ---------------------------------------------------------------------------
# Nodo del grafo
# ---------------------------------------------------------------------------

def disruption_agent(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del agente de gestión de disrupciones.

    Lee `delay_prediction` y `flight_context` del estado, ejecuta el
    bucle ReAct sobre las herramientas de disrupción, sintetiza una
    propuesta de actuación y devuelve la actualización para
    `disruption_proposal`.

    En caso de error, escribe en `error` en lugar de lanzar excepción.
    """
    try:
        messages = _run_react_loop(
            user_query=state["user_query"],
            flight_context=state.get("flight_context"),
            delay_prediction=state.get("delay_prediction"),
        )
        output = _synthesize(messages, state.get("delay_prediction"))

    except Exception as exc:  # noqa: BLE001
        return {"error": f"Error en disruption_agent: {exc}"}

    proposal = DisruptionProposal(
        proposal_id=f"PROP-{uuid.uuid4().hex[:8]}",
        severity=output.severity,
        actions=output.actions,
        affected_passengers_est=output.affected_passengers_est,
        alternative_flights=output.alternative_flights,
        reasoning=output.reasoning,
    )

    return {
        "disruption_proposal": proposal,
        "messages": [AIMessage(content=output.reasoning)],
    }