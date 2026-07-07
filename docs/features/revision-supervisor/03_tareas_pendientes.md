# Tareas pendientes: revision-supervisor

> Estado: 🟡 En curso
> Última actualización: 2026-07-05

## Bloque 1 — Supervisor determinista
- [x] T1.1 — Reescrito `graph/supervisor.py`: `supervisor(state)` reducido a `safe_next_node(state, "") + iteration++`; eliminados `RoutingDecision`, `_build_state_summary`, la llamada LLM y los imports sin uso
- [x] T1.2 — Eliminado `prompts/supervisor_prompt.py`. Verificado con `grep`: solo quedaba referenciado en `test_supervisor.py` (pendiente de Bloque 5)

## Bloque 2 — Tool de cascade risk
- [x] T2.1 — `tools/analytical_tools.py`: `get_cascade_risk_context` cambia `flight_date: str` por `month: int`; docstring actualizado; eliminado el parseo de fecha

## Bloque 3 — Agente analítico: derivar `flight_context`
- [x] T3.1 — `_run_react_loop`: cada entrada de `tool_results` pasa a `(tool_name, tool_args, content)`
- [x] T3.2 — `_assemble_analytics_result`: ajustado al nuevo shape de 3-tupla
- [x] T3.3 — Nueva `_derive_flight_context(tool_results) -> Optional[FlightContext]`
- [x] T3.4 — `_ensure_cascade_risk_context`: usa `flight_context.get("month")` en vez de `flight_date`; invoca la tool con `month`
- [x] T3.5 — Nodo `analytical_agent(state)`: calcula `flight_context` (estado previo o derivado) y lo añade a `update` solo si es verdadero (nunca sobrescribe con `None`)

## Bloque 4 — Estado
- [x] T4.1 — `graph/state.py`: comentario de `flight_context` actualizado (puede derivarse en `analytical_agent`)

## Bloque 5 — Tests
- [x] T5.1 — Reescrito `tests/integration/test_supervisor.py`: `TestSupervisorNodeIsolated` sin mocks de LLM (llamada directa a `supervisor(state)`, 8 tests cubriendo las 5 reglas + límite de iteraciones); `TestFullGraphEndToEnd` sin mock de `graph.supervisor.get_llm`; nuevo test de límite de iteraciones que verifica que corta el flujo antes de `disruption_agent` aunque haya disrupción detectada
- [x] T5.2 — `tests/unit/test_analytical_tools.py`: `TestGetCascadeRiskContext` actualizado a `month`
- [x] T5.3 — `tests/integration/test_analytical_agent.py`: nueva `TestDeriveFlightContext` (unitaria pura) + test de que el nodo deriva y escribe `flight_context` sin que venga pre-suministrado (el caso real de producción)
- [x] T5.4 — Suite completa ejecutada: **185 passed, 1 failed** (mismo fallo preexistente de `get_delay_by_hour`, no relacionado)

## Bloque 6 — Cierre
- [ ] T6.1 — Resumen final en `99_devlog.md`
- [ ] T6.2 — Generar `revision-supervisor-review.html` (sigue bloqueado: falta `docs/templates/review-template.html`) — a confirmar si aplica, dado que el usuario pasará directamente a pruebas manuales propias tras este evolutivo
