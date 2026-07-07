# Planificación: refactor-agente-disrupcion

## 1. Enfoque técnico

**El agente conserva sus 3 tools de base de datos**, pero deja de decidir con el LLM cuáles invocar: como las tres (`find_alternative_flights`, `estimate_affected_passengers`, `get_airport_ground_activity`) son *siempre* relevantes cuando este agente se ejecuta (solo se invoca si hay `flight_context` y una disrupción detectada/predicha), se llaman **directamente desde código Python**, sin pasar por `bind_tools`/bucle ReAct. Esto elimina por completo la fase de "decisión de qué tool llamar", que era el coste de latencia que preocupaba en 6.1 — se puede mantener el acceso a BD sin pagar rondas de ida y vuelta al LLM para decidir algo que ya sabemos de antemano.

**Máxima determinización, mínimo LLM** (continuando la filosofía ya aplicada en `analytical_agent`): de los cinco elementos que hoy produce el agente (`severity`, `actions`, `affected_passengers_est`, `alternative_flights`, `reasoning`), tres se pueden calcular con código, no con juicio del LLM:
  - `severity`: ya es una regla por rangos de minutos sobre `delay_prediction.expected_arr_delay_min` (documentada en el prompt actual) — se traslada a código.
  - La **selección de la mejor alternativa** entre los candidatos que devuelve `find_alternative_flights`: se puntúa cada candidato según el criterio de optimización activo (`min_passengers` → prioriza `reliability_pct` más alta; `min_cost` → prioriza menos reasignaciones/menor congestión) y se elige determinísticamente el de mayor puntuación. El resto de candidatos quedan en `alternatives_considered` con su puntuación, para que quede constancia de qué se descartó y por qué.
  - `estimated_operational_cost`: proxy numérico (ver §4) calculado a partir de `avg_late_aircraft_delay_min`/congestión de `get_airport_ground_activity` y el número de reasignaciones necesarias.

  Lo único que requiere una llamada LLM es **redactar** `actions` (2-5 acciones concretas en lenguaje operativo) y `reasoning` (justificación breve), a partir de todos los datos ya calculados — una única llamada `with_structured_output`, sin bucle ReAct previo. Esto responde directamente a 6.4 ("simplificar al máximo").

**Criterio configurable desde la interfaz** (6.2): se añade `optimization_criterion` como parámetro de la consulta (no solo una variable de entorno fija), con un valor por defecto en `Settings` si el operador no elige nada. Fluye por todo el pipeline: frontend → `QueryRequest` → `QueryService`/`run_query` → `SGIDAState` → `disruption_agent`.

**Cascade risk determinista** (6.6): el agente analítico deja de dejar `get_cascade_risk_context` a discreción del LLM — se invoca de forma determinista (mismo mecanismo que ya existe para el resto de campos) cada vez que hay `flight_context`, para garantizar que el agente de disrupción siempre tenga ese dato al evaluar alternativas. Es el único cambio que toca `analytical_agent.py` en este evolutivo, y es pequeño y aislado.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| Las 3 tools de disrupción se llaman directamente desde Python (no vía `bind_tools`/ReAct) | Mantener el bucle ReAct actual; eliminar las tools (opción (b) descartada en 6.1) | El usuario confirmó que quiere conservar el acceso a BD; la preocupación de latencia se resuelve quitando la decisión LLM de "qué tool llamar" (que no aporta valor: las 3 siempre son relevantes aquí) |
| `severity`, selección de mejor alternativa y `estimated_operational_cost` se calculan en código; el LLM solo redacta `actions` y `reasoning` | Dejar toda la síntesis en una llamada `with_structured_output` como hoy (calculando también severity/selección) | Igual que en `analytical_agent`: los números y reglas ya deterministas no deben pasar por el LLM (más rápido, sin riesgo de que invente o redondee mal); el LLM aporta valor real en la redacción de acciones y justificación, no en aritmética |
| `optimization_criterion` viaja como parámetro de la consulta (con valor por defecto en `Settings`), no como variable de entorno fija | Solo `Settings` fija; detección automática por texto de la consulta | El usuario quiere que el operador lo seleccione en la interfaz antes de consultar; una config fija no lo permite, y la detección por texto es innecesariamente compleja para un desplegable simple |
| Proxy de `estimated_operational_cost`: combinación normalizada de congestión histórica (`get_airport_ground_activity.avg_departures_in_hour`/`avg_taxi_out_min`) y número de reasignaciones necesarias | Proxy basado solo en distancia/millas; sin proxy (dejar el campo vacío) | Aprobado por el usuario en 6.3; se documenta igual que `estimated_passenger_load`, como heurística explícita dado que el dataset no tiene coste real |
| `get_cascade_risk_context` pasa a invocarse de forma determinista en `analytical_agent` siempre que hay `flight_context`, en vez de depender de que el LLM decida llamarla | Dejarlo como está (discrecional del LLM) | Es uno de los 3 requisitos de sistema citados explícitamente por el usuario ("impacto sobre el resto de operaciones conectadas"); el usuario aprobó en 6.6 hacerlo obligatorio si no complica nada — el cambio es aislado (una línea en el ensamblaje determinista, no una tool nueva) |
| El selector de criterio se añade al frontend (`App.jsx`) como un `<select>` simple en el formulario de consulta | Dejar el frontend fuera de alcance, solo backend | El usuario pidió explícitamente que sea seleccionable "en la interfaz antes de realizar la consulta"; el formulario actual es trivial de extender (un campo más en el estado del formulario y en el body del POST) |

## 3. Cambios por módulo

### `config/settings.py`
- Nueva constante `OPTIMIZATION_CRITERIA = ("min_passengers", "min_cost")`.
- Nuevo `Settings.DEFAULT_OPTIMIZATION_CRITERION: str = os.getenv("DEFAULT_OPTIMIZATION_CRITERION", "min_passengers")`, usado como valor por defecto cuando el operador no elige nada.

### `graph/state.py`
- `SGIDAState`: nuevo campo `optimization_criterion: str` (siempre presente, con el valor efectivo ya resuelto — no `Optional`, porque `initial_state` le aplica el valor por defecto de `Settings` si no se especifica).
- `initial_state(user_query, optimization_criterion=None)`: si `optimization_criterion` es `None`, usa `Settings.DEFAULT_OPTIMIZATION_CRITERION`.
- `DisruptionProposal` ampliado con los campos aprobados en 6.5:
  - `optimization_criterion: str`
  - `alternatives_considered: list[AlternativeCandidate]` (nuevo `TypedDict`: `airline`, `scheduled_dep`, `avg_arr_delay_min`, `reliability_pct`, `score`, `selected: bool`)
  - `estimated_operational_cost: Optional[float]`
  - `source_context: DisruptionSourceContext` (nuevo `TypedDict` con copia de `delay_prediction` y de los campos relevantes de `analytics_result` que motivaron la propuesta, para autocontención del JSON de cara al informe)
- `AnalyticsResult`: sin cambios de forma (ya tiene `cascade_risk_context`); solo cambia CUÁNDO se rellena (ver `analytical_agent.py`).

### `agents/analytical_agent.py`
- Cambio único y acotado: en `_run_react_loop`, cuando hay `flight_context`, tras el turno normal de ReAct, si el LLM no invocó `get_cascade_risk_context` por su cuenta, se invoca igualmente de forma determinista (misma lógica que ya usa `_assemble_analytics_result` para ensamblar campos) antes de devolver los resultados. No se toca el resto del agente.

### `tools/disruption_tools.py`
- Sin cambios en las 3 tools existentes (siguen siendo funciones `@tool` de LangChain, reutilizables también como funciones Python normales vía `.invoke()` o llamando a su función interna).

### `agents/disruption_agent.py`
- Se elimina el bucle ReAct (`_run_react_loop` con `bind_tools`) — las 3 tools se invocan directamente con los argumentos derivados de `flight_context`/`delay_prediction`.
- Nueva función `_gather_disruption_data(flight_context, delay_prediction) -> dict`: llama a las 3 tools con los argumentos ya disponibles en el estado (sin que el LLM decida nada) y devuelve sus resultados parseados.
- Nueva función `_compute_severity(delay_prediction) -> str`: aplica las reglas de rango de minutos ya documentadas hoy en el prompt.
- Nueva función `_select_best_alternative(candidates, criterion) -> tuple[Optional[dict], list[AlternativeCandidate]]`: puntúa cada candidato según el criterio activo y devuelve el elegido + la lista completa puntuada.
- Nueva función `_estimate_operational_cost(ground_activity, num_alternatives_needed) -> float`: proxy determinista documentado.
- `_synthesize(...)`: se simplifica a una única llamada `with_structured_output` sobre un `DisruptionOutput` reducido a `actions` y `reasoning` (el resto ya viene calculado); el prompt incluye todos los datos ya calculados (severity, alternativa elegida, coste estimado, contexto del analítico) para que el LLM redacte con base en ellos.
- El nodo `disruption_agent(state)` ensambla el `DisruptionProposal` final combinando los campos deterministas + el `actions`/`reasoning` del LLM, y añade `source_context` con la copia de `delay_prediction`/campos relevantes de `analytics_result`.

### `prompts/disruption_prompt.py`
- Se elimina `DISRUPTION_REACT_SYSTEM_PROMPT` (ya no hay bucle ReAct).
- `DISRUPTION_STRUCTURED_SYSTEM_PROMPT` se reduce a instruir la redacción de `actions` y `reasoning` a partir de datos ya calculados (severity, alternativa elegida, coste, criterio activo), no a calcular nada.

### `backend/app/schemas.py`
- `QueryRequest.optimization_criterion: str | None = None`.

### `backend/app/services/query_service.py`, `graph/supervisor.py`, `backend/app/api/routes/query.py`
- Se añade el parámetro `optimization_criterion` en la cadena `execute_query` → `QueryService.execute` → `run_query` → `initial_state`.

### `backend/app/cli.py`
- Sin cambios funcionales obligatorios (usa el valor por defecto de `Settings`); se puede añadir opcionalmente una nota en el banner indicando el criterio activo por defecto.

### `frontend/src/App.jsx`
- Nuevo campo en `initialForm`: `optimization_criterion: 'min_passengers'`.
- Nuevo `<select>` en el formulario con las dos opciones ("Minimizar pasajeros afectados" / "Minimizar coste operativo"), incluido en el body del POST a `/api/query`.

### Tests
- `tests/unit/test_disruption_tools.py`: sin cambios de fondo (las tools no cambian).
- `tests/integration/test_disruption_agent.py`: reescritura significativa — ya no se mockea `bind_tools`, se mockea la llamada única `with_structured_output`; nuevos tests para `_select_best_alternative` (criterio min_passengers vs min_cost eligen candidatos distintos), `_compute_severity`, `_estimate_operational_cost`.
- `tests/unit/test_state.py`: nuevos tests de `DisruptionProposal` ampliado y de `initial_state` con/sin `optimization_criterion`.
- `tests/integration/test_analytical_agent.py`: nuevo test de que `get_cascade_risk_context` se invoca de forma determinista cuando hay `flight_context`, incluso si el LLM no la pidió.
- `tests/integration/test_supervisor.py`: revisar que el flujo completo sigue funcionando con el nuevo campo `optimization_criterion` en el estado.

## 4. Modelo de datos / contratos

```python
# graph/state.py

class AlternativeCandidate(TypedDict):
    airline: str
    scheduled_dep: int
    avg_arr_delay_min: float
    reliability_pct: float
    score: float             # puntuación según el criterio activo
    selected: bool            # True solo para la alternativa elegida


class DisruptionSourceContext(TypedDict, total=False):
    delay_prediction: DelayPrediction
    cascade_risk_context: list[CascadeRiskFlight]
    flight_context: FlightContext


class DisruptionProposal(TypedDict):
    proposal_id: str
    severity: str
    actions: list[str]
    affected_passengers_est: int
    alternative_flights: list[str]
    reasoning: str
    optimization_criterion: str                    # "min_passengers" | "min_cost"
    alternatives_considered: list[AlternativeCandidate]
    estimated_operational_cost: Optional[float]
    source_context: DisruptionSourceContext
```

`Settings.DEFAULT_OPTIMIZATION_CRITERION` y `SGIDAState.optimization_criterion` son `str` con los valores válidos `"min_passengers"` / `"min_cost"` (documentados, no un `Literal` estricto para no acoplar `TypedDict` a validación en tiempo de ejecución — la validación de valor permitido se hace en `initial_state`/`QueryRequest`).

## 5. Plan de pruebas
- Unitarios de `_select_best_alternative`: con los mismos candidatos, `min_passengers` y `min_cost` deben poder elegir alternativas distintas (caso de prueba construido a propósito para que difieran).
- Unitarios de `_compute_severity`: los 4 rangos de minutos + el caso "sin alternativas fiables → critical".
- Unitarios de `_estimate_operational_cost`: monotonía básica (más congestión/más reasignaciones → coste mayor).
- Integración de `disruption_agent`: ya no se mockea `bind_tools`; se mockea `with_structured_output` para `actions`/`reasoning`, y las 3 tools se ejecutan reales contra DuckDB (mismo patrón que en `analytical_agent`).
- Integración de `analytical_agent`: `get_cascade_risk_context` se popula incluso cuando el LLM mockeado no la solicitó explícitamente.
- Validación manual (pospuesta según precedente del evolutivo anterior, a criterio del usuario): probar ambos criterios desde el frontend y comprobar que cambian la alternativa elegida.

## 6. Plan de despliegue / migración
No aplica migración de datos. Cambio de contrato interno (`SGIDAState`, `DisruptionProposal`) y de API (`QueryRequest` gana un campo opcional, retro-compatible). Frontend y backend se despliegan juntos como ya es habitual en este proyecto.

## 7. Estimación de complejidad
- Nº aproximado de tareas: ~20 (config/estado, agente analítico (cambio pequeño), agente de disrupción (reescritura), prompts, plumbing de API/CLI, frontend, tests).
- Áreas de mayor incertidumbre:
  - Calibrar la fórmula de `estimated_operational_cost` y la puntuación de `_select_best_alternative` para que produzcan resultados razonables en la práctica (ambas son heurísticas nuevas, sin precedente en el proyecto).
  - Si el criterio `min_cost` con datos reales del dataset llega a producir selecciones claramente distintas de `min_passengers` en casos de prueba reales (puede necesitar ajuste de pesos tras probar con datos reales).