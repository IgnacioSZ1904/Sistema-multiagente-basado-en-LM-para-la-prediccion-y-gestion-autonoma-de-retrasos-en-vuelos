# Tareas pendientes: refactor-agente-analitico

> Estado: 🟡 En curso (Bloques 1-7 completados; Bloque 8 pospuesto a petición del usuario)
> Última actualización: 2026-07-02

## Bloque 1 — Preparación
- [x] T1.1 — Crear rama `feature/refactor-agente-analitico` — **Decisión del usuario: se trabaja directamente en `main`, sin rama separada.**

## Bloque 2 — Tools (`tools/analytical_tools.py`)
- [x] T2.1 — Renombrar `predict_flight_delay` → `get_flight_historical_stats`; quitar lenguaje de "predicción" del docstring; renombrar salida `pct_disrupted` → `pct_over_threshold`, `main_cause` → `dominant_delay_cause`
- [x] T2.2 — Renombrar `get_cascade_risk_flights` → `get_cascade_risk_context`; ajustar docstring a lenguaje puramente descriptivo (sin "riesgo" interpretado por LLM)
- [x] T2.3 — Actualizar la lista `ANALYTICAL_TOOLS` con los nuevos nombres
- [x] T2.4 — Revisar las 6 tools exploratorias existentes: shape confirmado, coincide con los `TypedDict` planificados (`AirportStat`, `AirlineStat`, `RouteStat`, `MonthStat`, `HourStat`, `CauseStat`); sin cambios de código necesarios

## Bloque 3 — Estado (`graph/state.py`)
- [x] T3.1 — Definir los sub-`TypedDict`: `RouteStat`, `AirportStat`, `AirlineStat`, `HourStat`, `MonthStat`, `CauseStat`, `FlightHistoricalStats`, `CascadeRiskFlight`
- [x] T3.2 — Redefinir `AnalyticsResult(TypedDict, total=False)` agrupando los anteriores como campos opcionales + `tools_used: list[str]`; eliminado `summary_stats`
- [x] T3.3 — Actualizado el comentario de `delay_prediction` (se deriva de forma determinista en `analytical_agent`, no por interpretación LLM); import `Any` retirado por quedar sin uso

## Bloque 4 — Prompts
- [x] T4.1 — Reescribir `ANALYTICAL_REACT_SYSTEM_PROMPT`: nombres de tools actualizados, instrucción de solicitar varias tools en el mismo turno cuando aplique, prohibición explícita de narrativa/conclusiones, aclarar que `get_flight_historical_stats`/`get_cascade_risk_context` solo se usan si hay `flight_context`
- [x] T4.2 — Eliminado `ANALYTICAL_STRUCTURED_SYSTEM_PROMPT` (ya no hay fase de síntesis LLM) y sus referencias
- [x] T4.3 — Actualizado `DISRUPTION_REACT_SYSTEM_PROMPT`: menciona que el contexto de entrada incluye `analytics_result` (además de `delay_prediction`) como bloques JSON
- [x] T4.4 — Ajustado `DISRUPTION_STRUCTURED_SYSTEM_PROMPT`: describe el formato de entrada como JSON estructurado (sin cambiar las reglas de `severity`/`actions`/`reasoning`)

## Bloque 5 — Agente analítico (`agents/analytical_agent.py`)
- [x] T5.1 — Eliminado `AnalyticalOutput` (Pydantic) y `_synthesize()`
- [x] T5.2 — `_run_react_loop` ajustado para devolver `list[tuple[tool_name, tool_result_json]]`
- [x] T5.3 — Implementado `_TOOL_NAME_TO_FIELD` y `_assemble_analytics_result(tool_results) -> AnalyticsResult`
- [x] T5.4 — Implementado `_derive_delay_prediction(analytics_result) -> Optional[DelayPrediction]` con heurística determinista de `confidence` por tramos de `sample_size`, `is_disruption` por umbral, `main_cause` = `dominant_delay_cause`
- [x] T5.5 — Nodo `analytical_agent(state)` reescrito: ensambla `analytics_result` + `delay_prediction`, `AIMessage` de trazabilidad construido en código, modo degradado con contrato tipado
- [x] T5.6 — `_MAX_TOOL_CALLS` renombrado a `_MAX_REACT_TURNS`, reducido de 5 a 3

## Bloque 6 — Ajustes mínimos en agentes consumidores
- [x] T6.1 — `disruption_agent._run_react_loop`/`_synthesize`: aceptan `analytics_result` además de `delay_prediction`; ambos serializados con `json.dumps(..., ensure_ascii=False)` en el prompt (sin cambiar `DisruptionOutput` ni la lógica de síntesis)
- [x] T6.2 — `disruption_agent(state)`: pasa `state.get("analytics_result")` a las funciones anteriores
- [x] T6.3 — `communication_agent._build_context_block`: serializa `analytics_result`/`delay_prediction`/`disruption_proposal` con `json.dumps(...)` en vez de interpolar el dict de Python directamente

## Bloque 7 — Tests
- [x] T7.1 — Actualizado `tests/unit/test_analytical_tools.py` (nombres renombrados, campos `pct_over_threshold`/`dominant_delay_cause`, añadidos tests de `get_cascade_risk_context`)
- [x] T7.2 — Reescrito `tests/integration/test_analytical_agent.py`: caso exploratorio multi-tool en un turno, caso `flight_context` con `delay_prediction` derivado, assert de que no se llama `with_structured_output`, tests unitarios puros de `_derive_delay_prediction`, modo degradado, tool inexistente, JSON malformado
- [x] T7.3 — Actualizado `tests/integration/test_disruption_agent.py`: nuevo test que verifica que `analytics_result` se serializa como JSON explícito en el prompt (no `repr()` de dict)
- [x] T7.4 — Actualizado `tests/unit/test_state.py` a la nueva forma de `AnalyticsResult`
- [x] T7.5 — `tests/integration/test_supervisor.py` sí requería cambios (usaba `AnalyticalOutput`, eliminada): actualizado para mockear solo `bind_tools` del agente analítico, sin `with_structured_output`. `tests/test_communication_tools.py` no requirió cambios.
- [x] T7.6 — Suite completa ejecutada: **136 passed, 1 failed**. El fallo (`TestGetDelayByHour::test_hours_are_in_valid_range`, `hour == 24`) es **preexistente y no relacionado con este evolutivo** — `get_delay_by_hour` no se modificó (T2.4); es un caso límite de datos del dataset real (`CRSDepTime` con valor fuera de 0-2359). No se investiga más a fondo ahora: **el usuario decide dejar la verificación exhaustiva de tests (automática y manual) para más adelante** y da por bueno el trabajo realizado hasta este punto.

## Bloque 8 — Validación manual y cierre
- [!] T8.1 — Validación manual con Ollama real: **pospuesta a petición del usuario** ("los test automáticos y manual los dejamos para más adelante").
- [!] T8.2 — Generar `refactor-agente-analitico-review.html`: **pospuesta**. Sigue pendiente además que `docs/templates/review-template.html` no existe todavía en el repo.
- [!] T8.3 — Resumen final y cierre formal del evolutivo: **pospuesto**, no se cierra todavía.

---

**Nota sobre el Bloque 1 (T1.1):** antes de crear la rama se pedirá confirmación explícita, ya que implica una acción sobre el repositorio git.
