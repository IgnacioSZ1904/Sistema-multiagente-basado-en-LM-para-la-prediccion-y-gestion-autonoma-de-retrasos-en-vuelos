# Lecciones aprendidas: logs-trazabilidad-agentes

## [2026-07-13] — pytest adjunta sus propios handlers al logger nombrado, no solo al root

**Contexto:** Tarea T3.1, escribiendo `tests/unit/test_logging_config.py` para verificar que `configure_logging()` es idempotente (no duplica handlers).

**Qué pasó:** El test `test_does_not_duplicate_handlers_on_repeated_calls` fallaba con `3 == 1`: además del `StreamHandler` propio, aparecían dos `LogCaptureHandler` de pytest en `logging.getLogger("sgida").handlers`, pese a que ese logger tiene `propagate = False`.

**Causa raíz:** Se asumió que el plugin de logging de pytest solo instrumenta el logger raíz de Python (`logging.getLogger()`), y que un logger con `propagate=False` quedaría aislado de esa instrumentación. En realidad pytest adjunta sus handlers de captura directamente sobre loggers nombrados también, independientemente de `propagate`.

**Corrección aplicada:** El test no cuenta `len(logger.handlers)` a secas; filtra por los handlers cuyo formatter coincide con `logging_config._LOG_FORMAT` (los que añade nuestro propio código), ignorando cualquier handler que pytest u otro plugin haya adjuntado al mismo logger.

**Regla para el futuro:** Al testear idempotencia o cantidad de handlers de un logger en este proyecto, filtrar siempre por una propiedad identificable de los handlers propios (formatter, tipo, atributo marcador) en lugar de comparar `len(logger.handlers)` directamente — pytest y otros plugins pueden añadir sus propios handlers al mismo logger durante la ejecución de tests.

**Tags:** `#testing` `#logging`

## [2026-07-13] — El "fallback determinista" del router no es una anomalía cuando el supervisor es 100% determinista

**Contexto:** T3.3 (validación manual por el usuario). Ejecutó una consulta que debía activar los 3 agentes; solo se activaron `analytical_agent` y `communication_agent` (nunca `disruption_agent`), y el router logueaba `WARNING` en cada transición.

**Qué pasó:** Dos problemas relacionados:
1. `graph/router.py::safe_next_node` siempre recibe `llm_decision=""` desde `graph/supervisor.py` (diseño 100% determinista, sin LLM decidiendo routing — ver docstring de `supervisor.py`). Al instrumentar la "salvaguarda 2" (nombre de nodo inválido) con `logger.warning(...)` sin distinguir este caso, **cada** transición del grafo generaba un WARNING, aunque fuera el comportamiento normal y esperado, no una anomalía.
2. `analytical_agent()` falló con una excepción (probablemente en `llm_with_tools.invoke()`, que no tenía try/except propio) y el `except` de nivel de nodo la capturaba en silencio (solo `return {"error": ...}`, sin loggear nada). Esto dejó al `disruption_agent` sin activarse (la regla determinista de `_deterministic_fallback` prioriza `communication_agent` cuando hay `error`), y sin ninguna pista en el log de qué había fallado ni qué tools/LLM se habían intentado invocar.

**Causa raíz:** Al diseñar la instrumentación (fase de planificación) no se tuvo en cuenta que "nombre de nodo inválido" ya no es una salvaguarda contra un LLM real (esa arquitectura cambió en el evolutivo `revision-supervisor`, antes de este), sino el camino normal en el 100% de las ejecuciones. Y se instrumentaron solo los `try/except` que ya existían en el código, sin añadir logging al `except` de nivel de nodo (que sí existía, pero estaba mudo desde el principio, no solo desde este evolutivo).

**Corrección aplicada:** `router.py` distingue ahora decisión vacía (`DEBUG`, esperado) de decisión no vacía pero inválida (`WARNING`, anomalía real). Se añadió try/except con logging alrededor de `llm_with_tools.invoke()` en `analytical_agent.py`, y logging de error en los `except` de nivel de nodo de `analytical_agent()` y `disruption_agent()`, que antes devolvían `{"error": ...}` sin dejar rastro alguno en el log.

**Regla para el futuro:** Antes de fijar el nivel de severidad de un log (`WARNING` vs `DEBUG`/`INFO`), verificar contra el diseño real si la condición que dispara ese log es una anomalía genuina o el camino esperado en el flujo normal — no asumirlo por el nombre de la salvaguarda o comentario original. Además, cuando se instrumenta logging de errores, revisar también los bloques `except` que ya existían antes de esta tarea (no solo los que se tocan al añadir nueva lógica), porque un `except: return {"error": ...}` silencioso es precisamente el tipo de punto ciego que este evolutivo pretende eliminar.

**Tags:** `#logging` `#arquitectura` `#diseño`
