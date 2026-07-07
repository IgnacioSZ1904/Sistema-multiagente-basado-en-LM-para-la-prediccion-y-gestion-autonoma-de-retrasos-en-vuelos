# Análisis: refactor-agente-comunicacion

## 1. Petición original
> "ahora vamos a refactorizar el communication agent, este agente recoge la informacion de los otros dos agentes y es el que porfin expone la informacion y la muestra en lenguaje natural. las indicaciones mas concretas son las siguientes: responsable de traducir las decisiones del sistema a lenguaje natural comprensible, generando notificaciones o informes tanto para operadores como para pasajeros afectados. en esta interaccion tambien adaptaremos el frontend para cumplir con lo siguiente: Interfaz conversacional que permita a un operador interactuar con el sistema en lenguaje natural, consultando el estado de las operaciones o solicitando análisis específicos. Panel de visualización del estado del sistema, mostrando vuelos en riesgo, decisiones tomadas por los agentes y métricas de rendimiento global."

## 2. Objetivo
Refactorizar el Agente de Comunicación para que genere de forma explícita **tanto informes para el operador como notificaciones para pasajeros afectados** (hoy solo notifica al operador), y adaptar el frontend para cubrir dos capacidades nuevas: una **interfaz conversacional** (historial de intercambios en lenguaje natural, no un formulario de una sola consulta) y un **panel de estado del sistema** (vuelos en riesgo, decisiones de los agentes, métricas globales). Es el evolutivo de mayor alcance de frontend de los tres realizados hasta ahora.

## 3. Estado actual del proyecto

### Módulos / ficheros relevantes existentes
- `agents/communication_agent.py`: patrón de una sola fase (bucle acotado a 1-2 llamadas a `send_passenger_notification`, sin síntesis estructurada — la salida es directamente el texto de `final_response`). Ya serializa `analytics_result`/`delay_prediction`/`disruption_proposal` como JSON explícito en el prompt (tras el evolutivo `refactor-agente-analitico`).
- `prompts/communication_prompt.py`: instruye notificar (`send_passenger_notification`) únicamente a `"operator"` cuando `severity` es `"high"`/`"critical"`; **no** hay instrucción de notificar a `"passenger"` — la petición actual pide explícitamente generar también para pasajeros.
- `tools/communication_tools.py`: `send_passenger_notification` (ya soporta `recipient_type="passenger"|"operator"|"ground_staff"`, canal simulado, log a `data/notifications_log/notifications.jsonl`) y `get_notification_history` (recupera el historial — reutilizable directamente para alimentar el panel de estado).
- `graph/state.py`: `final_response: Optional[str]` es el único campo que escribe este agente; no hay ningún campo estructurado tipo `CommunicationReport` (a diferencia de `analytics_result`/`delay_prediction`/`disruption_proposal`, que sí siguen el patrón JSON tipado establecido en los dos evolutivos anteriores).
- `graph/supervisor.py` / `graph/router.py`: cada consulta (`run_query`) construye un `initial_state` nuevo y ejecuta el grafo de una vez; **no hay memoria conversacional entre consultas** — cada llamada a `/api/query` es independiente, sin contexto de intercambios anteriores.
- `backend/app/api/`: solo dos rutas, `/api/health` y `/api/query` (una consulta → una respuesta). No existe ningún endpoint de historial, dashboard o métricas.
- `backend/app/services/query_service.py`: capa fina que llama a `run_query` y mapea a `QueryResponse`; no persiste nada entre llamadas.
- `frontend/src/App.jsx`: formulario de una sola consulta (texto + selector de criterio ya añadido en el evolutivo anterior) con una sección de métricas puntuales (iteración, próximo nodo, disrupción sí/no) y un bloque de salida con el `final_response` de la ÚLTIMA consulta. No hay historial de mensajes, no hay panel de estado agregado, no hay ninguna llamada a `get_notification_history` desde el frontend.
- No existe ningún mecanismo de persistencia de "vuelos en riesgo" ni de "métricas de rendimiento global" más allá del log de notificaciones (`notifications.jsonl`) y de lo que cada `SGIDAState` contiene puntualmente durante su propia ejecución (se descarta al terminar la petición HTTP).

### Dependencias afectadas
- Cualquier historial/dashboard requiere que el backend **recuerde** algo entre peticiones HTTP — hoy no guarda nada (proceso sin estado más allá del log de notificaciones en disco). Hace falta decidir un mecanismo (ver preguntas abiertas).
- El frontend actual (`App.jsx`) se reescribe sustancialmente para pasar de "formulario de una consulta" a "interfaz conversacional + panel de estado" — mucho más cambio que el selector añadido en el evolutivo anterior.

### Configuración actual relacionada
- Ninguna variable de `Settings` relacionada con historial, retención de conversación o dashboard.

### Tests existentes que cubren el área
- `tests/integration/test_communication_agent.py`
- `tests/test_communication_tools.py`

## 4. Alcance

### Dentro de alcance
- `agents/communication_agent.py` / `prompts/communication_prompt.py`: generar también notificación para pasajeros (`recipient_type="passenger"`) cuando hay una disrupción relevante, no solo para el operador.
- Definir y exponer un mecanismo de historial/estado reciente del sistema (backend) para alimentar el panel — alcance exacto a resolver en preguntas abiertas.
- Nuevo endpoint de backend para servir ese estado agregado al frontend (p. ej. `/api/dashboard` o similar).
- Frontend: interfaz conversacional (historial de intercambios usuario/sistema) — alcance de "memoria real" vs "historial visual" a resolver en preguntas abiertas.
- Frontend: panel de estado del sistema (vuelos en riesgo, decisiones de los agentes, métricas globales), usando el nuevo endpoint.
- Tests correspondientes.

### Fuera de alcance
- Integración real con proveedores de email/SMS (ya documentado como limitación de TFG en `tools/communication_tools.py`; se mantiene simulado).
- Autenticación/autorización de operadores en el frontend.
- Persistencia en base de datos relacional/externa del historial (salvo que se decida lo contrario en preguntas abiertas); no se monta infraestructura nueva (Redis, Postgres, etc.) para esto.

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| "Interfaz conversacional" podría interpretarse como memoria conversacional real (el grafo recordando turnos anteriores), lo cual es un cambio arquitectónico grande (supervisor, estado, prompts de los 3 agentes) | Media | Alto | Aclarar en preguntas abiertas si "conversacional" es memoria real o solo un historial visual en el frontend sobre peticiones stateless (mucho más simple y de menor riesgo) |
| Sin un mecanismo de persistencia claro, "vuelos en riesgo"/"métricas globales" no tienen de dónde salir tras reiniciar el backend | Alta | Medio | Aceptar explícitamente una solución en memoria (no persistente entre reinicios) como limitación documentada del TFG, igual que ya se hace con otras simulaciones del proyecto |
| Alcance de frontend mucho mayor que en evolutivos anteriores (chat + dashboard) podría descontrolarse si no se acota con precisión qué componentes/vistas se construyen | Media | Medio | Desglosar en `02_planificacion.md` los componentes de UI concretos antes de programar nada |
| Enviar notificación automática a pasajeros en cada disrupción alta/crítica podría generar ruido si se prueba repetidamente en desarrollo | Baja | Bajo | Mantenerlo simulado (ya lo es); documentado como tal |

## 6. Preguntas abiertas

- [ ] **6.1 — ¿"Interfaz conversacional" implica memoria real entre consultas, o un historial visual sobre peticiones stateless?**
  - (a) **Memoria real**: el grafo recuerda turnos anteriores (habría que pasar historial de mensajes a los prompts de supervisor/agentes) — cambio grande, toca los 3 agentes + supervisor.
  - (b) **Historial visual (recomendado)**: cada consulta sigue siendo independiente en el backend (como hoy), pero el frontend mantiene y muestra la lista de intercambios (pregunta → respuesta) como un chat, y el operador puede referirse a contexto visualmente aunque el backend no "recuerde" — mucho más simple, menor riesgo, y ya cubre el caso de uso descrito ("consultar el estado... o solicitar análisis específicos", que no requiere memoria si cada pregunta es autocontenida).
  De momento historial visual, no queremos añadir mas complejidad

- [ ] **6.2 — Origen de datos para el panel de estado ("vuelos en riesgo", "decisiones de los agentes", "métricas de rendimiento global")**:
  - (a) **Historial en memoria del proceso backend (recomendado)**: cada vez que `run_query` termina, se guarda un resumen (timestamp, query, `delay_prediction`, `disruption_proposal`, severidad) en una lista acotada (p. ej. últimas 50), sin persistencia en disco; se pierde al reiniciar el backend (limitación documentada, como otras simulaciones del proyecto).
  - (b) Persistir a fichero/SQLite para sobrevivir reinicios.
  - (c) Sin historial propio: el panel solo muestra `get_notification_history` (que ya persiste a fichero) y no vuelos/predicciones si no hubo notificación.
  vamos con la opcion (a) de momento

- [ ] **6.3 — ¿Se envía notificación automática también a pasajeros, o solo se prepara el contenido y el operador decide enviarlo?** Propuesta: igual que hoy para "operator" (automático si severity alta/crítica), añadir un envío automático simulado también a "passenger" en esos mismos casos — ¿confirmas, o prefieres que sea manual/bajo confirmación?
se prepara el contenido, el operador tiene el poder 

- [ ] **6.4 — Alcance visual concreto del panel de estado**: ¿qué "métricas de rendimiento global" quieres ver exactamente? Propuesta mínima viable: nº de consultas procesadas en la sesión del backend, nº de disrupciones detectadas, distribución de severidades, nº de notificaciones enviadas (operador vs pasajero). ¿Añadimos/quitamos algo?
empezamos con esas luegosi eso las cambiamos

- [ ] **6.5 — ¿El agente de comunicación pasa a escribir también un campo estructurado en el estado** (p. ej. `communication_report` con el texto para operador + lista de notificaciones generadas), siguiendo el mismo patrón JSON ya aplicado a los otros dos agentes, o se mantiene `final_response: str` como único campo de salida (más simple, pero rompe la consistencia arquitectónica del resto del sistema)?
Este agente debe comunicarse con el operador a traves del frontend, dicho eso elige la opcion mas logica

## 7. Criterios de aceptación
- [ ] El agente de comunicación genera notificación tanto para operador como para pasajeros afectados cuando corresponde (no solo operador, como hoy).
- [ ] Existe un endpoint de backend que expone el estado agregado necesario para el panel (vuelos en riesgo / decisiones / métricas), documentando su alcance de persistencia.
- [ ] El frontend muestra un historial de intercambios en lenguaje natural (chat), no solo la última respuesta.
- [ ] El frontend tiene un panel de estado del sistema separado del chat, con al menos las métricas mínimas acordadas en 6.4.
- [ ] Tests actualizados y suite ejecutada (validación manual y cierre formal a confirmar con el usuario, como en los dos evolutivos anteriores).
