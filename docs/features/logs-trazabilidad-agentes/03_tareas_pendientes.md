# Tareas pendientes: logs-trazabilidad-agentes

> Estado: 🟢 Completado
> Última actualización: 2026-07-13

## Bloque 1 — Preparación
- [x] T1.1 — Añadir `LOG_LEVEL=INFO` a `.env.example`

## Bloque 2 — Implementación
- [x] T2.1 — Crear `config/logging_config.py` con `configure_logging()` (idempotente, lee `LOG_LEVEL` de entorno, formato texto plano a stdout) y `get_logger(name)`
- [x] T2.2 — Instrumentar `graph/supervisor.py`: log de la decisión de routing en `supervisor()` y wrapper `_with_node_logging()` aplicado a los 4 nodos en `build_graph()` (entrada/salida/duración por nodo)
- [x] T2.3 — Sustituir los `print()` de `graph/router.py` por `logger.warning(...)`, sin condicionarlos a `DEBUG_MODE`
- [x] T2.4 — Instrumentar `agents/analytical_agent.py`: log de cada llamada LLM (`bind_tools`, con duración) y de cada tool invocada (nombre/args/resultado) en `_run_react_loop()` y `_ensure_cascade_risk_context()`; sustituir el `print()` de límite de turnos
- [x] T2.5 — Instrumentar `agents/disruption_agent.py`: log de las 3 tools invocadas en `_gather_disruption_data()` y de la llamada LLM en `_synthesize()` (con duración)
- [x] T2.6 — Instrumentar `agents/communication_agent.py`: log de la llamada LLM (con duración); sustituir el `print()` de error existente, sin condicionarlo a `DEBUG_MODE`

## Bloque 2b — Correcciones surgidas de la validación manual del usuario (no previstas)
- [x] T2.7 — `graph/router.py`: no loggear como `WARNING` la decisión de routing vacía (`""`), que es el valor esperado siempre que pasa el supervisor 100% determinista; se reduce a `DEBUG`. Se mantiene `WARNING` para cadenas no vacías realmente inválidas
- [x] T2.8 — `agents/analytical_agent.py`: envolver `llm_with_tools.invoke()` en try/except con logging de error (antes fallaba en silencio, sin ninguna traza, cuando la llamada LLM lanzaba una excepción); loggear también el error capturado en el `except` de nivel de nodo, y un resumen final (tools consultadas + resultado de `delay_prediction`)
- [x] T2.9 — `agents/disruption_agent.py`: loggear el error capturado en el `except` de nivel de nodo (antes silencioso); loggear un resumen final (severidad, alternativas evaluadas, coste estimado)

## Bloque 3 — Pruebas
- [x] T3.1 — Crear `tests/unit/test_logging_config.py` (nombre de logger, nivel por defecto `INFO`, idempotencia de `configure_logging()`)
- [x] T3.2 — Ejecutar la suite completa existente (`tests/unit/` + `tests/integration/`) y confirmar que sigue en verde sin modificar sus aserciones
- [x] T3.3 — Validación manual: ejecutar `python main.py`, lanzar una consulta que dispare los 3 agentes (predicción de un vuelo concreto) y confirmar que la terminal muestra en tiempo real la secuencia completa (supervisor → analytical_agent → supervisor → disruption_agent → supervisor → communication_agent → supervisor → END, con tools y llamadas LLM visibles)

## Bloque 4 — Documentación
- [x] T4.1 — Anotar en `99_devlog.md` el resultado de la validación manual (T3.3) como evidencia de cierre
