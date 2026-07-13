"""
agents/analytical_agent.py
============================
Agente Analítico de SGIDA.

Responsabilidad: procesar el histórico de vuelos para identificar
patrones de retraso (rutas, aeropuertos, franjas horarias, causas) y,
cuando la consulta trae un vuelo concreto, calcular estadísticas
históricas y una predicción de retraso. La salida es SIEMPRE JSON
estructurado (`AnalyticsResult` / `DelayPrediction`) — este agente
nunca redacta texto en lenguaje natural para el operador; ese JSON es
lo que consumen `disruption_agent` (gestión de la disrupción) y
`communication_agent` (traducción a lenguaje natural).

Diseño en una sola fase con LLM (decisión documentada en la memoria
del TFG):
-------------------------------------------------------------------
Con Ollama como backend local, combinar `bind_tools()` (tool-calling)
y `with_structured_output()` (salida Pydantic) en una sola llamada es
poco fiable. La versión anterior de este agente resolvía esto con dos
llamadas LLM (ReAct + síntesis estructurada). Esa segunda llamada, sin
embargo, era redundante: las tools ya devuelven JSON con el shape
exacto que necesita el estado, así que pedirle al LLM que las
"reescriba" en un schema Pydantic solo añadía latencia y riesgo de que
transcribiera mal los números. Por eso aquí la fase de síntesis se
sustituye por un ENSAMBLAJE DETERMINISTA en código:

  FASE 1 (ReAct manual): el LLM con herramientas vinculadas decide qué
          consultas ejecutar contra DuckDB, en un bucle controlado por
          este código, hasta que deja de solicitar herramientas o se
          alcanza el máximo de turnos.

  FASE 2 (ensamblaje determinista): cada resultado de tool ya es JSON
          válido con el shape del campo de `AnalyticsResult` al que
          corresponde — se mapea `nombre_de_tool -> campo` y se hace
          `json.loads()`, sin ninguna llamada adicional al LLM. Si la
          consulta trajo estadísticas de un vuelo concreto
          (`flight_historical_stats`), se deriva además `delay_prediction`
          con una heurística determinista (umbral de disrupción +
          confianza según tamaño de muestra + causa dominante ya
          calculada por SQL).
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from config.logging_config import get_logger
from config.settings import Settings, get_llm
from graph.state import AnalyticsResult, DelayPrediction, FlightContext, SGIDAState
from prompts.analytical_prompt import ANALYTICAL_REACT_SYSTEM_PROMPT
from tools.analytical_tools import ANALYTICAL_TOOLS

logger = get_logger("analytical_agent")

# Máximo de turnos ReAct (llamadas al LLM) dentro de este agente. Un turno
# puede incluir varias tool_calls en paralelo. Distinto de
# Settings.GRAPH_MAX_ITERATIONS, que limita el grafo completo.
_MAX_REACT_TURNS = 3

_TOOLS_BY_NAME = {t.name: t for t in ANALYTICAL_TOOLS}

# Mapa determinista tool -> campo de AnalyticsResult que rellena.
_TOOL_NAME_TO_FIELD = {
    "get_top_delay_airports": "top_delay_airports",
    "get_top_delay_airlines": "top_delay_airlines",
    "get_top_delay_routes": "top_delay_routes",
    "get_delay_by_month": "delay_by_month",
    "get_delay_by_hour": "delay_by_hour",
    "get_delay_causes_breakdown": "delay_causes_breakdown",
    "get_flight_historical_stats": "flight_historical_stats",
    "get_cascade_risk_context": "cascade_risk_context",
}


# ---------------------------------------------------------------------------
# Fase 1 — Bucle ReAct manual
# ---------------------------------------------------------------------------

def _run_react_loop(user_query: str, flight_context: Any | None) -> list[tuple[str, dict, str]]:
    """
    Ejecuta el bucle ReAct manual: el LLM decide qué herramientas llamar,
    este código las ejecuta, hasta que el LLM no solicita más
    herramientas o se alcanza _MAX_REACT_TURNS.

    Returns
    -------
    list[tuple[str, dict, str]]
        Tripletas (nombre_de_tool, argumentos, resultado_json) de cada
        tool invocada, en el orden de ejecución. Es la entrada del
        ensamblaje determinista de la fase 2 (ver _assemble_analytics_result)
        y de la derivación de `flight_context` (ver _derive_flight_context).
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

    tool_results: list[tuple[str, dict, str]] = []

    for turn in range(_MAX_REACT_TURNS):
        start = time.perf_counter()
        try:
            response: AIMessage = llm_with_tools.invoke(messages)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "Llamada LLM (bind_tools, turno %d/%d) -> ERROR tras %.0f ms: %s",
                turn + 1, _MAX_REACT_TURNS, elapsed_ms, exc,
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Llamada LLM (bind_tools, turno %d/%d) -> OK en %.0f ms",
            turn + 1, _MAX_REACT_TURNS, elapsed_ms,
        )
        messages.append(response)

        if not response.tool_calls:
            # El LLM considera que ya tiene suficiente información.
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_fn = _TOOLS_BY_NAME.get(tool_name)

            tool_start = time.perf_counter()
            if tool_fn is None:
                result_content = f"Error: herramienta '{tool_name}' no existe."
                logger.error("Tool '%s' no existe (args=%s)", tool_name, tool_args)
            else:
                try:
                    result_content = tool_fn.invoke(tool_args)
                    tool_elapsed_ms = (time.perf_counter() - tool_start) * 1000
                    logger.info(
                        "Tool '%s'(%s) -> OK en %.0f ms", tool_name, tool_args, tool_elapsed_ms
                    )
                except Exception as exc:  # noqa: BLE001
                    tool_elapsed_ms = (time.perf_counter() - tool_start) * 1000
                    result_content = f"Error ejecutando '{tool_name}': {exc}"
                    logger.error(
                        "Tool '%s'(%s) -> ERROR tras %.0f ms: %s",
                        tool_name, tool_args, tool_elapsed_ms, exc,
                    )

            tool_results.append((tool_name, tool_args, str(result_content)))
            messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tool_call["id"])
            )
    else:
        # Se alcanzó _MAX_REACT_TURNS sin que el LLM se detuviera por sí mismo.
        logger.warning(
            "Limite de %d turnos ReAct alcanzado; se ensambla el resultado con lo disponible.",
            _MAX_REACT_TURNS,
        )

    return tool_results


# ---------------------------------------------------------------------------
# Fase 2 — Ensamblaje determinista (sin LLM)
# ---------------------------------------------------------------------------

def _assemble_analytics_result(tool_results: list[tuple[str, dict, str]]) -> AnalyticsResult:
    """
    Construye AnalyticsResult a partir de los resultados JSON que ya
    devolvieron las herramientas, sin pasar por el LLM. Cada tool
    devuelve exactamente el shape que espera su campo correspondiente
    (ver _TOOL_NAME_TO_FIELD); si una tool se invocó más de una vez,
    gana la última invocación.
    """
    result: AnalyticsResult = {}
    tools_used: list[str] = []

    for tool_name, _tool_args, content in tool_results:
        tools_used.append(tool_name)
        field = _TOOL_NAME_TO_FIELD.get(tool_name)
        if field is None:
            continue
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        result[field] = parsed  # type: ignore[literal-required]

    result["tools_used"] = tools_used
    return result


def _derive_flight_context(tool_results: list[tuple[str, dict, str]]) -> Optional[FlightContext]:
    """
    Deriva FlightContext de forma determinista a partir de los argumentos
    ya usados para invocar `get_flight_historical_stats` (si se llamó),
    sin ninguna llamada LLM adicional — el LLM ya extrajo esos datos del
    texto de la consulta al decidir qué tool invocar, aquí solo se
    reutilizan. Si se invocó más de una vez, gana la última invocación.
    Devuelve None si no se consultó ningún vuelo concreto.
    """
    derived: Optional[FlightContext] = None

    for tool_name, tool_args, _content in tool_results:
        if tool_name == "get_flight_historical_stats":
            derived = FlightContext(
                airline=tool_args.get("airline", ""),
                origin=tool_args.get("origin", ""),
                destination=tool_args.get("destination", ""),
                month=tool_args.get("month", 0),
                scheduled_dep=tool_args.get("scheduled_dep", 0),
            )

    return derived


def _ensure_cascade_risk_context(analytics_result: AnalyticsResult, flight_context: Any | None) -> None:
    """
    Garantiza que `cascade_risk_context` esté disponible cuando hay un
    vuelo concreto, invocando `get_cascade_risk_context` de forma
    determinista si el LLM no la solicitó por su cuenta durante el
    bucle ReAct. El "impacto sobre el resto de operaciones conectadas"
    es uno de los requisitos de sistema y no puede quedar a discreción
    del LLM. Modifica `analytics_result` in-place.
    """
    if "cascade_risk_context" in analytics_result or not flight_context:
        return

    origin = flight_context.get("origin")
    month = flight_context.get("month")
    scheduled_dep = flight_context.get("scheduled_dep")
    if not origin or not month or scheduled_dep is None:
        return

    tool_fn = _TOOLS_BY_NAME.get("get_cascade_risk_context")
    if tool_fn is None:
        return

    tool_args = {
        "origin": origin,
        "month": month,
        "dep_hour": scheduled_dep // 100,
        "delay_minutes": 0.0,
    }
    start = time.perf_counter()
    try:
        result_content = tool_fn.invoke(tool_args)
        analytics_result["cascade_risk_context"] = json.loads(result_content)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Tool 'get_cascade_risk_context'(%s) -> OK en %.0f ms (invocacion determinista)",
            tool_args, elapsed_ms,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "Tool 'get_cascade_risk_context'(%s) -> ERROR tras %.0f ms: %s",
            tool_args, elapsed_ms, exc,
        )
        return

    analytics_result.setdefault("tools_used", [])
    analytics_result["tools_used"].append("get_cascade_risk_context")


def _derive_delay_prediction(analytics_result: AnalyticsResult) -> Optional[DelayPrediction]:
    """
    Deriva la predicción de retraso de forma determinista a partir de
    `flight_historical_stats` (si esa tool fue invocada). Sin
    interpretación del LLM:

    - `is_disruption`: el retraso medio en llegada supera el umbral
      configurado (Settings.DELAY_THRESHOLD_MINUTES).
    - `confidence`: heurística por tramos de `sample_size` (menos de 30
      vuelos históricos comparables -> confianza baja; más de 200 ->
      confianza alta).
    - `main_cause`: la causa dominante ya calculada por SQL en la tool
      (`dominant_delay_cause`), no una interpretación adicional.

    Devuelve None si no se consultaron estadísticas de un vuelo concreto.
    """
    stats = analytics_result.get("flight_historical_stats")
    if not stats:
        return None

    sample_size = stats.get("sample_size") or 0
    avg_arr = stats.get("avg_arr_delay_min")

    if sample_size == 0 or avg_arr is None:
        return DelayPrediction(
            expected_dep_delay_min=0.0,
            expected_arr_delay_min=0.0,
            is_disruption=False,
            confidence=0.0,
            main_cause="unknown",
        )

    if sample_size < 30:
        confidence = round(0.3 + 0.2 * (sample_size / 30), 2)
    elif sample_size <= 200:
        confidence = round(0.5 + 0.3 * ((sample_size - 30) / 170), 2)
    else:
        confidence = round(min(0.8 + 0.15 * ((sample_size - 200) / 800), 0.95), 2)

    return DelayPrediction(
        expected_dep_delay_min=stats.get("avg_dep_delay_min") or 0.0,
        expected_arr_delay_min=avg_arr,
        is_disruption=avg_arr > Settings.DELAY_THRESHOLD_MINUTES,
        confidence=confidence,
        main_cause=stats.get("dominant_delay_cause") or "unknown",
    )


# ---------------------------------------------------------------------------
# Nodo del grafo
# ---------------------------------------------------------------------------

def analytical_agent(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del agente analítico.

    Lee `user_query` y `flight_context` del estado, ejecuta el bucle
    ReAct sobre las herramientas analíticas, ensambla `analytics_result`
    de forma determinista y, si hay estadísticas de un vuelo concreto,
    deriva `delay_prediction`. Nunca escribe texto en lenguaje natural
    dirigido al operador; el único mensaje que añade al canal
    `messages` es una traza técnica construida en código (no por el
    LLM), para depuración.

    En caso de error, escribe en `error` en lugar de lanzar excepción,
    permitiendo que el supervisor redirija al agente de comunicación.
    """
    if not Settings.ollama_available() and not state.get("error"):
        return {
            "analytics_result": AnalyticsResult(tools_used=[]),
            "messages": [
                AIMessage(content="[analytical_agent] Ollama no disponible; modo degradado, sin consultas realizadas.")
            ],
        }

    try:
        tool_results = _run_react_loop(
            user_query=state["user_query"],
            flight_context=state.get("flight_context"),
        )
        analytics_result = _assemble_analytics_result(tool_results)
        flight_context = state.get("flight_context") or _derive_flight_context(tool_results)
        _ensure_cascade_risk_context(analytics_result, flight_context)
        delay_prediction = _derive_delay_prediction(analytics_result)

    except Exception as exc:  # noqa: BLE001
        logger.error("analytical_agent fallo: %s", exc, exc_info=Settings.DEBUG_MODE)
        return {"error": f"Error en analytical_agent: {exc}"}

    tools_used = analytics_result.get("tools_used", [])
    trace_text = (
        f"[analytical_agent] tools consultadas: {', '.join(tools_used)}"
        if tools_used
        else "[analytical_agent] no se consultó ninguna herramienta."
    )
    logger.info(
        "analytical_agent resumen: tools=%s, delay_prediction=%s",
        tools_used or "[]", "is_disruption=" + str(delay_prediction["is_disruption"]) if delay_prediction else "N/A",
    )

    update: dict = {
        "analytics_result": analytics_result,
        "messages": [AIMessage(content=trace_text)],
    }
    if delay_prediction is not None:
        update["delay_prediction"] = delay_prediction
    if flight_context:
        update["flight_context"] = flight_context

    return update
