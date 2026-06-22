"""
agents/analytical_agent.py
============================
Agente Analítico de SGIDA.

Responsabilidad: procesar el histórico de vuelos para identificar
patrones de retraso (modo exploratorio) o predecir el retraso esperado
de un vuelo concreto y su riesgo de efecto cascada (modo predictivo).

Diseño en dos fases (decisión documentada en la memoria del TFG):
-------------------------------------------------------------------
Con Ollama como backend local, combinar `bind_tools()` (tool-calling)
y `with_structured_output()` (salida Pydantic) en una sola llamada es
poco fiable: el modelo tiende a confundir el esquema de la herramienta
con el esquema de salida. Por ello se separan en dos llamadas:

  FASE 1 (ReAct manual): el LLM con herramientas vinculadas decide qué
          consultas ejecutar contra DuckDB, en un bucle controlado por
          este código (no por un prebuilt de LangGraph), hasta que deja
          de solicitar herramientas o se alcanza el máximo de iteraciones.

  FASE 2 (síntesis estructurada): con el LLM SIN herramientas vinculadas
          pero con `with_structured_output(AnalyticalOutput)`, se sintetiza
          todo lo observado en la Fase 1 en un objeto Pydantic validado,
          que se traduce a los campos del SGIDAState.
"""

from __future__ import annotations

from typing import Optional, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from config.settings import Settings, get_llm
from graph.state import AnalyticsResult, DelayPrediction, SGIDAState
from prompts.analytical_prompt import (
    ANALYTICAL_REACT_SYSTEM_PROMPT,
    ANALYTICAL_STRUCTURED_SYSTEM_PROMPT,
)
from tools.analytical_tools import ANALYTICAL_TOOLS

# Máximo de llamadas a herramientas dentro de la fase ReAct de este agente.
# Distinto de Settings.GRAPH_MAX_ITERATIONS, que limita el grafo completo.
_MAX_TOOL_CALLS = 5

_TOOLS_BY_NAME = {t.name: t for t in ANALYTICAL_TOOLS}


# ---------------------------------------------------------------------------
# Esquema de salida estructurada (Fase 2)
# ---------------------------------------------------------------------------

class AnalyticalOutput(BaseModel):
    """
    Salida estructurada del agente analítico. Se traduce a
    DelayPrediction o AnalyticsResult según `response_mode`.
    """

    response_mode: str = Field(
        description='Modo de respuesta: "prediction" si la consulta era '
        'sobre un vuelo concreto, "exploratory" si era un análisis general.'
    )

    # --- Campos de modo "prediction" (rellenar solo si aplica) ----------
    expected_dep_delay_min: Optional[float] = Field(
        default=None, description="Retraso estimado en salida (minutos)."
    )
    expected_arr_delay_min: Optional[float] = Field(
        default=None, description="Retraso estimado en llegada (minutos)."
    )
    is_disruption: Optional[bool] = Field(
        default=None,
        description="True si el retraso estimado supera el umbral de disrupción.",
    )
    confidence: Optional[float] = Field(
        default=None, description="Confianza de la predicción, entre 0.0 y 1.0."
    )
    main_cause: Optional[str] = Field(
        default=None,
        description='Causa principal: "carrier" | "weather" | "nas" | '
        '"security" | "late_aircraft" | "unknown".',
    )

    # --- Campo de modo "exploratory" -------------------------------------
    exploratory_summary: Optional[dict] = Field(
        default=None,
        description="Resultados clave del análisis exploratorio, "
        "estructurados como un diccionario libre con los hallazgos "
        "más relevantes (p.ej. top_delay_airports, delay_causes_pct...).",
    )

    narrative_summary: str = Field(
        description="Resumen en 2-4 frases de los hallazgos, en lenguaje "
        "natural, para que el agente de comunicación lo use como base."
    )


# ---------------------------------------------------------------------------
# Fase 1 — Bucle ReAct manual
# ---------------------------------------------------------------------------

def _run_react_loop(user_query: str, flight_context: Any | None) -> list:
    """
    Ejecuta el bucle ReAct manual: el LLM decide qué herramientas llamar,
    este código las ejecuta y devuelve los resultados al LLM, hasta que
    el LLM no solicita más herramientas o se alcanza _MAX_TOOL_CALLS.

    Returns
    -------
    list[BaseMessage]
        Historial completo de mensajes generado durante el bucle
        (incluye AIMessages con tool_calls y los ToolMessages de resultado).
    """
    llm_with_tools = get_llm().bind_tools(ANALYTICAL_TOOLS)

    context_line = (
        f"\nContexto del vuelo proporcionado: {flight_context}"
        if flight_context else "\nNo se ha proporcionado un vuelo concreto."
    )

    messages: list = [
        SystemMessage(content=ANALYTICAL_REACT_SYSTEM_PROMPT),
        HumanMessage(content=f"Consulta del operador: {user_query}{context_line}"),
    ]

    for step in range(_MAX_TOOL_CALLS):
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            # El LLM considera que ya tiene suficiente información.
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
        # Se alcanzó _MAX_TOOL_CALLS sin que el LLM se detuviera por sí mismo.
        if Settings.DEBUG_MODE:
            print(
                f"[analytical_agent] Límite de {_MAX_TOOL_CALLS} llamadas "
                "a herramientas alcanzado; forzando síntesis con lo disponible."
            )

    return messages


# ---------------------------------------------------------------------------
# Fase 2 — Síntesis estructurada
# ---------------------------------------------------------------------------

def _synthesize(messages: list, user_query: str) -> AnalyticalOutput:
    """
    Toma el historial de la fase ReAct y produce la salida estructurada
    final, usando el LLM sin herramientas pero con schema Pydantic forzado.
    """
    structured_llm = get_llm().with_structured_output(AnalyticalOutput)

    # Construimos un resumen textual de las observaciones (resultados de
    # herramientas) en lugar de pasar el historial completo de mensajes,
    # para evitar confundir al modelo con tool_calls en esta segunda fase.
    observations = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            observations.append(f"- {msg.content}")

    observations_text = (
        "\n".join(observations) if observations
        else "No se obtuvieron resultados de ninguna herramienta."
    )

    synthesis_prompt = (
        f"Consulta original del operador: {user_query}\n\n"
        f"Resultados obtenidos de las herramientas consultadas:\n"
        f"{observations_text}\n\n"
        f"Umbral de disrupción configurado: {Settings.DELAY_THRESHOLD_MINUTES} minutos.\n\n"
        "Sintetiza estos resultados en la salida estructurada solicitada."
    )

    result = structured_llm.invoke([
        SystemMessage(content=ANALYTICAL_STRUCTURED_SYSTEM_PROMPT),
        HumanMessage(content=synthesis_prompt),
    ])

    return AnalyticalOutput.parse_obj(result)


# ---------------------------------------------------------------------------
# Nodo del grafo
# ---------------------------------------------------------------------------

def analytical_agent(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del agente analítico.

    Lee `user_query` y `flight_context` del estado, ejecuta el bucle
    ReAct sobre las herramientas analíticas, sintetiza el resultado y
    devuelve un diccionario parcial para actualizar el estado con
    `delay_prediction` o `analytics_result`, según corresponda.

    En caso de error, escribe en `error` en lugar de lanzar excepción,
    permitiendo que el supervisor redirija al agente de comunicación.
    """
    try:
        messages = _run_react_loop(
            user_query=state["user_query"],
                flight_context=state.get("flight_context"),
        )
        output = _synthesize(messages, state["user_query"])

    except Exception as exc:  # noqa: BLE001
        return {"error": f"Error en analytical_agent: {exc}"}

    update: dict = {}

    if output.response_mode == "prediction":
        update["delay_prediction"] = DelayPrediction(
            expected_dep_delay_min=output.expected_dep_delay_min or 0.0,
            expected_arr_delay_min=output.expected_arr_delay_min or 0.0,
            is_disruption=bool(output.is_disruption),
            confidence=output.confidence or 0.0,
            main_cause=output.main_cause or "unknown",
        )
    else:
        update["analytics_result"] = AnalyticsResult(
            summary_stats=output.exploratory_summary or {},
        )

    # El resumen narrativo se añade al canal de mensajes para que el
    # agente de comunicación (y el operador, en modo debug) tenga
    # visibilidad del razonamiento intermedio.
    update["messages"] = [AIMessage(content=output.narrative_summary)]

    return update