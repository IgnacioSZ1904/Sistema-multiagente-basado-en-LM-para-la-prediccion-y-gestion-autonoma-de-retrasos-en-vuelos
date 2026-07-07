# Planificación: revision-supervisor

## 1. Enfoque técnico

**Hallazgo B (supervisor determinista):** `supervisor()` deja de consultar al LLM. Se reduce a `next_agent = safe_next_node(state, "")` (la misma función de `graph/router.py` que ya se invoca hoy como base antes de intentar el LLM) + incrementar `iteration`. Se elimina `RoutingDecision`, `SUPERVISOR_SYSTEM_PROMPT`, `_build_state_summary` y la dependencia de `get_llm()`/`langchain_core.messages` en `graph/supervisor.py`. `graph/router.py` no cambia — ya era la fuente de verdad determinista, ahora pasa a ser la ÚNICA fuente de verdad.

**Hallazgo A (flight_context real):** `analytical_agent` pasa a capturar los argumentos (`tool_args`) con los que el LLM invocó `get_flight_historical_stats` durante el bucle ReAct (hoy se descartan, solo se guarda el resultado). Con esos argumentos construye determinísticamente un `FlightContext` y lo escribe de vuelta en el estado — sin ninguna llamada LLM adicional, igual que el resto de la fase 2 de este agente. Como consecuencia, `_ensure_cascade_risk_context` dispone de un `flight_context` real con el que invocar `get_cascade_risk_context`, que se simplifica para pedir `month: int` directamente (ya no necesita fingir una fecha completa que nadie tiene). `disruption_agent` no cambia: ya sabía leer `flight_context`, simplemente ahora recibe uno relleno de verdad.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| `supervisor()` pasa a ser determinista al 100%, sin LLM | Mantenerlo como está (LLM redundante pero inofensivo) | Confirmado en 6.1: la regla de la primera iteración es siempre "analytical_agent" por construcción del grafo — el LLM nunca decide nada distinto. Elimina una llamada LLM completa por consulta |
| `analytical_agent` deriva `flight_context` de los argumentos ya usados para `get_flight_historical_stats`, sin llamada LLM adicional | Añadir un paso de NLU/extracción separado (con o sin LLM) | Confirmado en 6.2: los argumentos ya existen (el LLM se los pasó a la tool), reutilizarlos es gratis; añadir un extractor nuevo sería una llamada LLM extra para conseguir información que ya tenemos |
| `get_cascade_risk_context` pasa a pedir `month: int` en vez de `flight_date: str` | Mantener `flight_date` y construir una fecha ficticia (p. ej. día 1) para no romper la firma | Construir una fecha ficticia sería peor: parece un dato real y no lo es. El propio parseo actual de `flight_date` solo extraía el mes — pedirlo directamente es más honesto y más simple |
| `analytical_agent` solo escribe `flight_context` en el estado si consigue derivar uno (nunca sobrescribe con `None` un valor ya presente) | Escribir siempre `flight_context` (incluyendo `None`) | Evita borrar accidentalmente un `flight_context` que en el futuro pudiera venir ya precargado desde otro origen (p. ej. un formulario estructurado) |

## 3. Cambios por módulo

### `graph/supervisor.py`
- `supervisor(state)`: se reduce a `{"next_agent": safe_next_node(state, ""), "iteration": state["iteration"] + 1}`.
- Se elimina `RoutingDecision`, `_build_state_summary`, el `try/except` de la llamada LLM, y los imports que quedan sin uso (`get_llm`, `SystemMessage`, `HumanMessage`, `SUPERVISOR_SYSTEM_PROMPT`, `Field`, `BaseModel`, `Literal`).
- Docstring del módulo actualizado: explica que el routing es 100% determinista y por qué (hallazgo de este evolutivo).

### `prompts/supervisor_prompt.py`
- Se elimina el fichero (ya no lo importa nadie).

### `tools/analytical_tools.py`
- `get_cascade_risk_context`: firma cambia de `flight_date: str` a `month: int`; se elimina el parseo `int(flight_date.split("-")[1])`; docstring actualizado.

### `agents/analytical_agent.py`
- `_run_react_loop`: cada entrada de `tool_results` pasa de `(tool_name, content)` a `(tool_name, tool_args, content)` — los argumentos ya estaban disponibles en el bucle, solo se propagan.
- `_assemble_analytics_result`: se ajusta al nuevo shape de 3-tupla (ignora `tool_args`, sigue usando `tool_name`/`content`).
- Nueva función `_derive_flight_context(tool_results) -> Optional[FlightContext]`: busca la última invocación de `get_flight_historical_stats` y construye `FlightContext(airline=..., origin=..., destination=..., month=..., scheduled_dep=...)` a partir de sus argumentos.
- `_ensure_cascade_risk_context`: dependía de `flight_context.get("flight_date")`; pasa a usar `flight_context.get("month")` directamente, y a invocar la tool con `month` en vez de `flight_date`.
- Nodo `analytical_agent(state)`: tras ensamblar `analytics_result`, calcula `flight_context = state.get("flight_context") or _derive_flight_context(tool_results)`; si el resultado es verdadero, lo añade a `update["flight_context"]` (nunca sobrescribe con `None`).

### `graph/state.py`
- Comentario de `flight_context` actualizado: ya no es solo "extraído de la consulta" de forma implícita — se documenta que `analytical_agent` puede derivarlo y escribirlo de forma determinista cuando detecta una consulta de vuelo concreto.

### Tests
- `tests/integration/test_supervisor.py`: reescritura de `TestSupervisorNodeIsolated` (ya no hay LLM que mockear — se llama a `supervisor(state)` directamente y se comprueba `next_agent` según el estado) y de `TestFullGraphEndToEnd` (se retira el mock de `graph.supervisor.get_llm`; el test de límite de iteraciones se replantea para verificar que, con `GRAPH_MAX_ITERATIONS` bajo, el grafo determinista corta el flujo antes de tiempo y aun así termina).
- `tests/unit/test_analytical_tools.py`: `TestGetCascadeRiskContext` actualizado a `month` en vez de `flight_date`.
- `tests/integration/test_analytical_agent.py`: nuevos tests de `_derive_flight_context` (deriva correctamente / `None` sin `get_flight_historical_stats`) y de que el nodo escribe `flight_context` en el resultado cuando corresponde.

## 4. Modelo de datos / contratos
Sin cambios de tipos nuevos. `FlightContext` (ya existente) se rellena ahora con 5 de sus campos opcionales (`airline`, `origin`, `destination`, `month`, `scheduled_dep`) cuando se deriva; el resto (`flight_date`, `year`, `day`, `scheduled_arr`, `distance`) quedan ausentes (campo `total=False`, ya soportado).

`get_cascade_risk_context` — firma nueva: `(origin: str, month: int, dep_hour: int, delay_minutes: float) -> str` (antes `flight_date: str` en vez de `month: int`).

## 5. Plan de pruebas
- Unitarios de `_derive_flight_context`: con/sin llamada a `get_flight_historical_stats`, última invocación gana si se llamó más de una vez.
- Integración de `analytical_agent`: consulta de vuelo concreto → `result["flight_context"]` presente y correcto; consulta exploratoria → sin `flight_context` en el resultado.
- Integración de `disruption_agent`: sin cambios de código, pero se valida (reutilizando fixtures existentes) que sigue funcionando con un `flight_context` de 5 campos (subconjunto real de lo que ahora produce `analytical_agent`).
- Supervisor: tests deterministas puros (sin mocks de LLM) cubriendo las 5 reglas de routing + el límite de iteraciones.
- Suite completa (`pytest`) al cerrar el bloque de implementación.

## 6. Plan de despliegue / migración
No aplica migración de datos. Cambio de comportamiento interno (routing determinista, `flight_context` real) sin cambios de API pública ni de contrato con el frontend.

## 7. Estimación de complejidad
- Nº aproximado de tareas: ~14-16 (supervisor, prompt eliminado, tool de cascade risk, agente analítico, tests).
- Áreas de mayor incertidumbre:
  - Verificar que ninguna otra parte del sistema dependía implícitamente de la llamada LLM del supervisor (p. ej. algún test que asuma que `RoutingDecision`/`get_llm` existen en `graph.supervisor`).
  - Confirmar que el nuevo test de límite de iteraciones sigue siendo representativo ahora que no hay forma de simular una "decisión defectuosa persistente del LLM" (porque ya no hay LLM decidiendo).
