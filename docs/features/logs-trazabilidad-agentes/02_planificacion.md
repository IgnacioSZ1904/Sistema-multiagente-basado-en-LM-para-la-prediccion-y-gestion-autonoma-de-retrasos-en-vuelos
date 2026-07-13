# Planificación: logs-trazabilidad-agentes

## 1. Enfoque técnico

Se introduce un módulo nuevo, `config/logging_config.py`, que centraliza la configuración del `logging` estándar de Python (un único `StreamHandler` a `stdout`, formato de texto plano, nivel configurable vía variable de entorno `LOG_LEVEL`, por defecto `INFO`) y expone `get_logger(nombre)` para que cada módulo obtenga un logger con nombre jerárquico (`sgida.<módulo>`). La configuración se aplica de forma perezosa (lazy) la primera vez que se pide un logger, así que ni la CLI ni el API necesitan una llamada de arranque explícita — basta con importar `get_logger`.

La instrumentación se reparte en dos niveles:
- **Nivel grafo (transiciones de nodo / "qué agente está activo")**: un único punto de envoltura en `graph/supervisor.py::build_graph()` que loggea entrada/salida y duración de cada nodo (`supervisor`, `analytical_agent`, `disruption_agent`, `communication_agent`), sin tocar el cuerpo de cada agente. Esto cubre el requisito "que agente está siendo usado" con una sola pieza de código, evitando duplicar la misma llamada de logging cuatro veces.
- **Nivel agente (tools y llamadas LLM)**: cada agente añade `logger.info(...)` puntuales alrededor de sus llamadas a `get_llm().invoke/bind_tools/with_structured_output` (con duración medida vía `time.perf_counter()`) y alrededor de cada invocación de tool (`tool_fn.invoke(...)`), indicando nombre de la tool, argumentos resumidos y si tuvo éxito o error. No se toca `tools/*.py` — el punto de invocación (y por tanto el punto natural de logging) ya está en los agentes.

Los `print()` de depuración ya existentes (`graph/router.py`, `agents/analytical_agent.py`, `agents/communication_agent.py`) se sustituyen por llamadas al logger centralizado, para no tener dos mecanismos de trazabilidad en paralelo. `backend/app/cli.py` mantiene su uso de `rich` intacto (interfaz de usuario: banner, panel de respuesta, `_print_debug_trace` final) — es un resumen distinto y complementario a los logs en tiempo real, no se fusiona con ellos.

Como tanto la CLI (`backend/app/cli.py`) como el API (`backend/app/services/query_service.py`) invocan el mismo `graph.supervisor.run_query()`, instrumentar el grafo y los agentes basta para que los logs aparezcan en ambos flujos sin tocar `backend/app/api/` ni `backend/app/services/`.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| Logging de transiciones de nodo centralizado en un wrapper dentro de `build_graph()`, no repetido en cada agente | Añadir `logger.info("entrando en X")` al principio de cada función de agente | Un único punto de instrumentación evita duplicar la misma línea de log 4 veces y garantiza que ningún nodo futuro se olvide de loggear su entrada/salida |
| `config/logging_config.py` lee `LOG_LEVEL` directamente de `os.getenv`, sin pasar por `Settings` | Añadir `LOG_LEVEL` a `config/settings.py` y que `logging_config` importe `Settings` | `config/settings.py` necesitaría importar `get_logger` de `logging_config` para loggear su propia validación → import circular. Al mantener `logging_config.py` autónomo (igual que `settings.py` ya hace con `load_dotenv`), se evita el ciclo |
| Nivel de log `INFO` activo por defecto, independiente de `Settings.DEBUG_MODE` | Reutilizar `DEBUG_MODE` como único interruptor | El usuario confirmó (fase de análisis, pregunta 1) que quiere trazabilidad por defecto; `DEBUG_MODE` sigue existiendo para otros usos (traza final en CLI) sin acoplarse al logging |
| Formato estándar de `logging` (texto plano), sin `rich` | Formatear los logs con `rich` para coherencia visual con la CLI | El usuario confirmó (fase de análisis, pregunta 4) formato estándar; además es más adecuado para la terminal del servidor API, que no siempre soporta el renderizado de `rich` |
| No se loggea el contenido de prompts ni respuestas del LLM, solo metadatos (agente, tipo de llamada, duración, éxito/error) | Loggear el prompt/respuesta completos para depuración profunda | Confirmado por el usuario (fase de análisis, pregunta 2); mantiene los logs legibles y evita ruido |
| Logging de tools centralizado en el punto de invocación dentro de cada agente (`agents/*.py`), no dentro de `tools/*.py` | Añadir logging dentro de cada función `@tool` | Los agentes son el único punto de invocación (`tool_fn.invoke(...)`); instrumentar ahí cubre las ~11 tools existentes con 3 puntos de código en vez de tocar cada función tool individualmente |
| No se añade id de correlación por consulta en los logs del API | Generar un `request_id`/`trace_id` y prefijar cada línea de log de esa consulta | Confirmado por el usuario (fase de análisis, pregunta 3): logs tal cual a la terminal del proceso; se deja fuera de alcance para no añadir complejidad no pedida |

## 3. Cambios por módulo

### `config/logging_config.py` (nuevo)
- Añade:
  - `configure_logging() -> None`: configura el logger raíz `"sgida"` con un `StreamHandler(stdout)` y formatter `"%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"`; nivel desde `os.getenv("LOG_LEVEL", "INFO")`. Idempotente (usa un flag de módulo para no añadir handlers duplicados si se llama más de una vez, relevante en tests que importan varios agentes).
  - `get_logger(name: str) -> logging.Logger`: garantiza `configure_logging()` ejecutado y devuelve `logging.getLogger(f"sgida.{name}")`.

### `graph/supervisor.py`
- Modifica:
  - `supervisor()`: añade `logger.info(...)` con la decisión de routing y la iteración.
  - `build_graph()`: envuelve cada nodo (`supervisor`, `analytical_agent`, `disruption_agent`, `communication_agent`) con un wrapper local que loggea entrada, salida y duración antes de registrarlo con `graph.add_node(...)`.
- Añade: función privada `_with_node_logging(name, fn)`.

### `graph/router.py`
- Modifica: sustituye los dos `print(...)` existentes (límite de iteraciones, decisión inválida) por `logger.warning(...)`, quitando la condición `if Settings.DEBUG_MODE` (pasan a loggearse siempre a nivel `WARNING`, visible por defecto).

### `agents/analytical_agent.py`
- Modifica:
  - `_run_react_loop()`: log de cada llamada LLM (`bind_tools`) por turno, con duración; log de cada tool invocada (nombre, args resumidos) y su resultado (éxito/error), sin alterar el manejo de excepciones existente (el log se añade alrededor del `try/except` ya existente, no lo sustituye). Sustituye el `print()` de límite de turnos por `logger.warning(...)`.
  - `_ensure_cascade_risk_context()`: log de la invocación determinista adicional de `get_cascade_risk_context` cuando aplica.

### `agents/disruption_agent.py`
- Modifica:
  - `_gather_disruption_data()`: log de cada una de las 3 tools invocadas (nombre, éxito/error), respetando los `try/except` existentes.
  - `_synthesize()`: log de la llamada LLM (`with_structured_output`) con duración.

### `agents/communication_agent.py`
- Modifica:
  - `communication_agent()`: log de la llamada LLM (`with_structured_output`) con duración; sustituye el `print()` de error existente por `logger.error(...)` (quitando la condición `if Settings.DEBUG_MODE`, pasa a loggearse siempre).

### `config/settings.py`
- Sin cambios (se evita el import circular explicado en la tabla de decisiones de diseño). Los `print()` de `Settings.validate()` se mantienen tal cual — son parte del arranque de configuración, no de la trazabilidad de una consulta, y ya están acotados a `DEBUG_MODE`.

### `.env.example`
- Añade la línea `LOG_LEVEL=INFO` documentando la nueva variable opcional.

### `backend/app/api/`, `backend/app/services/`, `backend/app/cli.py`
- Sin cambios de código — se benefician automáticamente de la instrumentación en `graph/` y `agents/` al compartir `run_query()`.

## 4. Modelo de datos / contratos

No aplica (no hay cambios de esquema, API pública ni estado del grafo). El único "contrato" nuevo es el formato de línea de log:

```
2026-07-13 10:32:01,123 | INFO    | sgida.supervisor | Supervisor -> analytical_agent (iteracion 1)
2026-07-13 10:32:01,124 | INFO    | sgida.graph.node | >> Entrando en nodo 'analytical_agent'
2026-07-13 10:32:01,980 | INFO    | sgida.analytical_agent | Llamada LLM (bind_tools, turno 1) -> OK en 850ms
2026-07-13 10:32:01,981 | INFO    | sgida.analytical_agent | Tool 'get_flight_historical_stats' invocada -> OK en 12ms
2026-07-13 10:32:02,010 | INFO    | sgida.graph.node | << Nodo 'analytical_agent' completado en 886ms
```

## 5. Plan de pruebas

- **Test unitario nuevo** `tests/unit/test_logging_config.py`:
  - `get_logger()` devuelve un `logging.Logger` con nombre `sgida.<name>`.
  - Nivel por defecto es `INFO` cuando no hay `LOG_LEVEL` en el entorno.
  - Llamar `configure_logging()` dos veces no duplica handlers en el logger raíz `"sgida"`.
- **Tests de integración existentes** (`tests/integration/test_analytical_agent.py`, `test_disruption_agent.py`, `test_communication_agent.py`, `test_supervisor.py`) y **unitarios** (`test_router.py`, `test_state.py`): se ejecutan sin modificar sus aserciones — deben seguir en verde, confirmando que el logging no altera el comportamiento funcional.
- **Validación manual**: lanzar `python main.py`, ejecutar una consulta que dispare los 3 agentes (p.ej. predicción de un vuelo concreto) y confirmar visualmente que la terminal muestra, en tiempo real, la secuencia completa: entrada → supervisor → analytical_agent (LLM + tools) → supervisor → disruption_agent (tools + LLM) → supervisor → communication_agent (LLM) → supervisor → END.
- No se añaden aserciones sobre el contenido exacto de los mensajes de log dentro de los tests funcionales de agentes (evita acoplar tests de comportamiento a redacción de logs, que puede cambiar); la cobertura de logging se concentra en `test_logging_config.py` + verificación manual.

## 6. Plan de despliegue / migración

No aplica — no hay migración de datos ni infraestructura. Único paso: documentar `LOG_LEVEL` en `.env.example` (opcional, con valor por defecto seguro si se omite).

## 7. Estimación de complejidad

- Nº aproximado de tareas: 11
- Áreas de mayor incertidumbre:
  - Verificar que envolver los nodos en `build_graph()` no interfiere con la forma en que LangGraph invoca/serializa las funciones de nodo (revisar en la fase de ejecución con un test manual antes de dar la tarea por cerrada).
  - Confirmar que la idempotencia de `configure_logging()` funciona correctamente bajo `pytest` (que importa múltiples módulos y podría re-invocar `get_logger()` muchas veces entre tests).
