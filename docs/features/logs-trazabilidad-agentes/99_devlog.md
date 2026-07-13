# Devlog: logs-trazabilidad-agentes

---

## [2026-07-13 00:00] — Inicio del evolutivo
- Carpeta creada en `docs/features/logs-trazabilidad-agentes`
- Confirmado nombre y alcance con el usuario (logging por terminal, CLI + API)

## [2026-07-13 00:10] — Análisis completado y aprobado
- Usuario resolvió las 4 preguntas abiertas: nivel `INFO` activo por defecto, sin loggear prompts/respuestas completas, sin id de correlación por request en el API, formato estándar de `logging` (no `rich`)

## [2026-07-13 00:20] — Planificación completada y aprobada
- Decisión clave: instrumentación de transiciones de nodo centralizada en un único wrapper dentro de `graph/supervisor.py::build_graph()`, en vez de repetir logging en cada agente
- Decisión clave: `config/logging_config.py` lee `LOG_LEVEL` directamente de entorno (sin pasar por `Settings`) para evitar import circular
- Usuario aprobó continuar a la fase de tareas

## [2026-07-13 00:25] — Desglose de tareas completado y aprobado
- 11 tareas en 4 bloques (preparación, implementación, pruebas, documentación)
- Usuario aprobó iniciar la ejecución

## [2026-07-13 01:00] — Bloque 1 y Bloque 2 (T1.1-T2.6) completados
- `config/logging_config.py` creado; `graph/supervisor.py`, `graph/router.py`, `agents/analytical_agent.py`, `agents/disruption_agent.py`, `agents/communication_agent.py` instrumentados
- `.env.example` documenta `LOG_LEVEL=INFO`

## [2026-07-13 01:15] — T3.1 completada: tests/unit/test_logging_config.py
- 5 tests, todos en verde. Se descubrió que pytest adjunta sus propios handlers al logger "sgida" (ver 04_lecciones_aprendidas.md); el test de idempotencia filtra por el formatter propio en vez de contar `len(handlers)`

## [2026-07-13 01:20] — T3.2 completada: suite completa ejecutada
- 190 passed, 1 failed (tests/unit/test_analytical_tools.py::TestGetDelayByHour::test_hours_are_in_valid_range). Confirmado con `git stash` que ese fallo es pre-existente (dato `hour=24` en el dataset BTS), no relacionado con este evolutivo

## [2026-07-13 01:30] — Usuario ejecuta T3.3 (validación manual) y reporta 3 problemas
- El router logueaba `WARNING` en cada transición del grafo (ruido, no anomalía real)
- `disruption_agent` nunca se activó en una consulta que debía dispararlo
- El log no daba pistas de qué tools/LLM se habían intentado cuando algo fallaba
- Diagnóstico: `analytical_agent` fallaba con una excepción no logueada (el `except` de nivel de nodo era silencioso desde antes de este evolutivo); eso ponía `error` en el estado y el router saltaba directo a `communication_agent`, saltándose `disruption_agent` (comportamiento correcto del router, pero sin visibilidad de la causa raíz)
- Correcciones aplicadas (T2.7-T2.9, añadidas a 03_tareas_pendientes.md como bloque no previsto): `router.py` distingue decisión vacía (esperada, `DEBUG`) de decisión inválida real (`WARNING`); `analytical_agent.py` envuelve la llamada LLM en try/except con logging y logea el `except` de nodo; `disruption_agent.py` logea su `except` de nodo; ambos añaden un resumen final (tools/severidad/coste)
- Lección registrada en 04_lecciones_aprendidas.md
- Pendiente: usuario debe repetir la consulta para confirmar que ahora aparece el error real de `analytical_agent` en el log y decidir si hace falta un evolutivo aparte para el bug funcional subyacente (por qué falla la llamada LLM)

## [2026-07-13 02:00] — T3.3 confirmada con evidencia: causa raíz visible en el log
- Usuario repite la consulta. El log ahora muestra exactamente lo que fallaba:
  `ERROR | sgida.analytical_agent | Llamada LLM (bind_tools, turno 1/3) -> ERROR tras 92037 ms: timed out`
  seguido del traceback completo (`httpx.ReadTimeout`) y `analytical_agent fallo: timed out`
- Causa raíz identificada (fuera del alcance de este evolutivo, es un bug/config funcional, no de logging): la llamada a Ollama tarda >90s y acaba en `ReadTimeout`, pese a que `Settings.LLM_REQUEST_TIMEOUT` (usado en `client_kwargs={"timeout": ...}` de `ChatOllama`, ver `config/settings.py`) está a 20s por defecto — el timeout real observado (92s) no coincide con el configurado, sugiere que el timeout de `client_kwargs` no se está aplicando al `stream()` de `httpx` en la llamada de tool-calling, o que el modelo local es simplemente muy lento en esta máquina para `bind_tools`
- La secuencia de agentes tras el fallo es la esperada dado el diseño: `analytical_agent` (error) -> `communication_agent` (LLM sintetiza un mensaje de error para el operador, correcto) -> END. `disruption_agent` no se salta por un bug de routing, sino porque nunca hay `delay_prediction`/`is_disruption` al fallar el primer agente
- Con esto, T3.1, T3.2 y T3.3 quedan completadas con evidencia. Bloques 1-4 de `03_tareas_pendientes.md` completos
- Queda abierta la decisión: ¿abrir un evolutivo nuevo para investigar/arreglar el timeout real de Ollama en `bind_tools` (posible bug de `client_kwargs` no propagándose al streaming, o simplemente hardware/modelo lento)? No se toca en este evolutivo (fuera de alcance, es un cambio funcional no de logging)
- Usuario decide: cerrar este evolutivo ahora; el bug del timeout se aborda en un evolutivo aparte más adelante, no aquí

## [2026-07-13 02:10] — Cierre sin HTML de revisión (falta la plantilla de referencia)
- Al intentar generar `logs-trazabilidad-agentes-review.html` según §4.6 de AGENTS.md, se comprueba que `docs/templates/review-template.html` **no existe** en el repositorio
- Se comprobó además que ninguno de los evolutivos previos (`refactor-agente-analitico`, `refactor-agente-comunicacion`, `refactor-agente-disrupcion`, `revision-supervisor`) generó nunca su `-review.html` — el hueco es anterior a este evolutivo, no algo introducido aquí
- AGENTS.md §7 prohíbe explícitamente generar el HTML con estilos inventados sin la plantilla, y §7 también prohíbe cerrar un evolutivo sin el HTML validado — hay una contradicción de facto en la metodología actual (no hay plantilla, pero tampoco se puede cerrar sin ella)
- **Propuesta de mejora de la template/proceso** (registrada aquí tal como indica §4.6 regla 2, ya que no se inventa CSS): crear `docs/templates/review-template.html` como un evolutivo `meta-crear-review-template` que defina los componentes base (hero, badges, tablas, callouts) reutilizables por todos los evolutivos futuros, y retroactivamente generar el HTML pendiente de los 4 evolutivos anteriores + este si se considera necesario
- Decisión del usuario (2026-07-13): cerrar `logs-trazabilidad-agentes` sin el artefacto HTML por ahora. Las tareas funcionales (bloques 1-4 de `03_tareas_pendientes.md`) están completas y verificadas con evidencia; solo falta el artefacto de comunicación no técnica, que queda pendiente hasta que exista la plantilla
- Estado final del evolutivo: **completado funcionalmente**, cierre de comunicación (HTML) diferido
