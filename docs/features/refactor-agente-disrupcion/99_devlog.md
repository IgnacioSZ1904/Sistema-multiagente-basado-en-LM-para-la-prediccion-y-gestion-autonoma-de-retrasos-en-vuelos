# Devlog: refactor-agente-disrupcion

---

## [2026-07-03 00:00] — Inicio del evolutivo
- Carpeta creada en `docs/features/refactor-agente-disrupcion/`.
- Lección aprendida consultada de `docs/features/refactor-agente-analitico/04_lecciones_aprendidas.md`: no sobre-interpretar frases ambiguas con alto impacto arquitectónico sin confirmar antes con el usuario.
- Revisados: `agents/disruption_agent.py`, `tools/disruption_tools.py`, `prompts/disruption_prompt.py`, `graph/state.py` (`DisruptionProposal`), `agents/communication_agent.py`, `config/settings.py`, `backend/app/schemas.py`.
- Análisis redactado. Pregunta clave 6.1 (destino de las 3 tools de `disruption_tools.py` que hoy acceden a BD) puede reabrir `analytical_agent.py`, ya cerrado en el evolutivo anterior — se deja explícito como pregunta abierta, sin asumir la respuesta.

## [2026-07-03 00:15] — Análisis respondido; 6.1 se corrige tras validar
- Usuario responde las 6 preguntas abiertas. 6.1 se corrige: el agente de disrupción **conserva** el acceso a BD (la preocupación era latencia, no el acceso en sí). 6.2: criterio seleccionable desde la interfaz, no solo config fija. 6.3: proxy de coste aprobado. 6.4: simplificar al máximo. 6.5: campos extra aprobados. 6.6: cascade risk determinista aprobado si no complica.
- `01_analisis.md` actualizado in-place (objetivo, criterios de aceptación) para reflejar la corrección de 6.1.
- `02_planificacion.md` redactado: las 3 tools se llaman de forma determinista desde código (sin bucle ReAct), eliminando la preocupación de latencia sin renunciar a BD; severity/selección de alternativa/coste se calculan en código, el LLM solo redacta `actions`/`reasoning`; `optimization_criterion` viaja como parámetro de la consulta desde el frontend; `get_cascade_risk_context` pasa a ser determinista en `analytical_agent` (único cambio ahí).
- Pendiente: validación del usuario antes de generar `03_tareas_pendientes.md`.

## [2026-07-03 00:25] — Planificación aprobada, desglose de tareas generado
- Usuario aprueba pasar a la siguiente fase ("okey sigamos").
- `03_tareas_pendientes.md` creado con 9 bloques (~24 tareas): config, estado, agente analítico (cambio acotado), agente de disrupción (reescritura), prompts, plumbing API/CLI, frontend, tests, validación manual y cierre.
- Pendiente: validación del usuario sobre el desglose antes de empezar la ejecución.

## [2026-07-03 00:35] — Desglose aprobado; validación manual y cierre (Bloque 9) pospuestos
- Usuario aprueba el desglose y pide, como en el evolutivo anterior, posponer la validación manual; iterar hasta el Bloque 8 inclusive.
- Bloque 1 (config) y Bloque 2 (estado) completados: `Settings.OPTIMIZATION_CRITERIA`/`DEFAULT_OPTIMIZATION_CRITERION`; `graph/state.py` con `AlternativeCandidate`, `DisruptionSourceContext`, `DisruptionProposal` ampliado, `SGIDAState.optimization_criterion`, `initial_state` actualizado. Verificado con `ast.parse` + smoke test.
- Bloque 3 completado: `analytical_agent.py` gana `_ensure_cascade_risk_context()`, invocada tras `_assemble_analytics_result` y antes de `_derive_delay_prediction`; garantiza `cascade_risk_context` cuando hay `flight_context`, sin depender de que el LLM decida llamar a esa tool. Cambio aislado, verificado con `ast.parse`.
- Bloque 4 completado: `disruption_agent.py` reescrito por completo. Sin bucle ReAct/`bind_tools`; `_gather_disruption_data` invoca las 3 tools directamente; `_compute_severity`, `_select_best_alternative`, `_estimate_operational_cost` deterministas; `DisruptionOutput` → `DisruptionNarrative` (solo `actions`/`reasoning`, única llamada LLM); nodo ensambla `DisruptionProposal` completo con `source_context`. Modo degradado actualizado. Verificado con `ast.parse`.
- Bloque 5 completado: `disruption_prompt.py` reescrito — eliminado el prompt ReAct, `DISRUPTION_STRUCTURED_SYSTEM_PROMPT` ahora solo guía la redacción de `actions`/`reasoning` sobre datos ya calculados. Verificado con `ast.parse`; sin referencias colgantes al prompt eliminado (grep limpio).
- Bloque 6 completado: `optimization_criterion` conectado de extremo a extremo — `QueryRequest` (schemas.py) → `execute_query` (routes/query.py) → `QueryService.execute` → `run_query` (supervisor.py) → `initial_state`. Banner de `cli.py` muestra el criterio activo por defecto. Verificado con `ast.parse` en los 5 ficheros tocados.
- Bloque 7 completado: `App.jsx` con selector de criterio (`<select>`) y `optimization_criterion` en el body del POST. Corregido de paso un bug preexistente en el `onChange` del textarea (pisaba todo el `form` en vez de fusionar). `npx vite build` verificado sin errores.

## [2026-07-03 01:15] — Bloque 8 completado (tests); Bloque 9 pospuesto
- `tests/conftest.py`: `sample_disruption_proposal` actualizado al nuevo shape de `DisruptionProposal`.
- `tests/unit/test_state.py`: `DisruptionProposal` ampliado + `TestAlternativeCandidate`; `initial_state` con/sin `optimization_criterion`.
- `tests/integration/test_disruption_agent.py`: reescrito por completo — ya no se mockea `bind_tools` (el agente no tiene bucle ReAct); se mockea la única llamada `with_structured_output`; nuevos tests unitarios puros de `_compute_severity`, `_select_best_alternative`, `_estimate_operational_cost`; tests de una sola llamada LLM, contexto JSON, modo degradado, `flight_context` ausente.
- `tests/integration/test_analytical_agent.py`: 2 tests nuevos sobre la invocación determinista de `get_cascade_risk_context`.
- `tests/integration/test_supervisor.py`: revisado, compatible sin cambios.
- Suite completa: **158 passed, 1 failed** (mismo fallo preexistente no relacionado, `get_delay_by_hour`).
- El usuario pide, como en el evolutivo anterior, posponer la validación manual y el cierre (Bloque 9, incluido el HTML de revisión) para más adelante. El evolutivo queda documentado y en curso, listo para retomarse.