# Análisis: refactor-agente-disrupcion

## 1. Petición original
> "vale ahora de la misma forma que hemos hecho con el agente analitico quiero que refactoricemos el agente de disrupcion (siguiendo agents.md de nuevo), las indicaciones iniciales son estas: una vez detectado o predicho un retraso, este agente razona sobre las opciones disponibles y propone soluciones concretas, como la reasignación automática de pasajeros a vuelos alternativos o la priorización de recursos en tierra. Quiero que este agente no acceda a la base de datos, toma los datos del agente analitico y evalua cual puede ser la mejor opcion. de nuevo quiero que la salida de este agente tenga un formato predefinido y que entregue lo necesario para posteriormente generar un informe para el operador, incluyendo la informacion que le venga previamente del agente analitico y la informacion extra aportada por este agente."
>
> Requisitos de sistema citados como objetivo final:
> - Análisis exploratorio automatizado del dataset de vuelos, identificando las principales causas, rutas y aeropuertos con mayor incidencia de retrasos.
> - Predicción de retrasos en tiempo real a partir de las condiciones de un vuelo dado, estimando su impacto sobre el resto de operaciones conectadas.
> - Generación autónoma de propuestas de actuación ante una disrupción, evaluando alternativas y seleccionando la más adecuada según criterios configurables como minimizar el número de pasajeros afectados o el coste operativo.

## 2. Objetivo
> **[CORREGIDO 2026-07-03]** Tras validar el análisis, el usuario reconsideró 6.1: el agente de disrupción **conserva el acceso a la base de datos** vía sus 3 tools (la preocupación real era el tiempo de ejecución por añadir más idas y vueltas al LLM, no el acceso a BD en sí — ver `02_planificacion.md` para cómo se resuelve sin ese coste).

Redefinir el Agente de Disrupción para que **evalúe explícitamente varias alternativas de actuación** (usando sus 3 tools existentes de solo lectura sobre la base de datos) y seleccione la mejor según un **criterio configurable por el operador desde la interfaz** (minimizar pasajeros afectados o minimizar coste operativo). Su salida es un JSON con formato predefinido, autocontenido, que incluye tanto el contexto heredado del Agente Analítico como la información adicional que él mismo aporta (alternativas evaluadas, criterio usado, justificación), preparado para que un informe posterior (generado por `communication_agent` o una funcionalidad futura de reporting) no necesite volver a consultar otras fuentes.

## 3. Estado actual del proyecto

### Módulos / ficheros relevantes existentes
- `agents/disruption_agent.py`: patrón de dos fases (ReAct manual con `bind_tools` sobre `DISRUPTION_TOOLS` → síntesis con `with_structured_output(DisruptionOutput)`). Ya recibe `delay_prediction` y `analytics_result` (JSON serializado explícitamente, tras el evolutivo anterior), pero **también** ejecuta 3 herramientas propias que acceden a la base de datos.
- `tools/disruption_tools.py`: 3 tools, **todas acceden a DuckDB directamente** (`duckdb.connect(Settings.DB_PATH, read_only=True)`):
  - `find_alternative_flights`: vuelos históricamente comparables como candidatos de reasignación.
  - `estimate_affected_passengers`: estimación heurística de pasajeros afectados (capacidad media de 150 pax/vuelo, documentado como heurística porque el dataset no tiene pasajeros reales).
  - `get_airport_ground_activity`: congestión histórica del aeropuerto en una franja horaria (proxy de recursos en tierra).
  - El docstring del módulo ya documenta la limitación de fondo: el dataset BTS es histórico de vuelos operados, no un sistema de reservas/inventario en tiempo real; todo es "propuesta", no ejecución real.
- `prompts/disruption_prompt.py`: `DISRUPTION_REACT_SYSTEM_PROMPT` instruye el uso de las 3 tools; `DISRUPTION_STRUCTURED_SYSTEM_PROMPT` fija reglas de `severity` (por rangos de minutos), `actions`, `alternative_flights`, `affected_passengers_est`, `reasoning`. No existe ningún concepto de "criterio de optimización" ni de "alternativas evaluadas explícitamente" — hoy el LLM elige una única propuesta sin dejar constancia de qué otras opciones consideró ni por qué.
- `graph/state.py` → `DisruptionProposal` (`TypedDict`, `total=True`): `proposal_id`, `severity`, `actions`, `affected_passengers_est`, `alternative_flights` (lista de strings libres), `reasoning`. No hay campo para el criterio usado, para las alternativas descartadas, ni para el contexto heredado del analítico embebido.
- `agents/communication_agent.py`: vuelca `disruption_proposal` como bloque JSON crudo en el prompt (tras el evolutivo anterior). No depende de campos concretos — cualquier ampliación del shape es retro-compatible sin tocar este agente.
- `graph/state.py` → `AnalyticsResult`/`DelayPrediction` (ver evolutivo `refactor-agente-analitico`): ya tipados, ya sin narrativa, ya con `cascade_risk_context` como campo **opcional** que el agente analítico solo rellena si el LLM decide invocar `get_cascade_risk_context` durante su bucle ReAct — no es una garantía automática cuando hay disrupción.
- `config/settings.py`: no existe ningún parámetro de "criterio de optimización" (pasajeros vs coste) ni ningún proxy de coste operativo.
- `backend/app/schemas.py` → `QueryResponse.disruption_proposal: dict[str, Any] | None`: tipo genérico, no requiere cambios por ampliar el shape.

### Dependencias afectadas
- Si las 3 tools de `disruption_tools.py` dejan de ejecutarse desde `disruption_agent` (por el requisito "no accede a la base de datos"), su lógica debe migrar a algún sitio que sí tenga acceso a BD — el candidato natural es `analytical_agent`/`analytical_tools.py`, ya que es el único agente con acceso a datos históricos tras el evolutivo anterior. Esto **vuelve a tocar el agente analítico**, que se cerró (parcialmente) en el evolutivo previo.
- El bucle ReAct de `disruption_agent` pierde su razón de ser si se queda sin ninguna tool propia — habría que decidir si se elimina por completo (agente de una sola llamada LLM, como ya se hizo con el analítico) o se mantiene vacío por si en el futuro se le asignan otras tools.

### Configuración actual relacionada
- `Settings.DELAY_THRESHOLD_MINUTES`: usado ya por `analytical_agent` para `is_disruption`.
- No existe aún ninguna variable de entorno para el criterio de optimización de propuestas.

### Tests existentes que cubren el área
- `tests/unit/test_disruption_tools.py`
- `tests/integration/test_disruption_agent.py`
- `tests/integration/test_supervisor.py` (indirectamente, vía el flujo completo del grafo)

## 4. Alcance

### Dentro de alcance
- Retirar el acceso a base de datos de `disruption_agent` (según se resuelva la pregunta 6.1 sobre el destino de las 3 tools actuales).
- Nuevo esquema de salida (`DisruptionProposal` / `DisruptionOutput`) con campos adicionales para: criterio de optimización usado, alternativas evaluadas (no solo la elegida), y el contexto heredado del agente analítico embebido para autocontención del informe.
- Nueva configuración de criterio de optimización (`Settings`), con al menos dos valores: minimizar pasajeros afectados / minimizar coste operativo (proxy a definir, dataset sin coste real).
- Revisión del patrón del agente (¿sigue teniendo bucle ReAct si se queda sin tools propias, o pasa a una única llamada estructurada como el analítico?).
- Actualización de `prompts/disruption_prompt.py` para reflejar el nuevo rol (evaluar alternativas ya proporcionadas, no buscar datos).
- Tests correspondientes (alcance de verificación exhaustiva a decidir con el usuario, dado el precedente del evolutivo anterior).

### Fuera de alcance
- Generar el informe final para el operador en sí (eso es de `communication_agent` o de una funcionalidad de reporting futura); este evolutivo solo entrega el JSON con la información necesaria para ello.
- Cambios en el frontend/API más allá de los ya cubiertos por el tipo genérico `dict[str, Any]`.
- Ejecutar reasignaciones reales o integraciones con sistemas de reservas (limitación de dataset ya documentada y fuera del alcance del TFG).

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Si las 3 tools se trasladan a `analytical_agent`, se reabre un evolutivo que se consideraba cerrado, con riesgo de inconsistencia con las decisiones ya tomadas (ensamblaje determinista, JSON tipado) | Alta si se confirma el traslado | Medio | Aplicar exactamente el mismo patrón ya validado (tool → campo tipado de `AnalyticsResult`, ensamblaje determinista, sin narrativa) en vez de inventar uno nuevo |
| "Coste operativo" no tiene proxy definido en el dataset (no hay precios, no hay costes de tripulación/combustible) | Alta | Medio | Definir una heurística explícita y documentada (igual que ya se hizo con `estimated_passenger_load`), a validar con el usuario en la pregunta 6.3 |
| Si `cascade_risk_context` sigue siendo opcional/discrecional del LLM analítico, `disruption_agent` puede quedarse sin información de "impacto en operaciones conectadas" justo cuando más la necesita (disrupción confirmada) | Media | Alto | Evaluar si el ensamblaje determinista del analítico debe invocar `get_cascade_risk_context` automáticamente cuando `is_disruption=True`, en vez de dejarlo a discreción del LLM (pregunta 6.6) |
| Ampliar `DisruptionProposal` con contexto duplicado (analytics_result/delay_prediction ya están en el estado) puede generar payloads grandes/redundantes | Baja | Bajo | Es una petición explícita del usuario ("incluyendo la información que le venga previamente"); documentar la duplicación como decisión consciente, no como descuido |

## 6. Preguntas abiertas

- [ ] **6.1 — Destino de las 3 tools actuales de `disruption_tools.py`** (la más importante, cross-cutting con el agente analítico). Al confirmar "no accede a la base de datos", ¿cuál de estas opciones es la correcta?
  - (a) Las 3 tools (`find_alternative_flights`, `estimate_affected_passengers`, `get_airport_ground_activity`) se trasladan a `tools/analytical_tools.py`; el agente analítico las invoca (probablemente solo cuando `is_disruption=True` o hay `flight_context`) y sus resultados pasan a ser campos opcionales de `AnalyticsResult`. El agente de disrupción las recibe ya calculadas.
  - (b) Se eliminan por completo: el agente de disrupción razona únicamente con lo que YA existe hoy en `analytics_result`/`delay_prediction` (sin buscar vuelos alternativos concretos ni congestión de aeropuerto), y "evaluar alternativas" se limita a razonar sobre las opciones que el propio LLM propone en su respuesta (sin candidatos históricos concretos respaldados por SQL).
  - (c) Otra combinación (p. ej., alguna tool se elimina y otra se traslada).
  mejor permitimos el acceso a base de datos,lo unico que no queria era aumentar mucho el tiempo de ejecucion por tener que hacer entradas con todos los agentes pero creo que tiene mas sentido accediendo a base de datos.

  Esto determina si este evolutivo vuelve a tocar `analytical_agent.py`/`analytical_tools.py`/`graph/state.py` (los ficheros que acabamos de cerrar) o no.

- [ ] **6.2 — Alcance del "criterio configurable"**: ¿es una variable de entorno/configuración fija para todo el sistema (`Settings.DISRUPTION_OPTIMIZATION_CRITERION = "min_passengers" | "min_cost"`), o algo que se pueda indicar por consulta (el operador escribe "prioriza minimizar el coste" en su pregunta y el sistema lo detecta)? Recomendación: empezar por configuración global (más simple, determinista, fácil de testear); dejar la detección por consulta como posible extensión futura.
La idea esque sea algo que el operador podra seleccionar en la interfaz antes de realizar la consulta

- [ ] **6.3 — Proxy para "coste operativo"**: el dataset no tiene coste real (ni precios de billete, ni coste de combustible/tripulación/reasignación). ¿Qué heurística usamos como proxy? Propuesta a validar: combinar `avg_late_aircraft_delay_min`/franja horaria de mayor congestión (más congestión histórica → más caro reubicar) y número de vuelos alternativos necesarios (más reasignaciones → más caro). Necesita quedar tan documentado como el proxy de pasajeros (`estimated_passenger_load`).
Me gusta la propuesta

- [ ] **6.4 — ¿Bucle ReAct o llamada única?**: si el agente de disrupción se queda sin tools propias (según se resuelva 6.1), ¿tiene sentido mantener el patrón `bind_tools` + bucle ReAct (que nunca tendría nada que llamar), o se simplifica a una única llamada `with_structured_output` razonando sobre el JSON ya recibido — mismo espíritu de "menos llamadas LLM" aplicado al agente analítico?
Vamos a intentar simplificar lo maximo posible(luego si vemos que queda corto ampliaremos complejidad)

- [ ] **6.5 — Campos "extra" concretos en el nuevo `DisruptionProposal`**: además de los campos actuales (`severity`, `actions`, `affected_passengers_est`, `alternative_flights`, `reasoning`), propongo añadir:
  - `optimization_criterion`: el criterio efectivamente usado ("min_passengers" | "min_cost").
  - `alternatives_considered`: lista de las opciones evaluadas (no solo la elegida), con una puntuación o motivo de descarte de cada una.
  - `estimated_operational_cost`: valor numérico del proxy de coste (ver 6.3), o `null` si el criterio activo es de pasajeros.
  - `source_context`: copia embebida (o referencia) de `analytics_result`/`delay_prediction` que motivó la propuesta, para que el JSON sea autocontenido de cara al informe.

  ¿Confirmas estos campos, o quieres añadir/quitar alguno? 
  me gustan los campos propuestos

- [ ] **6.6 — ¿El "impacto sobre el resto de operaciones conectadas" (cascade risk) debe ser obligatorio cuando hay disrupción?** Hoy `cascade_risk_context` es un campo opcional de `AnalyticsResult` que el LLM analítico rellena solo si decide llamar a `get_cascade_risk_context`. Dado que es uno de los 3 requisitos de sistema citados explícitamente, ¿debe el agente analítico invocar esa tool de forma **determinista** (no opcional) cada vez que `flight_context` está presente y/o `is_disruption=True`, para garantizar que el agente de disrupción siempre tenga ese dato disponible al evaluar alternativas?
Si pensamos que no va a dar problemas extra hagamoslo asi

## 7. Criterios de aceptación
- [ ] ~~`disruption_agent` no importa `duckdb`~~ — **descartado tras la corrección de 6.1**: conserva sus 3 tools de BD, pero se invocan de forma determinista (sin bucle ReAct/LLM decidiendo cuáles llamar), para no añadir latencia extra.
- [ ] La propuesta generada refleja explícitamente qué criterio de optimización se usó y qué alternativas se evaluaron (no solo la elegida).
- [ ] Existe una configuración (`Settings`) que permite cambiar el criterio de optimización, y ese cambio altera la alternativa seleccionada en al menos un caso de prueba.
- [ ] El JSON de salida (`DisruptionProposal`) es autocontenido: incluye tanto el contexto heredado del agente analítico como la información adicional aportada por el propio agente de disrupción.
- [ ] Los 3 requisitos de sistema citados por el usuario quedan cubiertos de extremo a extremo por la combinación de ambos agentes (analítico + disrupción).
- [ ] Tests actualizados y suite ejecutada (alcance de profundidad de verificación a confirmar, dado que en el evolutivo anterior se pospuso la validación exhaustiva).