# Devlog: refactor-agente-analitico

---

## [2026-07-02 00:00] — Inicio del evolutivo
- Carpeta creada en `docs/features/refactor-agente-analitico/`
- Análisis iniciado tras revisar `data/data_ingestion.py`, `agents/analytical_agent.py`, `tools/analytical_tools.py`, `prompts/analytical_prompt.py`, `graph/state.py`, `agents/disruption_agent.py`, `tools/disruption_tools.py`, `agents/communication_agent.py`, `graph/supervisor.py`

## [2026-07-02 00:10] — Análisis aprobado (respuestas del usuario)
- 6.1: Confirmado — el agente analítico deja el modo `"prediction"`; `predict_flight_delay`/`get_cascade_risk_flights` se redefinen como tools factuales dentro de `analytical_tools.py` (no se mueven a `disruption_tools.py`), porque el agente de disrupción no accederá a la base de datos. Los 3 tools existentes de `disruption_tools.py` (propuesta de acciones) quedan fuera de alcance de este evolutivo.
- 6.2: JSON de salida con estructura fija tipada y campos opcionales según tipo de consulta.
- 6.3: Se prioriza el patrón más rápido posible sin perder funcionalidad — se mantiene el patrón de 2 fases (ReAct + `with_structured_output`, ya validado con Ollama) pero se optimiza el bucle (menos iteraciones máximas, fomentar llamadas a varias tools por turno).
- 6.4: El nodo puede dejar un mensaje breve de trazabilidad si no añade coste relevante — se resuelve construyéndolo de forma determinista (sin LLM extra) a partir del log de tools invocadas, no generado por el modelo.
- Pasando a Fase 2 (planificación técnica).

## [2026-07-02 00:20] — Planificación redactada, pendiente de validación
- `02_planificacion.md` completo: fase 2 del agente analítico pasa a ensamblaje determinista (sin segunda llamada LLM), predicción trasladada a `disruption_agent`.

## [2026-07-02 00:30] — Redirección del usuario: la predicción vuelve al agente analítico
- El usuario, tras leer `02_planificacion.md`, corrige: quiere que `analytical_agent` siga haciendo las predicciones; lo importante era que la comunicación entre agentes sea JSON explícito (estilo MCP), no que cambie de agente quién predice.
- Lección registrada en `04_lecciones_aprendidas.md`.
- `01_analisis.md` (nota de interpretación en 6.1) y `02_planificacion.md` (enfoque, decisiones de diseño, cambios por módulo, plan de pruebas, complejidad) actualizados in-place para reflejar el diseño corregido: `analytical_agent` calcula `delay_prediction` de forma determinista (no LLM); `disruption_agent` solo lo consume; se generaliza la serialización JSON explícita entre agentes a `disruption_agent` y `communication_agent`.
- Vuelvo a pedir validación de `02_planificacion.md` antes de generar `03_tareas_pendientes.md`.

## [2026-07-02 00:40] — Planificación aprobada, desglose de tareas generado
- Usuario aprueba pasar a la siguiente fase.
- `03_tareas_pendientes.md` creado con 8 bloques (~19 tareas): preparación, tools, estado, prompts, agente analítico, ajustes mínimos en disrupción/comunicación, tests, cierre.
- Nota añadida: `docs/templates/review-template.html` no existe todavía en el repo; se marcó como bloqueante para T8.2 (generación del HTML de cierre).
- Pendiente: validación del usuario sobre el desglose antes de empezar la ejecución.

## [2026-07-02 00:50] — Desglose aprobado, inicio de ejecución
- Usuario aprueba el desglose de tareas ("vamos al lío").
- T1.1: se pregunta al usuario rama vs `main`; decide trabajar directamente en `main`, sin rama separada. Tarea marcada como resuelta (no aplica crear rama).
- Empieza el Bloque 2 (tools).

## [2026-07-02 01:00] — Bloque 2 completado (tools)
- `tools/analytical_tools.py`: `predict_flight_delay` → `get_flight_historical_stats` (salida factual: `pct_over_threshold`, `dominant_delay_cause`, sin `main_cause` interpretado); `get_cascade_risk_flights` → `get_cascade_risk_context`. `ANALYTICAL_TOOLS` actualizada. Las 6 tools exploratorias no requirieron cambios (shape ya coincide con los `TypedDict` planificados).

## [2026-07-02 01:10] — Bloque 3 completado (estado)
- `graph/state.py`: nuevos `TypedDict` (`RouteStat`, `AirportStat`, `AirlineStat`, `HourStat`, `MonthStat`, `CauseStat`, `FlightHistoricalStats`, `CascadeRiskFlight`); `AnalyticsResult` retipado con `total=False` agrupándolos + `tools_used`; eliminado el cajón de sastre `summary_stats`. Comentario de `delay_prediction` actualizado para reflejar el cálculo determinista. Import `Any` retirado (sin uso). Verificado con `ast.parse`.

## [2026-07-02 01:20] — Bloque 4 completado (prompts)
- `prompts/analytical_prompt.py`: reescrito por completo. Solo queda `ANALYTICAL_REACT_SYSTEM_PROMPT` (nombres de tools actualizados, instrucción de pedir varias tools en un mismo turno, prohibición explícita de narrativa). `ANALYTICAL_STRUCTURED_SYSTEM_PROMPT` eliminado.
- `prompts/disruption_prompt.py`: `DISRUPTION_REACT_SYSTEM_PROMPT` y `DISRUPTION_STRUCTURED_SYSTEM_PROMPT` actualizados para describir la entrada como bloques JSON (`delay_prediction` + `analytics_result` opcional); reglas de `severity`/`actions`/`reasoning` sin cambios.

## [2026-07-02 01:35] — Bloque 5 completado (agente analítico)
- `agents/analytical_agent.py` reescrito por completo: eliminada `AnalyticalOutput`/`_synthesize()` (fase 2 LLM); `_run_react_loop` ahora devuelve `list[tuple[tool_name, resultado_json]]`; nuevo `_assemble_analytics_result` (ensamblaje determinista vía `_TOOL_NAME_TO_FIELD` + `json.loads`); nuevo `_derive_delay_prediction` (heurística determinista de `confidence`/`is_disruption`/`main_cause`); nodo `analytical_agent(state)` escribe `analytics_result` siempre y `delay_prediction` solo si hay `flight_historical_stats`; traza de `messages` construida en código, sin LLM. `_MAX_REACT_TURNS = 3`. Verificado con `ast.parse`.

## [2026-07-02 01:45] — Bloque 6 completado (comunicación JSON entre agentes)
- `agents/disruption_agent.py`: `_run_react_loop`/`_synthesize` reciben ahora también `analytics_result`; `delay_prediction`/`analytics_result`/`flight_context` se serializan con `json.dumps(..., ensure_ascii=False)` en el prompt en vez de interpolar el dict de Python. `DisruptionOutput` sin cambios de forma.
- `agents/communication_agent.py`: `_build_context_block` serializa `analytics_result`/`delay_prediction`/`disruption_proposal` con `json.dumps(...)`. Verificado ambos con `ast.parse`.

## [2026-07-02 02:00] — Bloque 7 completado (tests) y pausa del evolutivo
- Actualizados: `tests/conftest.py` (fixture `sample_analytics_result` al nuevo shape), `tests/unit/test_analytical_tools.py` (renombrados + `TestGetCascadeRiskContext` nueva), `tests/unit/test_state.py`, `tests/integration/test_analytical_agent.py` (reescrito por completo: ya no hay mock de `with_structured_output`, se añaden tests unitarios puros de `_derive_delay_prediction`, modo degradado, multi-tool-en-un-turno, JSON malformado), `tests/integration/test_disruption_agent.py` (test nuevo de serialización JSON), `tests/integration/test_supervisor.py` (eliminadas referencias a `AnalyticalOutput`, que ya no existe).
- Suite completa ejecutada: **136 passed, 1 failed**. El único fallo (`test_hours_are_in_valid_range`, `get_delay_by_hour` devuelve `hour == 24`) es preexistente, no relacionado con este refactor (no se tocó esa tool ni su SQL).
- El usuario pide dejar la verificación exhaustiva (incluida la investigación de ese fallo preexistente) y la validación manual con Ollama para más adelante; da por bueno el trabajo hasta este punto. Bloque 8 (validación manual + cierre con HTML de revisión) queda pospuesto, sin cerrar el evolutivo todavía.
