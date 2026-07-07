# Devlog: refactor-agente-comunicacion

---

## [2026-07-03 00:00] — Inicio del evolutivo
- Carpeta creada en `docs/features/refactor-agente-comunicacion/`.
- Revisados: `agents/communication_agent.py`, `prompts/communication_prompt.py`, `tools/communication_tools.py`, `graph/state.py` (`final_response`), `graph/supervisor.py`, `backend/app/api/` (rutas actuales), `backend/app/services/query_service.py`, `frontend/src/App.jsx`, `frontend/src/styles.css`.
- Este es el evolutivo con mayor alcance de frontend hasta ahora (interfaz conversacional + panel de estado), y el primero que requiere decidir un mecanismo de persistencia/historial en el backend (hoy no existe ninguno más allá del log de notificaciones).
- Análisis redactado con 5 preguntas abiertas, la más importante: si "interfaz conversacional" implica memoria real entre consultas o solo un historial visual en el frontend sobre peticiones stateless (recomendado, mucho menor riesgo).

## [2026-07-03 00:20] — Análisis respondido; planificación redactada
- 6.1: historial visual (b), sin memoria real en el grafo. 6.2: historial en memoria del backend (a), sin persistencia nueva. 6.3: el agente solo redacta notificaciones, el operador decide enviarlas (nuevo endpoint). 6.4: métricas mínimas propuestas, aceptadas para empezar. 6.5: delegado — se añade `draft_notifications` estructurado manteniendo `final_response` sin duplicarlo, por consistencia con el patrón ya aplicado a los otros 2 agentes.
- `02_planificacion.md` redactado: `communication_agent` se simplifica a una única llamada LLM (sin tool-calling); nuevo `history_service` en memoria; nuevos endpoints `/api/dashboard` y `/api/notifications/send`; frontend dividido en `ChatPanel`/`DashboardPanel` con pestañas.
- Pendiente: validación del usuario antes de generar `03_tareas_pendientes.md`.

## [2026-07-03 00:30] — Planificación aprobada, desglose de tareas generado
- Usuario aprueba pasar a la siguiente fase ("vamos").
- `03_tareas_pendientes.md` creado con 9 bloques (~28 tareas): estado, prompt, agente de comunicación, historial en memoria, schemas/wiring, nuevas rutas API, frontend (4 tareas), tests, validación manual y cierre.
- Pendiente: validación del usuario sobre el desglose antes de empezar la ejecución.

## [2026-07-03 00:40] — Desglose aprobado, inicio de ejecución
- Usuario pide ejecutar hasta el Bloque 8, dejando la validación manual (Bloque 9) para más adelante — mismo patrón que los dos evolutivos anteriores.
- Bloque 1 completado: `graph/state.py` con `NotificationDraft`, `SGIDAState.draft_notifications`, `initial_state` actualizado.
- Bloque 2 completado: `communication_prompt.py` reescrito para salida estructurada única (`final_response` + `draft_notifications`), dejando explícito que son borradores no enviados.
- Bloque 3 completado: `communication_agent.py` reescrito por completo (sin `bind_tools`, única llamada `with_structured_output`); `tools/communication_tools.py` con docstring actualizado (tools ahora invocadas desde rutas de API). Verificado con `ast.parse`.
- Bloque 4 completado: nuevo `backend/app/services/history_service.py` (historial en memoria, tope 50, sin persistencia). Verificado con `ast.parse`.
- Bloque 5 completado: `schemas.py` con `QueryResponse.draft_notifications`, `NotificationSendRequest`, `DashboardResponse`; `query_service.py` registra actividad en `history_service` tras cada consulta. Verificado con `ast.parse`.
- Bloque 6 completado: nuevas rutas `dashboard.py` (`GET /dashboard`) y `notifications.py` (`POST /notifications/send`), registradas en `app.py`. Verificado funcionalmente con `TestClient` (health/dashboard/notifications responden 200); se limpió el registro de prueba escrito en `data/notifications_log/notifications.jsonl`.
- Bloque 7 completado: frontend dividido en `ChatPanel.jsx` (historial de chat + tarjetas de notificación con botón "Enviar") y `DashboardPanel.jsx` (métricas + actividad reciente), `App.jsx` reducido a shell con pestañas, nuevo `api.js` compartido, estilos añadidos. `npx vite build` verificado sin errores.

## [2026-07-03 01:30] — Bloque 8 completado (tests); Bloque 9 pospuesto
- `tests/integration/test_communication_agent.py` reescrito por completo (mock de `with_structured_output`, casos de `draft_notifications`, modo degradado).
- `tests/unit/test_state.py`: `NotificationDraft` + `draft_notifications` en `initial_state`.
- Nuevo `tests/unit/test_history_service.py` y nuevo `tests/integration/test_api_routes.py` (`TestClient`, smoke tests de las 4 rutas de la API).
- Suite completa: **177 passed, 1 failed** (mismo fallo preexistente no relacionado). Se detectó y corrigió una regresión real en `tests/integration/test_supervisor.py`: seguía mockeando `communication_agent` con el patrón `bind_tools` ya eliminado en este evolutivo; corregido a `with_structured_output`.
- El usuario pide, como en los evolutivos anteriores, posponer la validación manual y el cierre (Bloque 9, incluido el HTML de revisión) para más adelante. El evolutivo queda documentado y en curso.
