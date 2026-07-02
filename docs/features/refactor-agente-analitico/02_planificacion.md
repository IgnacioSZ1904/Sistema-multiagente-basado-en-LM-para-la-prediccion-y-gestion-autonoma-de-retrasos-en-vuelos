# Planificación: refactor-agente-analitico

## 1. Enfoque técnico

> **[CORREGIDO 2026-07-02]** Revisión tras redirección del usuario: el agente analítico **conserva** la responsabilidad de la predicción (no se traslada a `disruption_agent`). Ver `04_lecciones_aprendidas.md` para el detalle de la corrección. El resto de este documento refleja ya el diseño corregido.

El agente analítico pasa de un patrón "ReAct + síntesis LLM con `with_structured_output`" a un patrón **"ReAct + ensamblaje determinista"**. La fase de síntesis actual reescribe con el LLM datos que las tools ya devuelven en el shape exacto necesario (JSON con las columnas ya nombradas); eso es una llamada al LLM redundante que añade latencia y riesgo de que el modelo transcriba mal números. El agente **no redacta narrativa** (eso no cambia), pero sí sigue **calculando la predicción** (`is_disruption`, `confidence`, `main_cause`, `expected_dep_delay_min`, `expected_arr_delay_min`) — la diferencia clave es que ese cálculo pasa a ser **determinista en código Python**, no una interpretación del LLM: `is_disruption` es una comparación contra `Settings.DELAY_THRESHOLD_MINUTES`, `confidence` es una heurística basada en `sample_size` (mismas reglas que hoy vivían en `ANALYTICAL_STRUCTURED_SYSTEM_PROMPT`, trasladadas a código), y `main_cause` ya lo calcula el propio SQL de la tool (`dominant_delay_cause`). Esto elimina la segunda llamada LLM por completo (ni para exploratorio ni para predicción), respondiendo a 6.3 (patrón más rápido) y 6.4 (trazabilidad barata).

Las dos tools que hoy "predicen" (`predict_flight_delay`, `get_cascade_risk_flights`) se conservan en `tools/analytical_tools.py`, renombradas, devolviendo estadísticas históricas puramente factuales; el código del nodo (no el LLM) deriva de ahí los campos interpretados de `delay_prediction`.

`disruption_agent` **no** calcula la predicción — la recibe ya calculada (`delay_prediction`) del agente analítico, junto con `analytics_result` (contexto exploratorio, p.ej. `cascade_risk_context`) como información adicional. Su trabajo sigue siendo razonar sobre cómo **gestionar** la disrupción: severidad, acciones concretas, vuelos alternativos, pasajeros afectados. No consulta la base de datos para nada de esto (principio confirmado por el usuario), toda la información le llega ya elaborada desde el analítico.

**Comunicación "estilo MCP" entre agentes:** para que el intercambio de información entre agentes sea explícito y fácil de razonar (y no dependa de que el LLM interprete la `repr()` de un dict de Python pegada en el prompt), los contextos que se pasan a `disruption_agent` y `communication_agent` se serializan con `json.dumps(..., ensure_ascii=False)` como bloques JSON etiquetados dentro del prompt, en vez de f-strings con el dict crudo. Esto mejora la fiabilidad de lectura del LLM consumidor y dota al sistema de un contrato de datos entre agentes más parecido a payloads de herramientas/recursos MCP.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| Fase 2 del agente analítico pasa de LLM (`with_structured_output`) a ensamblaje determinista en código, **incluyendo el cálculo de `delay_prediction`** | (a) Mantener LLM de síntesis pero sin narrativa; (b) fusionar fase 1 y 2 en una sola llamada `bind_tools` + `with_structured_output`; (c) trasladar el cálculo de predicción a `disruption_agent` (descartada tras redirección del usuario) | (a) sigue pagando una llamada LLM completa para reformatear datos que ya están bien formados → más lento y con riesgo de transcripción. (b) ya está documentado como poco fiable con Ollama. El ensamblaje determinista es más rápido, 100% fiel a los datos, sin alucinación numérica, y permite que el analítico siga "prediciendo" sin pagar una segunda llamada LLM |
| `predict_flight_delay`/`get_cascade_risk_flights` se quedan en `tools/analytical_tools.py`, renombradas y sin campos interpretativos (los campos interpretados se derivan después, en código, no en la tool) | Moverlas a `disruption_tools.py`; mantenerlas devolviendo ya `is_disruption`/`confidence`/`main_cause` calculado en SQL | El agente de disrupción no accede a la base de datos. Separar "hechos" (tool) de "predicción derivada" (código del nodo) mantiene las tools reutilizables y testeables de forma aislada |
| `analytical_agent` conserva la escritura de `delay_prediction` en el estado; `disruption_agent` **consume** `delay_prediction` + `analytics_result`, no los calcula | Que `disruption_agent` calculara `is_disruption`/`confidence`/`main_cause` (descartada) | El usuario se retractó explícitamente: quiere que el analítico siga prediciendo. `disruption_agent` se centra en "gestionar" (severidad, acciones, alternativas), no en "predecir" |
| Los 3 tools existentes de `disruption_tools.py` (`find_alternative_flights`, `estimate_affected_passengers`, `get_airport_ground_activity`), que sí acceden a BD, se dejan sin tocar en este evolutivo | Retirar también su acceso a BD | Fuera del alcance declarado en `01_analisis.md` (propuesta de acciones, no predicción/patrones); se propone como evolutivo futuro `refactor-agente-disrupcion` si se quiere extender el principio |
| El JSON de salida (`AnalyticsResult`) usa una única estructura fija con **todos los campos opcionales** (`total=False`), en vez de variantes por tipo de consulta | Dos esquemas separados (`ExploratoryResult` / `FlightSpecificResult`) | Coincide con la respuesta 6.2 del usuario; simplifica el contrato para los consumidores sin perder expresividad |
| Se reduce `_MAX_TOOL_CALLS` de 5 a 3 turnos ReAct y el prompt anima explícitamente a pedir varias tools en el mismo turno cuando la consulta lo requiera | Mantener 5 turnos; forzar una tool por turno | Con tools más enfocadas y sin segunda llamada LLM, 3 turnos son suficientes en la práctica; permitir varias `tool_calls` por turno (ya soportado por el bucle actual) reduce round-trips al LLM, el principal coste de latencia con Ollama local |
| Los contextos pasados entre agentes (`disruption_agent`, `communication_agent`) se serializan como bloques JSON explícitos (`json.dumps`) en vez de interpolar el `repr()` de un dict de Python en el prompt | Mantener la interpolación actual (`f"...: {state['analytics_result']}"`) | Petición explícita del usuario de "asimilar este sistema a MCP" para comunicación entre agentes más efectiva; un bloque JSON bien formado es más fácil de parsear/citar por el LLM consumidor que un `repr()` de Python (que no es JSON válido, p.ej. usa comillas simples) |

## 3. Cambios por módulo

### `tools/analytical_tools.py`
- Se mantienen sin cambios funcionales: `get_top_delay_airports`, `get_top_delay_airlines`, `get_top_delay_routes`, `get_delay_by_month`, `get_delay_by_hour`, `get_delay_causes_breakdown` (ya devuelven el shape necesario).
- `predict_flight_delay` → renombrada a `get_flight_historical_stats`. Se elimina cualquier lenguaje de "predicción" del docstring; los campos de salida pasan a ser: `airline`, `origin`, `destination`, `month`, `scheduled_dep`, `avg_dep_delay_min`, `avg_arr_delay_min`, `pct_over_threshold`, `sample_size`, `dominant_delay_cause` (mismo cálculo SQL que hoy calcula `main_cause`, pero se documenta como "causa histórica dominante", un hecho, no una predicción).
- `get_cascade_risk_flights` → renombrada a `get_cascade_risk_context`. Mismo SQL; docstring ajustado para dejar claro que son datos descriptivos (vuelos con exposición histórica a retraso de aeronave tardía), no un cálculo de riesgo interpretado por el LLM.
- Se actualiza la lista `ANALYTICAL_TOOLS` con los nuevos nombres.

### `prompts/analytical_prompt.py`
- Se elimina `ANALYTICAL_STRUCTURED_SYSTEM_PROMPT` (ya no hay fase de síntesis LLM).
- `ANALYTICAL_REACT_SYSTEM_PROMPT` se reescribe: nombres de tools actualizados, instrucción explícita de "cuando la consulta lo requiera, solicita varias herramientas en el mismo turno en vez de una por una", prohibición explícita de generar texto narrativo o conclusiones (el agente solo reúne datos), y aclaración de que `get_flight_historical_stats`/`get_cascade_risk_context` solo se usan cuando hay `flight_context`.

### `agents/analytical_agent.py`
- Se elimina `AnalyticalOutput` (Pydantic) y `_synthesize()` (la llamada LLM de síntesis desaparece por completo).
- Se elimina el campo `narrative_summary`; se conserva la distinción entre datos exploratorios y datos de vuelo concreto, pero como dos campos del mismo ensamblaje determinista, no como `response_mode` narrado por el LLM.
- `_run_react_loop` se ajusta para devolver también la lista de `(tool_name, tool_result_json)` invocados (no solo los mensajes), necesaria para el ensamblaje determinista.
- Nueva función `_assemble_analytics_result(tool_results) -> AnalyticsResult`: por cada resultado, `json.loads()` del contenido y asignación al campo correspondiente según una tabla `TOOL_NAME_TO_FIELD`. Si una tool fue llamada más de una vez, gana la última invocación (limitación documentada).
- Nueva función `_derive_delay_prediction(flight_historical_stats) -> Optional[DelayPrediction]`: si `get_flight_historical_stats` fue invocada y devolvió `sample_size > 0`, calcula de forma determinista:
  - `is_disruption = avg_arr_delay_min > Settings.DELAY_THRESHOLD_MINUTES`
  - `confidence`: heurística por tramos de `sample_size` (`< 30` → hasta 0.5; `30–200` → escalado lineal 0.5–0.8; `> 200` → 0.8+), misma regla que antes vivía en `ANALYTICAL_STRUCTURED_SYSTEM_PROMPT`, ahora en código.
  - `main_cause = dominant_delay_cause` (ya calculado por SQL en la tool).
  - `expected_dep_delay_min` / `expected_arr_delay_min` = los promedios ya devueltos por la tool.
  Si no hay `flight_context`/no se llamó a la tool, `delay_prediction` queda `None`.
- `analytical_agent(state)`: ejecuta fase 1, ensambla `analytics_result` y (si aplica) `delay_prediction`, y añade a `messages` un `AIMessage` construido en código (no por el LLM) del tipo `"[analytical_agent] tools consultadas: get_top_delay_routes, get_flight_historical_stats"` para trazabilidad en modo debug.
- Modo degradado (Ollama no disponible): devuelve `AnalyticsResult` vacío con `tools_used=[]` en vez de un dict libre `{"mode": "degraded"}`, manteniendo el contrato tipado; `delay_prediction` queda `None`.

### `graph/state.py`
- Se sustituye el `AnalyticsResult` actual (con `summary_stats: dict[str, Any]` como cajón de sastre) por sub-`TypedDict`s tipados: `RouteStat`, `AirportStat`, `AirlineStat`, `HourStat`, `MonthStat`, `CauseStat`, `FlightHistoricalStats`, `CascadeRiskFlight`, y un `AnalyticsResult(TypedDict, total=False)` que los agrupa como campos opcionales, más `tools_used: list[str]`.
- `delay_prediction` (`DelayPrediction`) **no cambia de forma ni de propietario**: lo sigue escribiendo `analytical_agent`, como hoy. Se actualiza únicamente el comentario para aclarar que se deriva de forma determinista de `flight_historical_stats`, no de una interpretación LLM.

### `agents/disruption_agent.py`
- Cambio mínimo: `_run_react_loop` y `_synthesize` pasan a recibir tanto `delay_prediction` como `analytics_result` (contexto exploratorio adicional, p.ej. `cascade_risk_context`) — hoy solo recibían `delay_prediction`. `DisruptionOutput` **no cambia** (sigue sin campos de predicción; se mantiene enfocado en `severity`/`actions`/`affected_passengers_est`/`alternative_flights`/`reasoning`).
- El nodo `disruption_agent(state)` sigue escribiendo únicamente `disruption_proposal`, como hoy.
- Los contextos (`delay_prediction`, `analytics_result`) se serializan con `json.dumps(..., ensure_ascii=False)` en bloques etiquetados del prompt en vez de interpolar el dict de Python directamente (mejora "estilo MCP").

### `prompts/disruption_prompt.py`
- `DISRUPTION_REACT_SYSTEM_PROMPT`: se actualiza la descripción del contexto de entrada para mencionar que ahora también puede recibir `analytics_result` (contexto exploratorio) además de `delay_prediction`, ambos como bloques JSON.
- `DISRUPTION_STRUCTURED_SYSTEM_PROMPT`: sin cambios de fondo (sigue centrado en `severity`/`actions`/`reasoning`); solo se ajusta la descripción del formato de entrada (JSON en vez de texto libre).

### `agents/communication_agent.py`
- `_build_context_block`: los campos `analytics_result`, `delay_prediction`, `disruption_proposal` se serializan con `json.dumps(...)` en vez de `f"...: {state['analytics_result']}"` (mismo motivo "estilo MCP"). Cambio pequeño, sin tocar el resto de la lógica del agente.

### Tests
- `tests/unit/test_analytical_tools.py`: renombrar tests de `predict_flight_delay`/`get_cascade_risk_flights`, ajustar campos esperados (`pct_over_threshold`, `dominant_delay_cause`).
- `tests/integration/test_analytical_agent.py`: reescribir para el nuevo contrato (mock de `get_llm().bind_tools(...)` con varias `tool_calls` en un turno; assert de que NO se invoca `with_structured_output`; assert del `AnalyticsResult` ensamblado; caso con `flight_context` → assert de `delay_prediction` derivado correctamente según la heurística de `confidence`).
- `tests/integration/test_disruption_agent.py`: ajustar mocks para pasar también `analytics_result`; la salida sigue siendo solo `disruption_proposal` (sin cambios de contrato de salida).
- `tests/unit/test_state.py`: ajustar a la nueva forma de `AnalyticsResult`; `delay_prediction` sin cambios de forma.
- `tests/integration/test_supervisor.py`: revisar que no dependa de la forma interna de `analytics_result`/`delay_prediction` (hoy solo comprueba presencia/ausencia) — sin cambios esperados, pero se ejecuta para confirmarlo.

## 4. Modelo de datos / contratos

```python
# graph/state.py

class RouteStat(TypedDict):
    origin: str
    destination: str
    avg_arr_delay_min: float
    total_flights: int

class AirportStat(TypedDict):
    origin: str
    avg_dep_delay_min: float
    total_flights: int
    pct_delayed: float

class AirlineStat(TypedDict):
    airline: str
    avg_arr_delay_min: float
    total_flights: int
    pct_delayed: float

class HourStat(TypedDict):
    hour: int
    avg_dep_delay_min: float
    total_flights: int

class MonthStat(TypedDict):
    month: int
    avg_arr_delay_min: float
    total_flights: int

class CauseStat(TypedDict):
    cause: str            # "carrier" | "weather" | "nas" | "security" | "late_aircraft"
    total_minutes: float
    pct: float

class FlightHistoricalStats(TypedDict):
    airline: str
    origin: str
    destination: str
    month: int
    scheduled_dep: int
    avg_dep_delay_min: Optional[float]
    avg_arr_delay_min: Optional[float]
    pct_over_threshold: Optional[float]
    sample_size: int
    dominant_delay_cause: str

class CascadeRiskFlight(TypedDict):
    destination: str
    airline: str
    scheduled_dep: int
    avg_late_aircraft_delay_min: float
    total_flights: int

class AnalyticsResult(TypedDict, total=False):
    top_delay_routes: list[RouteStat]
    top_delay_airports: list[AirportStat]
    top_delay_airlines: list[AirlineStat]
    delay_by_hour: list[HourStat]
    delay_by_month: list[MonthStat]
    delay_causes_breakdown: list[CauseStat]
    flight_historical_stats: FlightHistoricalStats
    cascade_risk_context: list[CascadeRiskFlight]
    tools_used: list[str]
```

`delay_prediction` conserva exactamente el `TypedDict DelayPrediction` actual (sin cambios de forma), solo cambia quién lo escribe (`disruption_agent` en vez de `analytical_agent`).

## 5. Plan de pruebas

- **Unitarios** (`tests/unit/test_analytical_tools.py`): shape JSON de `get_flight_historical_stats` y `get_cascade_risk_context` tras el renombrado; resto de tools sin regresión.
- **Unitarios** (`tests/unit/test_state.py`): `initial_state()` y forma de `AnalyticsResult` tipado.
- **Integración** (`tests/integration/test_analytical_agent.py`):
  - Caso exploratorio: LLM mockeado solicita 2 tools en el mismo turno → `analytics_result` con ambos campos poblados, `delay_prediction` ausente.
  - Caso con `flight_context`: LLM solicita `get_flight_historical_stats` → `analytics_result.flight_historical_stats` poblado y `delay_prediction` derivado correctamente (`is_disruption` según umbral, `confidence` según los tramos de `sample_size`, `main_cause` = `dominant_delay_cause`).
  - Verificar que no se realiza ninguna llamada `with_structured_output` (mock/spy sobre `get_llm()`) en ningún caso, ni exploratorio ni de predicción.
  - Caso "tool inexistente" / error de tool: comportamiento de fallback igual que hoy.
  - Caso `sample_size == 0` (sin datos históricos): `delay_prediction` es `None` o tiene `confidence=0.0`/`main_cause="unknown"`, no se inventan cifras.
- **Integración** (`tests/integration/test_disruption_agent.py`): se pasa `delay_prediction` (ya calculado, mockeado como vendría del analítico) y `analytics_result` como contexto; la salida estructurada mockeada produce `disruption_proposal` coherente con esa entrada. Se verifica que el prompt recibido por el LLM contiene los bloques JSON serializados (no `repr()` de dict).
- **Validación manual**: lanzar `python main.py` (CLI) con una consulta exploratoria y una de vuelo concreto contra Ollama real, revisar en modo `DEBUG_MODE=true` que el JSON generado es correcto y que el mensaje de trazabilidad es breve.
- Ejecutar la suite completa (`pytest`) al cerrar el bloque de implementación y antes del cierre del evolutivo.

## 6. Plan de despliegue / migración
No aplica migración de datos (no cambia el esquema de `analytical_db.duckdb`, no hay usuarios en producción). El cambio es de código y contrato interno del grafo; se despliega mergeando la rama de este evolutivo tras aprobar la review.

## 7. Estimación de complejidad
- Nº aproximado de tareas: ~16-18 (repartidas en preparación, tools, prompts, agente analítico, estado, ajuste mínimo de agente de disrupción y comunicación, tests, documentación). Menor que la estimación previa porque `disruption_agent` ya no gana un esquema de salida nuevo.
- Áreas de mayor incertidumbre:
  - Si el modelo local (`llama3.1` vía Ollama) realmente solicita varias tools en un mismo turno de forma consistente, o si en la práctica sigue pidiendo una por una (impacto en el objetivo de latencia de 6.3, no en la corrección funcional).
  - Calibrar los tramos exactos de la heurística determinista de `confidence` según `sample_size` para que se comporte de forma razonable en la práctica (valores de referencia tomados del prompt original, pueden necesitar ajuste tras pruebas manuales).
