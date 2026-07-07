# Tareas pendientes: refactor-agente-disrupcion

> Estado: 🟡 En curso (Bloques 1-8 completados; Bloque 9 pospuesto a petición del usuario)
> Última actualización: 2026-07-03

## Bloque 1 — Configuración
- [x] T1.1 — `config/settings.py`: añadido `OPTIMIZATION_CRITERIA = ("min_passengers", "min_cost")` y `Settings.DEFAULT_OPTIMIZATION_CRITERION` (env `DEFAULT_OPTIMIZATION_CRITERION`, por defecto `"min_passengers"`)

## Bloque 2 — Estado (`graph/state.py`)
- [x] T2.1 — Nuevo `TypedDict AlternativeCandidate` (`airline`, `scheduled_dep`, `avg_arr_delay_min`, `reliability_pct`, `score`, `selected`)
- [x] T2.2 — Nuevo `TypedDict DisruptionSourceContext` (`total=False`: `delay_prediction`, `cascade_risk_context`, `flight_context`)
- [x] T2.3 — Ampliado `DisruptionProposal` con `optimization_criterion`, `alternatives_considered`, `estimated_operational_cost`, `source_context`
- [x] T2.4 — Añadido `SGIDAState.optimization_criterion: str`
- [x] T2.5 — Actualizado `initial_state(user_query, optimization_criterion=None)`: aplica `Settings.DEFAULT_OPTIMIZATION_CRITERION` si no se especifica. Verificado con smoke test (`min_passengers` por defecto).

## Bloque 3 — Agente analítico (cambio acotado)
- [x] T3.1 — `analytical_agent.py`: nueva `_ensure_cascade_risk_context()`, invocada tras el ensamblaje; si hay `flight_context` y el LLM no llamó a `get_cascade_risk_context`, se invoca de forma determinista (in-place sobre `analytics_result`)

## Bloque 4 — Agente de disrupción (reescritura)
- [x] T4.1 — Eliminado el bucle ReAct / `bind_tools` de `disruption_agent.py`
- [x] T4.2 — `_gather_disruption_data(flight_context) -> dict`: invoca directamente las 3 tools con los argumentos derivados de `flight_context`, con defaults seguros si falta información
- [x] T4.3 — `_compute_severity(expected_arr_delay_min, has_reliable_alternative) -> str`
- [x] T4.4 — `_select_best_alternative(candidates, criterion) -> tuple[Optional[dict], list[AlternativeCandidate]]`
- [x] T4.5 — `_estimate_operational_cost(ground_activity, num_alternatives_available) -> float`
- [x] T4.6 — `DisruptionOutput` → `DisruptionNarrative` (solo `actions`/`reasoning`); `_synthesize` reducido a una única llamada `with_structured_output`
- [x] T4.7 — Nodo `disruption_agent(state)` reescrito: ensambla `DisruptionProposal` completo
- [x] T4.8 — Modo degradado actualizado al nuevo shape (incluye `source_context`, `optimization_criterion`, listas vacías)

## Bloque 5 — Prompts
- [x] T5.1 — Eliminado `DISRUPTION_REACT_SYSTEM_PROMPT`
- [x] T5.2 — Reescrito `DISRUPTION_STRUCTURED_SYSTEM_PROMPT`: solo instruye la redacción de `actions`/`reasoning` a partir de datos ya calculados

## Bloque 6 — Plumbing API / CLI
- [x] T6.1 — `backend/app/schemas.py`: `QueryRequest.optimization_criterion: str | None = None`
- [x] T6.2 — `backend/app/services/query_service.py`: `QueryService.execute` acepta y propaga `optimization_criterion`
- [x] T6.3 — `graph/supervisor.py`: `run_query()` acepta y propaga `optimization_criterion` a `initial_state`
- [x] T6.4 — `backend/app/api/routes/query.py`: pasa `payload.optimization_criterion` a `service.execute(...)`
- [x] T6.5 — `backend/app/cli.py`: banner ahora muestra el criterio activo por defecto

## Bloque 7 — Frontend
- [x] T7.1 — `frontend/src/App.jsx`: `optimization_criterion` añadido al estado del formulario, `<select>` con las dos opciones, incluido en el body del POST. De paso se corrigió un bug preexistente: el `onChange` del textarea reemplazaba todo el objeto `form` en vez de fusionar. Build de producción (`vite build`) verificado sin errores.

## Bloque 8 — Tests
- [x] T8.1 — `tests/unit/test_state.py`: `DisruptionProposal` ampliado (+ `TestAlternativeCandidate`); `initial_state` con y sin `optimization_criterion`. `tests/conftest.py`: `sample_disruption_proposal` actualizado al nuevo shape.
- [x] T8.2 — Reescrito `tests/integration/test_disruption_agent.py`: ya no se mockea `bind_tools`; se mockea la única llamada `with_structured_output`; tests unitarios de `_compute_severity`, `_select_best_alternative` (criterios distintos eligen candidatos distintos), `_estimate_operational_cost`; test de una sola llamada LLM; test de contexto JSON; modo degradado; `flight_context` ausente sin crash
- [x] T8.3 — `tests/integration/test_analytical_agent.py`: 2 tests nuevos — `get_cascade_risk_context` se invoca de forma determinista con `flight_context` aunque el LLM no la pida, y NO se fuerza sin `flight_context`
- [x] T8.4 — Revisado `tests/integration/test_supervisor.py`: compatible sin cambios (disruption_agent no se invoca en el flujo exploratorio probado; el resto no depende de la forma interna de `disruption_proposal`)
- [x] T8.5 — Suite completa ejecutada: **158 passed, 1 failed** (mismo fallo preexistente de `get_delay_by_hour`, no relacionado con este evolutivo — ver evolutivo anterior)

## Bloque 9 — Validación manual y cierre
- [ ] T9.1 — Validación manual: probar ambos criterios desde el frontend y comprobar que cambian la alternativa elegida (alcance a confirmar con el usuario, como en el evolutivo anterior)
- [ ] T9.2 — Generar `refactor-agente-disrupcion-review.html` (sigue bloqueado: `docs/templates/review-template.html` no existe)
- [ ] T9.3 — Resumen final en `99_devlog.md` y cierre del evolutivo