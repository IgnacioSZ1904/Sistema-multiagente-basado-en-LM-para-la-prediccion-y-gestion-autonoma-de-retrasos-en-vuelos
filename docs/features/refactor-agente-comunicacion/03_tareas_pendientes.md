# Tareas pendientes: refactor-agente-comunicacion

> Estado: 🟡 En curso (Bloques 1-8 completados; Bloque 9 pospuesto a petición del usuario)
> Última actualización: 2026-07-03

## Bloque 1 — Estado (`graph/state.py`)
- [x] T1.1 — Nuevo `TypedDict NotificationDraft` (`recipient_type`, `channel`, `message`, `flight_reference`)
- [x] T1.2 — `SGIDAState.draft_notifications: list[NotificationDraft]`
- [x] T1.3 — `initial_state()`: inicializa `draft_notifications=[]`. Verificado con `ast.parse` + smoke test.

## Bloque 2 — Prompt
- [x] T2.1 — Reescrito `prompts/communication_prompt.py`: única llamada estructurada; instruye `draft_notifications` (operador siempre que hay `disruption_proposal`; pasajero adicional si `severity` es `"high"`/`"critical"`); deja explícito que son borradores, no envíos

## Bloque 3 — Agente de comunicación
- [x] T3.1 — Eliminado el bucle `bind_tools`/`COMMUNICATION_TOOLS` de `agents/communication_agent.py`
- [x] T3.2 — Nuevo `CommunicationOutput`/`NotificationDraftModel` (Pydantic): `final_response`, `draft_notifications`
- [x] T3.3 — Única llamada `with_structured_output` sobre el contexto ya construido por `_build_context_block`
- [x] T3.4 — Nodo `communication_agent(state)` reescrito: devuelve `final_response` + `draft_notifications` + traza en `messages`
- [x] T3.5 — Modo degradado / manejo de errores actualizado (`draft_notifications=[]`). Docstring de `tools/communication_tools.py` actualizado (tools ahora invocadas desde rutas de API, no desde el LLM)

## Bloque 4 — Historial en memoria (backend)
- [x] T4.1 — Nuevo `backend/app/services/history_service.py`: `record_activity`, `get_recent_activity(limit)`, `get_metrics()`, tope de 50 entradas

## Bloque 5 — Schemas y wiring de `query_service`
- [x] T5.1 — `QueryResponse.draft_notifications: list[dict] | None = None`
- [x] T5.2 — Nuevo `NotificationSendRequest` (schema)
- [x] T5.3 — Nuevo `DashboardResponse` (schema)
- [x] T5.4 — `query_service.py`: llama a `history_service.record_activity(...)` tras `run_query`

## Bloque 6 — Nuevas rutas de API
- [x] T6.1 — `backend/app/api/routes/dashboard.py`: `GET /dashboard`
- [x] T6.2 — `backend/app/api/routes/notifications.py`: `POST /notifications/send`
- [x] T6.3 — Registrados ambos routers en `backend/app/api/app.py`. Verificado funcionalmente con `TestClient`: `/api/health`, `/api/dashboard` y `/api/notifications/send` responden 200

## Bloque 7 — Frontend
- [x] T7.1 — `frontend/src/components/ChatPanel.jsx`: formulario migrado + historial de intercambios (burbujas usuario/sistema) + tarjetas de `draft_notifications` con botón "Enviar" (llama a `/api/notifications/send`)
- [x] T7.2 — `frontend/src/components/DashboardPanel.jsx`: tiles de métricas + lista de actividad reciente (vuelos en riesgo resaltados con `risk-badge`)
- [x] T7.3 — `frontend/src/App.jsx`: shell con pestañas "Chat" / "Panel de estado"; nuevo `frontend/src/api.js` con `API_BASE_URL` compartido
- [x] T7.4 — `frontend/src/styles.css`: estilos de pestañas, burbujas de chat, tarjetas de notificación, tiles de métricas, actividad reciente. `npx vite build` verificado sin errores.

## Bloque 8 — Tests
- [x] T8.1 — Reescrito `tests/integration/test_communication_agent.py`: mock de `with_structured_output` (ya no `bind_tools`); casos de `draft_notifications` (ninguno / solo operador / operador+pasajero); una sola llamada LLM; modo degradado; error
- [x] T8.2 — `tests/unit/test_state.py`: `NotificationDraft`; `initial_state` con `draft_notifications=[]`
- [x] T8.3 — Nuevo `tests/unit/test_history_service.py`: `record_activity`/`get_recent_activity`/`get_metrics`, tope de 50
- [x] T8.4 — Nuevo `tests/integration/test_api_routes.py` (`TestClient`): smoke tests de `/api/health`, `/api/query` (incluye `draft_notifications` y propagación de `optimization_criterion`), `/api/dashboard`, `/api/notifications/send`
- [x] T8.5 — Suite completa ejecutada: **177 passed, 1 failed** (mismo fallo preexistente de `get_delay_by_hour`, no relacionado). Además se detectó y corrigió una regresión real: `tests/integration/test_supervisor.py` todavía mockeaba `communication_agent` con el patrón `bind_tools` ya eliminado — corregido a `with_structured_output`

## Bloque 9 — Validación manual y cierre
- [ ] T9.1 — Validación manual: frontend completo (chat + panel + botón de envío) de extremo a extremo (alcance a confirmar con el usuario, como en los evolutivos anteriores)
- [ ] T9.2 — Generar `refactor-agente-comunicacion-review.html` (sigue bloqueado: `docs/templates/review-template.html` no existe)
- [ ] T9.3 — Resumen final en `99_devlog.md` y cierre del evolutivo
