# Análisis: revision-supervisor

## 1. Petición original
> "como ultimo feature antes de empezar a hacer pruebas manuales quiero que revisemos el supervisor para ver que cumplimos con todo lo anterior y que es coherente con nuestros objetivos, quizas refactorizando el agente y su prompt para asegurar un correcto y optimo funcionamiento del sistema"

## 2. Objetivo
Auditar `graph/supervisor.py`, `graph/router.py` y `prompts/supervisor_prompt.py`, y su coherencia con los tres agentes ya refactorizados, antes de empezar las pruebas manuales. Esta auditoría ha encontrado **dos hallazgos de fondo** que van más allá del supervisor en sí — uno de ellos, si no se corrige, haría que gran parte de lo construido en los tres evolutivos anteriores no se ejercite nunca en el sistema real (solo en tests, donde los datos se inyectan manualmente). Se documentan aquí para decidir juntos el alcance de la corrección.

## 3. Estado actual del proyecto — Hallazgos

### 🔴 Hallazgo A (crítico): `flight_context` nunca se rellena en el sistema real

`graph/state.py` define `flight_context` como el "vuelo concreto extraído de la consulta", y tanto `analytical_agent` (`_ensure_cascade_risk_context`) como `disruption_agent` (`_gather_disruption_data`) **dependen de que ese campo venga relleno** para funcionar:

- `analytical_agent._ensure_cascade_risk_context(analytics_result, flight_context)`: si `flight_context` es falsy, hace `return` inmediato — nunca fuerza `get_cascade_risk_context`.
- `disruption_agent._gather_disruption_data(flight_context)`: sin `origin`/`destination`/`airline`/`month`/`scheduled_dep`, las 3 tools no se invocan (los `if` guardan cada llamada) — el agente produce una propuesta sin alternativas, sin estimación de pasajeros y sin actividad de aeropuerto.

**El problema:** he revisado todo el código de producción (`grep` de `flight_context =` fuera de tests) y **ningún componente escribe nunca ese campo**. `initial_state()` siempre lo inicializa a `None`, y no existe ningún paso de NLU/extracción que lo derive de `user_query`. El propio banner de la CLI (`backend/app/cli.py`) invita a escribir consultas como *"Predice el retraso del vuelo AA en la ruta de Chicago, IL a Denver, CO en marzo a las 14:00"*, dando a entender que el sistema debería reconocer un vuelo concreto — pero nada lo construye como `FlightContext` estructurado.

Lo que SÍ ocurre hoy: el LLM del agente analítico recibe el texto crudo de `user_query` en su prompt y **puede** (y de hecho así está pensado en `ANALYTICAL_REACT_SYSTEM_PROMPT`) invocar `get_flight_historical_stats(airline=..., origin=..., destination=..., month=..., scheduled_dep=...)` extrayendo esos parámetros directamente del texto, sin depender de `flight_context`. Es decir: **la predicción de un vuelo concreto SÍ funciona** (vía extracción implícita del LLM al decidir qué tool llamar), pero el resultado nunca se propaga como `flight_context` estructurado al resto del estado — por lo que todo lo que depende de `flight_context` (cascade risk determinista, las 3 tools de disrupción, `flight_reference` en las notificaciones) queda inerte en producción.

**Por qué no se detectó en tests:** todos los tests de `disruption_agent` y de `_ensure_cascade_risk_context` usan `sample_flight_context` (fixture manual) o construyen el estado a mano — nunca pasan por la ruta real "texto libre → `flight_context`", que es precisamente la que no existe.

**Corrección propuesta:** dado que el agente analítico ya conoce los argumentos exactos (`airline`, `origin`, `destination`, `month`, `scheduled_dep`) cuando invoca `get_flight_historical_stats` — porque el propio LLM se los pasó como argumentos de la tool call —, se puede derivar `flight_context` de forma **determinista y sin ninguna llamada LLM adicional**: `analytical_agent` captura esos argumentos (hoy se descartan) y los escribe de vuelta en el estado como `flight_context` tras ensamblar `analytics_result`. Esto también requiere ajustar `get_cascade_risk_context` (hoy pide `flight_date: str` solo para extraer el mes) para aceptar `month: int` directamente, ya que `get_flight_historical_stats` no produce una fecha completa (día/año), solo mes.

### 🟡 Hallazgo B (simplificación importante): la llamada LLM del supervisor es redundante

Repasando `graph/supervisor.py` + `prompts/supervisor_prompt.py`:

- El supervisor solo consulta al LLM en la **primera** iteración de cada consulta (`if state["iteration"] == 0`). En todas las iteraciones siguientes, el routing es 100% determinista vía `graph/router.py::_deterministic_fallback`.
- En la primera iteración, `initial_state()` garantiza que `analytics_result` y `delay_prediction` están siempre vacíos. La regla 3 del propio prompt del supervisor ("si no hay `analytics_result` ni `delay_prediction`, ve a `analytical_agent`") es **la única regla que puede aplicar** en ese momento — es imposible que a la primera iteración ya exista `disruption_proposal` o `final_response`. Por tanto, **la decisión correcta en la primera iteración es siempre "analytical_agent"**, sea cual sea la consulta.
- Esto significa que la llamada LLM de routing (`get_llm().with_structured_output(RoutingDecision)`) nunca aporta una decisión distinta de la que ya daría `_deterministic_fallback(state)` — solo añade latencia (una llamada LLM completa) y una fuente de fallo más (de ahí el `try/except` que ya existe para degradarla).

Esto es coherente con el patrón ya aplicado a los otros tres agentes en los evolutivos anteriores (sustituir juicio de LLM por código determinista cuando el LLM no aporta valor real). Aquí el caso es incluso más claro: la regla es 100% determinista **por construcción del propio grafo**, no una heurística.

**Corrección propuesta:** eliminar la llamada LLM del supervisor por completo — `supervisor()` pasa a ser un nodo puramente determinista que delega en la misma lógica de `graph/router.py`. Se elimina `RoutingDecision`, `SUPERVISOR_SYSTEM_PROMPT` y la dependencia de `get_llm()` en este módulo. El grafo se vuelve más rápido (un salto menos de LLM en cada consulta) y con un punto de fallo menos.

### Hallazgos menores
- `prompts/supervisor_prompt.py` tiene una cabecera de docstring desincronizada: dice `prompts/orchestrator_prompt.py`, un nombre de fichero antiguo. Si se elimina el prompt (Hallazgo B), esto desaparece solo; si se conserva, habría que corregirlo igualmente.
- `graph/supervisor.py::_build_state_summary` solo se usa para construir el mensaje al LLM de routing — si se adopta el Hallazgo B, queda sin uso y se elimina.

## 4. Alcance

### Dentro de alcance
- **Hallazgo A**: `analytical_agent` deriva y escribe `flight_context` de forma determinista a partir de los argumentos de `get_flight_historical_stats`. Ajuste de `get_cascade_risk_context` (tools/analytical_tools.py) para aceptar `month: int` en vez de `flight_date: str`. Actualización de `graph/state.py` (comentario de propiedad de `flight_context`).
- **Hallazgo B**: simplificar `supervisor()` a un nodo determinista, eliminando la llamada LLM, `RoutingDecision` y `SUPERVISOR_SYSTEM_PROMPT`.
- Actualización de tests afectados por ambos cambios.

### Fuera de alcance
- Cambios en la topología del grafo (nodos/aristas) — se mantiene igual.
- Cualquier extracción de `flight_context` más allá de lo que ya infiere el LLM del agente analítico al elegir argumentos de tool (no se añade un parser NLU adicional ni reglas regex).
- Validación manual (según lo acordado, se hace después de este evolutivo, no como parte de él).

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Eliminar la llamada LLM del supervisor podría sorprender si en el futuro se quiere que el supervisor tome decisiones más matizadas (p. ej. detectar consultas fuera de alcance/chit-chat) | Baja ahora, media a futuro | Bajo | Documentar la decisión y su razonamiento (regla 100% determinista hoy); si en el futuro se necesita matiz, se reintroduce el LLM en ese momento con una razón concreta |
| Cambiar la firma de `get_cascade_risk_context` (`flight_date` → `month`) toca una tool ya cerrada en `refactor-agente-analitico` | Baja | Bajo | Cambio pequeño y aislado; se actualizan los tests correspondientes en el mismo bloque |
| Derivar `flight_context` de los argumentos de `get_flight_historical_stats` asume que esos argumentos son fiables (el LLM pudo alucinar una ciudad inexistente) | Media | Bajo | Ya es una limitación existente (las tools ya toleran combinaciones sin datos, devolviendo `sample_size=0`); no se introduce riesgo nuevo |

## 6. Preguntas abiertas

- [ ] **6.1 — ¿Confirmas eliminar por completo la llamada LLM del supervisor** (Hallazgo B), dejándolo 100% determinista, dado que hoy nunca puede decidir algo distinto de lo que ya decide el fallback determinista? Alternativa: dejarlo como está (LLM redundante pero "inofensivo" salvo por la latencia extra) si prefieres conservar el patrón por si se amplía la lógica de routing más adelante.
confirmo
- [ ] **6.2 — ¿Confirmas la corrección del Hallazgo A** (derivar `flight_context` de forma determinista en `analytical_agent` + ajustar `get_cascade_risk_context` a `month: int`)? Es la corrección que hace que el resto de lo construido (cascade risk determinista, tools de disrupción, `flight_reference` en notificaciones) se ejercite de verdad en el sistema real, no solo en tests.
confirmo tambien

## 7. Criterios de aceptación
- [ ] Una consulta en lenguaje natural sobre un vuelo concreto (sin fixtures, extremo a extremo) deja `flight_context` relleno en el estado tras `analytical_agent`.
- [ ] `disruption_agent`, en ese mismo caso, recibe datos reales de `find_alternative_flights`/`estimate_affected_passengers`/`get_airport_ground_activity` (no listas/dicts vacíos por falta de `flight_context`).
- [ ] El supervisor decide el routing sin llamar al LLM (si se confirma 6.1), o se documenta explícitamente por qué se conserva.
- [ ] Tests actualizados y suite completa ejecutada.
