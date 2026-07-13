# Análisis: logs-trazabilidad-agentes

## 1. Petición original
> "quiero que siguiendo la metodologia de AGENTS.md implementemos unos logs que vayan mostrando por terminal el punto en el que se encuentra el sistema y todo lo que va ocurriendo, de modo que cuando le haga una pregunta me vaya poniendo que agente esta siendo usado, que herramientas usa, si hace llamada a llm, etc."

## 2. Objetivo
Dotar a SGIDA de un sistema de logging estructurado que, al ejecutar una consulta (por CLI o vía API), muestre por terminal en tiempo real: qué nodo del grafo está activo (supervisor / analytical / disruption / communication), qué herramientas se invocan y con qué argumentos, cuándo se hace una llamada al LLM (Ollama) y su duración, y el resultado/errores de cada paso. El objetivo es dar visibilidad operativa y de depuración sin alterar el comportamiento funcional del grafo.

## 3. Estado actual del proyecto

### Módulos / ficheros relevantes
- **`graph/supervisor.py`**: construye el `StateGraph` (LangGraph) y define el nodo `supervisor`, 100% determinista, que decide el routing vía `graph/router.py::safe_next_node`.
- **`graph/router.py`**: lógica de enrutamiento y salvaguardas (límite de iteraciones, nodo inválido, no repetir agente). Ya tiene algunos `print()` condicionados a `Settings.DEBUG_MODE`.
- **`graph/state.py`**: `SGIDAState` (TypedDict), estado compartido entre nodos.
- **`agents/analytical_agent.py`**: bucle ReAct manual (`llm_with_tools.invoke()` hasta `_MAX_REACT_TURNS = 3`), invoca tools de `tools/analytical_tools.py`, ensambla resultado sin LLM adicional. Tiene un `print()` de depuración si se alcanza el límite de turnos.
- **`agents/disruption_agent.py`**: recoge datos deterministamente invocando 3 tools directamente (sin bucle ReAct), calcula severidad/coste/alternativa en código, y hace **una única** llamada LLM (`with_structured_output`) para redactar `actions`/`reasoning`.
- **`agents/communication_agent.py`**: una única llamada LLM (`with_structured_output`) que produce `final_response` y `draft_notifications`. Tiene un `print()` de error condicionado a `DEBUG_MODE`.
- **`tools/analytical_tools.py`, `tools/disruption_tools.py`, `tools/communication_tools.py`**: funciones `@tool` de LangChain que consultan DuckDB o calculan heurísticas; se invocan con `.invoke()` desde los agentes.
- **`config/settings.py`**: `Settings` (config global, incluye `DEBUG_MODE: bool`) y `get_llm()` (factoría cacheada de `ChatOllama`).
- **`backend/app/cli.py`**: punto de entrada CLI (`main.py` → `backend.app.cli.main`). Usa `rich.console.Console` para la interfaz; ya imprime una traza de depuración (`_print_debug_trace`) si `Settings.DEBUG_MODE` es `True`, pero solo al final de la ejecución (no en tiempo real).
- **`backend/app/services/query_service.py`**: punto de entrada API — llama a `graph.supervisor.run_query()` (mismo grafo que la CLI) y adapta el resultado a `QueryResponse`.
- **`backend/app/api/routes/query.py`** y resto de `backend/app/api/`: expone `run_query` vía FastAPI.

### Dependencias afectadas
- `rich` (ya en uso en `backend/app/cli.py` para la interfaz de consola).
- Ningún uso actual del módulo estándar `logging` de Python — toda la depuración existente es `print()` condicionado a `Settings.DEBUG_MODE` (ver `config/settings.py`, `graph/router.py`, `agents/analytical_agent.py`, `agents/communication_agent.py`).
- LangChain / LangGraph: los agentes invocan `get_llm().invoke(...)`, `.bind_tools(...)`, `.with_structured_output(...)` y las tools vía `tool_fn.invoke(...)`. Son los puntos naturales para envolver con logging (duración de llamada LLM, tool invocada + argumentos + resultado).

### Configuración actual relacionada
- `Settings.DEBUG_MODE` (env `DEBUG_MODE`, default `false`): actualmente solo controla si se imprimen algunos `print()` puntuales y la traza final en CLI. No existe un nivel de verbosidad granular ni un logger configurado.

### Tests existentes que cubren el área
- `tests/integration/test_analytical_agent.py`, `test_disruption_agent.py`, `test_communication_agent.py`, `test_supervisor.py`: prueban el comportamiento funcional de cada nodo (mockeando LLM/tools previsiblemente). Ninguno verifica salida de logs.
- `tests/unit/test_router.py`, `test_state.py`: prueban routing determinista y estado.
- No hay tests actuales sobre logging/trazabilidad — es funcionalidad nueva.

## 4. Alcance

### Dentro de alcance
- Sustituir los `print()` de depuración dispersos por un logger estructurado (módulo estándar `logging` de Python, con posible formateo enriquecido vía `rich` para la CLI).
- Loggear, para cada consulta:
  - Entrada al grafo (consulta del operador, criterio de optimización).
  - Cada transición de nodo (supervisor decide ir a X).
  - Cada llamada al LLM: agente que la hace, tipo de llamada (`bind_tools` / `with_structured_output`), y duración.
  - Cada invocación de tool: nombre, argumentos, y resumen del resultado (o error).
  - Resultado final / errores capturados por cada agente.
- Que los logs aparezcan **en tiempo real** por terminal (no solo al final, a diferencia del `_print_debug_trace` actual), tanto si se ejecuta por CLI (`main.py`) como si se ejecuta vía API (`backend/app/api/`, cuyo proceso también tiene una terminal/consola asociada al servidor).
- Un nivel de verbosidad configurable (reutilizando o extendiendo `Settings.DEBUG_MODE`, o añadiendo un nuevo `LOG_LEVEL`).

### Fuera de alcance
- Persistencia de logs en fichero o servicio externo (ya existe una lección aprendida previa de que un `logs/` en disco se eliminó por ser depuración puntual — no se reintroduce salvo que se pida explícitamente).
- Exponer los logs en el frontend (React) o vía un endpoint de streaming al cliente HTTP; el alcance es la terminal donde corre el proceso (servidor o CLI).
- Métricas/observabilidad (Prometheus, OpenTelemetry, etc.).
- Cambiar el comportamiento funcional del grafo, agentes o tools — este evolutivo es puramente de observabilidad.

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Logging añade acoplamiento repetido en los 3 agentes + router + supervisor, con riesgo de duplicar lógica | Media | Media | Centralizar en un módulo `logging_config.py` (o similar) con un logger nombrado y helpers reutilizables (p.ej. decorador o context manager para medir llamadas LLM) |
| Logs muy verbosos degradan la legibilidad de la CLI (`rich` ya gestiona la interfaz interactiva) | Media | Baja | Usar niveles de log (`INFO` para trazabilidad de agente/tool/LLM, `DEBUG` para detalle de payloads) y permitir configurar el nivel por `.env` |
| Logging de argumentos/resultados de tools podría exponer datos sensibles en consola (aunque el dataset es histórico público de vuelos) | Baja | Baja | Revisar que no se loggeen credenciales ni tokens (no aplica aquí, pero se deja como criterio de aceptación) |
| Mezclar `print()` de `rich.console.Console` (interfaz CLI) con el nuevo logger puede producir salida desordenada o duplicada | Media | Media | Definir claramente qué usa `rich` (interfaz de usuario: banner, respuesta final) y qué usa el logger (trazabilidad interna), evitando solapamiento |
| Coste de latencia al medir tiempos de llamada LLM/tools (mínimo, pero a validar) | Baja | Baja | Usar `time.perf_counter()`, overhead despreciable |

## 6. Preguntas abiertas
- [x] ¿El logging debe activarse siempre por defecto (nivel `INFO` básico: agente/tool/LLM) o solo cuando `DEBUG_MODE=true` / un nuevo flag `LOG_LEVEL`?
  → **Activo por defecto** (nivel `INFO`), independiente de `DEBUG_MODE`. Se deja configurable para poder ajustarlo más adelante si hace falta.
- [x] ¿Se quiere loggear también el contenido completo de prompts y respuestas del LLM, o solo metadatos?
  → **Solo metadatos** (agente, tipo de llamada, duración, éxito/error). No se loggean prompts ni respuestas completas por ahora.
- [x] En el flujo API, ¿los logs van a la terminal del proceso servidor tal cual, o con un id de consulta para diferenciar requests concurrentes?
  → **Tal cual, a la terminal del proceso** (uvicorn). No se añade id de correlación por request en esta fase.
- [x] ¿Formato `rich` (coherente con la CLI) o formato estándar de `logging`?
  → **Formato estándar de `logging`** (texto plano), no `rich`.

## 7. Criterios de aceptación
- [ ] Al ejecutar una consulta por CLI (`python main.py` / `backend.app.cli.main`), la terminal muestra en tiempo real (no solo al final): entrada de la consulta, cada nodo del grafo por el que pasa, cada tool invocada (nombre + args resumidos), cada llamada al LLM (agente + tipo), y el resultado final.
- [ ] El mismo comportamiento aplica al ejecutar una consulta vía API (servidor uvicorn), visible en la terminal donde corre el servidor.
- [ ] No se han introducido cambios en el comportamiento funcional del grafo, agentes o tools (los tests de integración existentes en `tests/integration/` siguen pasando sin modificación de sus aserciones funcionales).
- [ ] Los `print()` de depuración actuales dispersos en `graph/router.py`, `agents/analytical_agent.py`, `agents/communication_agent.py` y `config/settings.py` quedan sustituidos por el logger centralizado (o justificado por qué se mantienen si alguno es intencionalmente parte de la interfaz `rich`).
- [ ] El nivel de verbosidad es configurable (vía `.env` / `Settings`), sin necesidad de tocar código para activarlo o desactivarlo.
- [ ] No se loggean datos sensibles (no aplica actualmente, pero se deja como criterio para futuras ampliaciones).
