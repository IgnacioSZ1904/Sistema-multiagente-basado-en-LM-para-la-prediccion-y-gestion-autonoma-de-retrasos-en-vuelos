# Planificación: refactor-agente-comunicacion

## 1. Enfoque técnico

**Comunicación agente**: se simplifica al mismo patrón ya aplicado a los otros dos agentes — una única llamada `with_structured_output`, sin bucle de tool-calling (redactar texto no requiere ninguna tool). La salida deja de ser solo `final_response: str`; gana un campo estructurado `draft_notifications: list[NotificationDraft]` con el contenido de notificación ya redactado (para operador siempre que hay `disruption_proposal`, y también para pasajero si `severity` es `"high"`/`"critical"`) — **sin enviarlas**. El envío deja de ser automático: es una acción explícita del operador desde el frontend (6.3), que llama a un nuevo endpoint que invoca `send_passenger_notification` bajo demanda.

**Historial y panel de estado (6.1 + 6.2)**: nada de memoria conversacional real en el grafo — cada consulta sigue siendo independiente en el backend (sin tocar supervisor ni prompts de routing). El "historial conversacional" vive solo en el frontend (estado de React, no persistente al recargar). El "panel de estado" se alimenta de un historial **en memoria del proceso backend** (lista acotada, últimas 50 consultas), nuevo módulo `history_service`, sin base de datos nueva — limitación de persistencia documentada explícitamente (se pierde al reiniciar el backend), igual que otras simulaciones ya existentes en el proyecto.

**Frontend**: se divide `App.jsx` en un layout de dos paneles con pestañas — "Chat" (formulario + historial de intercambios + tarjetas de notificación con botón "Enviar") y "Panel de estado" (métricas + actividad reciente), cada uno como componente separado para no inflar un único fichero.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| Historial del panel: lista en memoria del proceso backend (`history_service.py`), capada a 50 entradas, sin persistencia en disco | Persistir a SQLite/fichero; sin historial propio (solo notificaciones) | Confirmado en 6.2(a): simplicidad, sin infraestructura nueva; limitación de persistencia documentada como las demás simulaciones del TFG |
| "Interfaz conversacional" = historial visual en el frontend, backend sigue stateless por consulta | Memoria real en el grafo (supervisor + 3 agentes recordando turnos) | Confirmado en 6.1(b): el usuario prioriza no añadir complejidad; el caso de uso descrito no requiere memoria real si cada consulta es autocontenida |
| El agente de comunicación **redacta** notificaciones (`draft_notifications`) pero no las envía; nuevo endpoint `POST /api/notifications/send` para que el operador decida | Auto-enviar como hoy (solo a operador); auto-enviar también a pasajero | Confirmado en 6.3: "el operador tiene el poder" — se prepara el contenido, el envío (que ya solo es un log simulado) queda como acción explícita del operador |
| `communication_agent` gana `draft_notifications` estructurado en el estado, además de mantener `final_response: str` sin cambios | Envolver todo en un nuevo `communication_report` (incluyendo duplicar el texto); mantener solo `final_response` sin estructura | Decisión delegada al agente en 6.5: se sigue el patrón ya consistente de los otros dos agentes (JSON tipado) sin duplicar el texto ya existente en un envoltorio adicional — cambio mínimo que mantiene coherencia arquitectónica |
| Métricas del panel: nº consultas procesadas (histórico en memoria), nº disrupciones detectadas, distribución de severidades, nº notificaciones enviadas (operador/pasajero, desde el log persistente de `get_notification_history`) | Añadir más métricas ahora (tiempos de respuesta, tasa de acierto, etc.) | Confirmado en 6.4: empezar con el mínimo viable, iterar después si hace falta |
| `communication_agent` se simplifica a una única llamada LLM (sin `bind_tools`); `send_passenger_notification`/`get_notification_history` se invocan solo desde las rutas de la API, no desde el LLM | Mantener el bucle de tool-calling actual | Redactar contenido no requiere ninguna tool; coherente con la simplificación ya aplicada a `analytical_agent` y `disruption_agent` (menos llamadas LLM = más rápido y fiable) |
| Frontend dividido en componentes `ChatPanel.jsx` / `DashboardPanel.jsx` con pestañas en `App.jsx` | Todo en un único `App.jsx` (como hoy, pero mucho más grande) | El alcance de este evolutivo (chat + dashboard) es sustancialmente mayor que el formulario actual; separar en componentes evita un fichero difícil de mantener |
| El historial de chat del frontend NO persiste al recargar la página (vive solo en el estado de React de la sesión de navegador) | Persistir en `localStorage` | No se pidió explícitamente; mantenerlo simple por ahora, coherente con 6.1 ("no añadir más complejidad") |

## 3. Cambios por módulo

### `graph/state.py`
- Nuevo `TypedDict NotificationDraft`: `recipient_type` (`"operator"` \| `"passenger"` \| `"ground_staff"`), `channel`, `message`, `flight_reference`.
- `SGIDAState`: nuevo campo `draft_notifications: list[NotificationDraft]`, escrito por `communication_agent` (lista vacía si no aplica).
- `initial_state`: inicializa `draft_notifications=[]`.

### `prompts/communication_prompt.py`
- Reescrito para un único prompt de salida estructurada: instruye a producir `final_response` (mismas reglas actuales: resumir `analytics_result`/`delay_prediction`/`disruption_proposal`/`error`) y, adicionalmente, `draft_notifications`:
  - Si hay `disruption_proposal`: incluir un borrador para `"operator"` (tono interno/operativo, canal `"operator_dashboard"`).
  - Si además `severity` es `"high"`/`"critical"`: incluir también un borrador para `"passenger"` (tono cercano, sin jerga interna, canal `"email"`).
  - Dejar explícito que son BORRADORES pendientes de aprobación — el LLM no debe afirmar que ya se ha notificado a nadie.

### `agents/communication_agent.py`
- Se elimina el bucle de tool-calling (`bind_tools(COMMUNICATION_TOOLS)` + `_MAX_TOOL_CALLS`).
- Nuevo `CommunicationOutput(BaseModel)`: `final_response: str`, `draft_notifications: list[NotificationDraftModel]`.
- Única llamada `get_llm().with_structured_output(CommunicationOutput)` sobre el mismo bloque de contexto JSON ya construido por `_build_context_block`.
- El nodo devuelve `final_response`, `draft_notifications` y el `AIMessage` de traza (igual que antes, ahora sin pasar por tool-calling).
- Modo degradado / manejo de errores: mismo texto de fallback que hoy, `draft_notifications=[]`.

### `tools/communication_tools.py`
- Sin cambios funcionales. Se re-etiqueta en el docstring que ahora se invocan desde las rutas de la API (acción explícita del operador / lectura del panel), no desde el LLM.

### `backend/app/services/history_service.py` (nuevo)
- Lista en memoria (módulo-level), capada a 50 entradas.
- `record_activity(query, optimization_criterion, state) -> None`: guarda timestamp, query, criterio, `flight_context`, `delay_prediction`, `disruption_proposal`, `error`.
- `get_recent_activity(limit=20) -> list[dict]`.
- `get_metrics() -> dict`: `total_queries`, `total_disruptions`, `severity_distribution` (dict), derivados del historial en memoria.

### `backend/app/services/query_service.py`
- Tras obtener `state` de `run_query`, llama a `history_service.record_activity(...)` antes de construir `QueryResponse`.

### `backend/app/schemas.py`
- `QueryResponse`: añade `draft_notifications: list[dict] | None = None`.
- Nuevo `NotificationSendRequest(BaseModel)`: `recipient_type`, `message`, `flight_reference`, `channel`.
- Nuevo `DashboardResponse(BaseModel)`: `recent_activity: list[dict]`, `metrics: dict`, `notifications: list[dict]`.

### `backend/app/api/routes/dashboard.py` (nuevo)
- `GET /dashboard`: combina `history_service.get_recent_activity()` + `get_metrics()` + `get_notification_history` (tool, invocada directamente para leer el log persistente de notificaciones ya enviadas).

### `backend/app/api/routes/notifications.py` (nuevo)
- `POST /notifications/send`: invoca `send_passenger_notification` con el payload recibido; devuelve el resultado (status, notification_id, timestamp).

### `backend/app/api/app.py`
- Registra los 2 routers nuevos (`dashboard_router`, `notifications_router`) bajo el prefijo `/api`.

### Frontend
- `frontend/src/components/ChatPanel.jsx` (nuevo): formulario de consulta (ya existente, migrado) + lista de intercambios (usuario/sistema) + tarjetas de `draft_notifications` con botón "Enviar" (llama a `POST /api/notifications/send`).
- `frontend/src/components/DashboardPanel.jsx` (nuevo): tiles de métricas + tabla/lista de actividad reciente (vuelos en riesgo resaltados cuando `delay_prediction.is_disruption`).
- `frontend/src/App.jsx`: se reduce a shell con pestañas ("Chat" / "Panel de estado") + cabecera existente (hero, healthcheck).
- `frontend/src/styles.css`: estilos añadidos para pestañas, burbujas de chat, tarjetas de notificación, tiles de métricas (reutilizando `.card`/`.metric` donde sea posible).

### Tests
- `tests/integration/test_communication_agent.py`: reescritura — se mockea `with_structured_output` en vez de `bind_tools`; casos: `draft_notifications` vacío sin disrupción, borrador de operador cuando hay `disruption_proposal`, borrador adicional de pasajero cuando `severity` es alta/crítica, modo degradado, error capturado.
- `tests/unit/test_state.py`: `NotificationDraft`, `initial_state` con `draft_notifications=[]`.
- `tests/unit/test_history_service.py` (nuevo): `record_activity`/`get_recent_activity`/`get_metrics`, tope de 50 entradas.
- `tests/integration/test_api_routes.py` (nuevo, usando `fastapi.testclient.TestClient`): smoke tests de `/api/dashboard` y `/api/notifications/send`, y que `/api/query` sigue funcionando con el nuevo campo `draft_notifications`.

## 4. Modelo de datos / contratos

```python
# graph/state.py
class NotificationDraft(TypedDict):
    recipient_type: str      # "operator" | "passenger" | "ground_staff"
    channel: str              # "email" | "sms" | "push" | "operator_dashboard"
    message: str
    flight_reference: str
```

`SGIDAState.draft_notifications: list[NotificationDraft]` — siempre presente (lista vacía si no aplica).

```python
# backend/app/schemas.py (forma orientativa)
class NotificationSendRequest(BaseModel):
    recipient_type: str
    message: str
    flight_reference: str = ""
    channel: str = "email"

class DashboardResponse(BaseModel):
    recent_activity: list[dict]
    metrics: dict
    notifications: list[dict]
```

## 5. Plan de pruebas
- Unitarios de `history_service`: cap de 50, orden más-reciente-primero, `get_metrics` cuenta bien disrupciones/severidades.
- Integración de `communication_agent`: casos de `draft_notifications` (ninguno / solo operador / operador+pasajero), sin llamadas a tools (ya no las tiene).
- Smoke tests de API (`TestClient`) para los 2 endpoints nuevos y para que `/api/query` no rompa contratos existentes.
- Validación manual (a confirmar con el usuario, como en los evolutivos anteriores): abrir el frontend, lanzar varias consultas, comprobar el historial de chat, cambiar de pestaña al panel y ver que las métricas/actividad reciente se actualizan, y probar el botón "Enviar" de una notificación.

## 6. Plan de despliegue / migración
No aplica migración de datos. Cambios de contrato aditivos (`QueryResponse.draft_notifications` es un campo nuevo opcional). El historial en memoria se reinicia en cada despliegue/reinicio del backend — limitación conocida y documentada.

## 7. Estimación de complejidad
- Nº aproximado de tareas: ~28-32 (el evolutivo más grande hasta ahora, por el frontend de dos paneles y los 2 endpoints nuevos).
- Áreas de mayor incertidumbre:
  - Diseño visual concreto del panel de estado y del chat (se resuelve con CSS reutilizando las clases existentes, pero es la parte más subjetiva).
  - Si el LLM local, en una única llamada estructurada, redacta de forma fiable tonos distintos para operador vs pasajero dentro del mismo esquema — puede necesitar ajuste de prompt tras pruebas manuales.
