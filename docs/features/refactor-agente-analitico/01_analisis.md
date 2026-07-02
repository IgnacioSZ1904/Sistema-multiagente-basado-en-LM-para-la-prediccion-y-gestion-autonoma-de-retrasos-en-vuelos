# Análisis: refactor-agente-analitico

## 1. Petición original
> "quiero refactorizar el agente analitico, para ello observaremos el archivo data ingestion.py, y quiero refactorizar las tools, el proompt y la creacion de agente para que cumpla lo siguiente: encargado de procesar los datos históricos de vuelos para identificar patrones de retraso, detectar rutas, aeropuertos y franjas horarias problemáticas, la idea es que este agente no devuelva una respuesta en lenguaje natural, sino una respuesta en json con la informacion obtenida de mayor relevancia. Posteriormente ese json sera enviado a un agente de disrupcion que tendra que realizar el analisis de la informacion y tratar de predecir e intentar gestionar las posibles disrupciones o a un agente de comunicacion que devuelva los datos en lenguaje natural"

## 2. Objetivo
Redefinir el Agente Analítico como un agente **puramente exploratorio**: consulta el histórico de vuelos (vía DuckDB, ver `data/data_ingestion.py`) para detectar patrones de retraso — rutas, aeropuertos y franjas horarias problemáticas — y devuelve **exclusivamente un JSON estructurado** con los hallazgos más relevantes, sin narrativa en lenguaje natural. Ese JSON pasa a ser la entrada del Agente de Disrupción (que razona sobre predicción y gestión de disrupciones) o del Agente de Comunicación (que lo traduce a lenguaje natural para el operador).

## 3. Estado actual del proyecto

### Módulos / ficheros relevantes existentes
- `data/data_ingestion.py`: script de carga única del parquet BTS a `data/analytical_db.duckdb` (tabla `flights`). No requiere cambios funcionales, pero define el esquema de columnas disponible que acota qué puede calcular el agente.
- `agents/analytical_agent.py`: agente de dos fases (ReAct manual con `bind_tools` → síntesis con `with_structured_output`). Actualmente soporta **dos modos**: `"prediction"` (retraso de un vuelo concreto, con `predict_flight_delay` y `get_cascade_risk_flights`) y `"exploratory"` (patrones generales). Siempre añade un campo `narrative_summary` en lenguaje natural al estado (`messages`).
- `tools/analytical_tools.py`: 8 tools LangChain sobre DuckDB. 6 son exploratorias (`get_top_delay_airports`, `get_top_delay_airlines`, `get_top_delay_routes`, `get_delay_by_month`, `get_delay_by_hour`, `get_delay_causes_breakdown`) y 2 son predictivas/de vuelo concreto (`predict_flight_delay`, `get_cascade_risk_flights`).
- `prompts/analytical_prompt.py`: dos prompts (`ANALYTICAL_REACT_SYSTEM_PROMPT` y `ANALYTICAL_STRUCTURED_SYSTEM_PROMPT`) que instruyen sobre ambos modos.
- `graph/state.py`: `SGIDAState` ya separa `analytics_result` (exploratorio) de `delay_prediction` (predictivo) como campos independientes; ambos son escritos únicamente por `analytical_agent`. `AnalyticsResult` es un `TypedDict` con campos ad-hoc (`top_delay_airports`, `top_delay_airlines`, etc.) pero el agente en la práctica solo rellena `summary_stats` con un dict libre (`output.exploratory_summary`), sin tipar los sub-campos reales.
- `agents/disruption_agent.py`: consume **solo** `delay_prediction` y `flight_context` del estado (no lee `analytics_result`). Tiene sus propias tools de solo lectura (`find_alternative_flights`, `estimate_affected_passengers`, `get_airport_ground_activity`) orientadas a proponer acciones, pero **no** tiene herramientas de predicción de retraso propias — hoy esa responsabilidad vive en `analytical_agent` vía `predict_flight_delay`.
- `agents/communication_agent.py`: vuelca `analytics_result`, `delay_prediction` y `disruption_proposal` (todos como `dict`/`str` crudos) en el prompt y genera texto libre. No depende de que `analytical_agent` emita narrativa — ya sabe trabajar con datos estructurados.
- `graph/supervisor.py`: decide el routing entre agentes; no depende del formato interno de `analytics_result`/`delay_prediction`, solo comprueba si están presentes (`is not None`).
- `config/settings.py`: expone `DELAY_THRESHOLD_MINUTES`, `DB_PATH`, `get_llm()`, `ollama_available()`.

### Dependencias afectadas
- `graph/supervisor.py` (`_build_state_summary`) referencia `analytics_result` y `delay_prediction` por separado — hay que decidir si esta distinción se mantiene.
- `agents/communication_agent.py` (`_build_context_block`) ya consume ambos campos como datos crudos; compatible sin cambios si se mantiene la forma de `SGIDAState`.
- `agents/disruption_agent.py` no consume `analytics_result` hoy; si el nuevo JSON del analítico debe alimentar al agente de disrupción (como pide la petición), hay que añadir esa lectura.

### Configuración actual relacionada
- `Settings.DELAY_THRESHOLD_MINUTES` (por defecto 15 min) se usa dentro de las queries SQL de `analytical_tools.py` para calcular `pct_delayed` / `pct_disrupted`.
- `Settings.DB_PATH` apunta a `data/analytical_db.duckdb`, generado por `data/data_ingestion.py`.

### Tests existentes que cubren el área
- `tests/unit/test_analytical_tools.py`
- `tests/integration/test_analytical_agent.py`
- `tests/integration/test_disruption_agent.py` (indirectamente, por el contrato de `delay_prediction`)
- `tests/integration/test_supervisor.py`
- `tests/unit/test_state.py`

## 4. Alcance

### Dentro de alcance
- Refactor de `tools/analytical_tools.py`: revisar/ajustar las tools exploratorias para que sus salidas encajen limpiamente en el JSON final (rutas, aeropuertos, franjas horarias, causas).
- Refactor de `prompts/analytical_prompt.py`: nuevo prompt (o prompts) que instruya al agente a **solo explorar y estructurar**, eliminando cualquier instrucción de redactar texto narrativo.
- Refactor de `agents/analytical_agent.py`: nuevo esquema de salida estructurada (Pydantic) sin `narrative_summary` ni modo `"prediction"`; el nodo del grafo escribe únicamente el JSON de hallazgos en el estado.
- Ajuste de `graph/state.py` en la parte de `AnalyticsResult` / `SGIDAState` si el nuevo contrato de datos lo requiere (ver preguntas abiertas).
- Actualizar `tests/unit/test_analytical_tools.py` y `tests/integration/test_analytical_agent.py` para el nuevo contrato.
- Actualizar `agents/disruption_agent.py` lo mínimo necesario para que reciba el JSON del analítico como contexto de entrada (según se resuelva la pregunta abierta §6.1).

### Fuera de alcance
- Cambios en `data/data_ingestion.py` (solo se usa como referencia de esquema, no se modifica su lógica de carga).
- Migración de `predict_flight_delay` / `get_cascade_risk_flights` a `tools/disruption_tools.py` y la lógica de predicción dentro de `disruption_agent.py` en profundidad — se decide el destino en este análisis, pero la implementación completa de "predecir y gestionar disrupciones" en el agente de disrupción, si aplica, se detallará en `02_planificacion.md` una vez resuelta la pregunta abierta.
- Cambios en `communication_agent.py` más allá de lo estrictamente necesario para seguir leyendo el nuevo formato de `analytics_result`.
- Cambios en `graph/supervisor.py` (routing) salvo ajustes triviales de nombres de campo.
- Frontend / API (`backend/app/...`).

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Mover la predicción (`predict_flight_delay`, `get_cascade_risk_flights`) al agente de disrupción rompe tests/integración existentes que asumen `delay_prediction` viene del analítico | Media | Alto | Definir el contrato de datos en `02_planificacion.md` antes de tocar código; actualizar tests en el mismo bloque de tareas que el cambio de origen |
| El LLM local (Ollama) no respeta el esquema JSON estrictamente y cuela texto libre en algún campo | Media | Medio | Mantener `with_structured_output` con Pydantic (patrón ya validado en el proyecto) y tests de contrato sobre el shape del JSON |
| `disruption_agent` y `communication_agent` dependen implícitamente de la forma actual de `analytics_result`/`delay_prediction`; un cambio de esquema sin actualizarlos rompe el flujo end-to-end | Alta si no se coordina | Alto | Incluir en `03_tareas_pendientes.md` un bloque específico de "consumidores downstream" con checks explícitos |
| Test suite actual (`tests/integration/test_disruption_agent.py`) puede fallar si cambia el origen de `delay_prediction` | Media | Medio | Ejecutar suite completa tras cada tarea del bloque de implementación, no solo al final |

## 6. Preguntas abiertas — RESUELTAS (2026-07-02)

- [x] **6.1 — ¿Se traslada la responsabilidad de predicción al agente de disrupción?** La petición dice que el JSON del analítico "será enviado a un agente de disrupción que tendrá que realizar el análisis de la información y tratar de **predecir** e intentar gestionar las posibles disrupciones". Hoy la predicción (`predict_flight_delay`, `is_disruption`, `confidence`, `main_cause`, `get_cascade_risk_flights`) vive en `analytical_agent`/`analytical_tools.py`. ¿Confirmas que:
  - (a) El agente analítico deja de tener modo `"prediction"` y solo hace análisis exploratorio de patrones (rutas/aeropuertos/franjas problemáticas), y
  - (b) `predict_flight_delay` y `get_cascade_risk_flights` se trasladan a `tools/disruption_tools.py`, pasando a ser responsabilidad del agente de disrupción (que además consumirá el JSON exploratorio del analítico como contexto adicional)?
  Lo Confirmo(siendo necesario que el agente analitico le aporte toda la informacion necesaria al de disrupcion, que no accedera a la base de datos)

  **[CORREGIDO 2026-07-02 — el usuario se retractó parcialmente, ver `04_lecciones_aprendidas.md`]:** `predict_flight_delay` y `get_cascade_risk_flights` se quedan en `tools/analytical_tools.py` (renombradas, sin campos interpretativos: solo hechos históricos). El **agente analítico conserva la responsabilidad de la predicción** (`is_disruption`, `confidence`, `main_cause`, `expected_dep_delay_min`, `expected_arr_delay_min`) — no se traslada al agente de disrupción. La diferencia respecto al diseño original es que esos campos se calculan de forma **determinista en código** (umbral configurado, heurística de `sample_size`, causa dominante ya calculada por SQL) en vez de con una segunda llamada LLM — así se mantiene JSON puro, sin narrativa, y sin coste extra de latencia. El agente de disrupción vuelve a consumir `delay_prediction` (ya calculado) para razonar sobre cómo **gestionar** la disrupción (severidad, acciones, vuelos alternativos), no para calcular la predicción él mismo; también recibe `analytics_result` como contexto adicional. Todo el intercambio entre agentes se formaliza como bloques JSON explícitos en los prompts (estilo "MCP": payloads estructurados en vez de interpolar `repr()` de dicts de Python), para una comunicación entre agentes más efectiva y menos ambigua.

  Los 3 tools ya existentes de `disruption_tools.py` (`find_alternative_flights`, `estimate_affected_passengers`, `get_airport_ground_activity`) siguen fuera de alcance de este evolutivo (propuesta de acciones, no predicción/patrones).

- [x] **6.2 — Forma exacta del JSON de salida.** ¿El JSON debe ser una estructura fija con campos tipados (p.ej. `top_delay_routes`, `top_delay_airports`, `delay_by_hour`, `delay_causes_pct`, tal como ya sugiere `AnalyticsResult` en `graph/state.py`), o un formato más libre tipo `{"findings": [...]}` con hallazgos priorizados por el LLM? La primera opción es más fácil de consumir para `disruption_agent`/`communication_agent`; la segunda da más flexibilidad al LLM para resumir lo más relevante de la consulta concreta.
Primera opcion, pero con algunos campos opcionales que se rellenen o no segun el tipo de consulta

- [x] **6.3 — ¿Se limita el número de tools que puede llamar el agente en una consulta, o se cambia el bucle ReAct actual?** La petición menciona "refactorizar las tools, el prompt y la creación de agente" — ¿mantenemos el patrón de dos fases (ReAct manual + síntesis con `with_structured_output`), que ya está documentado y probado en el proyecto, o se busca un patrón distinto?
Quiero el patron mas optimo, para evitar largas esperas al agente sin comprometer la funcionalidad

- [x] **6.4 — ¿El campo `messages`/canal conversacional sigue recibiendo algo del agente analítico?** Si se elimina `narrative_summary`, ¿el nodo deja de añadir `AIMessage` al estado, o añade el JSON serializado como mensaje (por trazabilidad en modo debug) sin que cuente como "respuesta en lenguaje natural" de cara al operador?
si no consume mucho o no retrasa mucho la ejecucion puede dejar un pequeño mensaje para trazabilidad

## 7. Criterios de aceptación
- [ ] `analytical_agent` devuelve siempre una estructura JSON validada (Pydantic) con los hallazgos de patrones de retraso; ningún campo de la salida es texto narrativo libre dirigido al operador.
- [ ] El JSON incluye, como mínimo, rutas problemáticas, aeropuertos problemáticos y franjas horarias problemáticas (con sus métricas: retraso medio, % de disrupción, volumen de vuelos).
- [ ] El nuevo contrato de `analytics_result` en `graph/state.py` está tipado explícitamente (no un `dict` libre sin estructura).
- [ ] `disruption_agent` y/o `communication_agent` consumen el nuevo JSON sin necesitar parsear texto libre.
- [ ] Los tests unitarios de `tools/analytical_tools.py` y de integración de `analytical_agent` pasan con el nuevo contrato.
- [ ] La suite completa de tests (`pytest`) pasa tras el refactor.
- [ ] Resuelta la pregunta 6.1, el alcance de este evolutivo (o de uno derivado) queda reflejado y ejecutado de forma consistente.
