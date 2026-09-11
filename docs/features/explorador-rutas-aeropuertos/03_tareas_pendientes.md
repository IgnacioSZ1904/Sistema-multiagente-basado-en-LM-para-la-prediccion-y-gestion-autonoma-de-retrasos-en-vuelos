# Tareas pendientes: explorador-rutas-aeropuertos

> Estado: 🟢 Completado (HTML de revisión omitido por decisión del usuario, ver T5.1/T5.2)
> Última actualización: 2026-09-08

## Bloque 1 — Preparación
- [x] T1.1 — Revisar cómo se conectan a DuckDB `tools/analytical_tools.py` y/o `query_service.py` para reutilizar el mismo patrón de conexión en el nuevo `routes_service.py` (no inventar uno distinto)
- [x] T1.2 — Medir el tiempo real de una consulta `SELECT DISTINCT OriginCityName, DestCityName FROM flights` sobre la tabla completa, para confirmar si el cacheo en memoria (§2 de `02_planificacion.md`) es necesario desde el principio o se puede simplificar

## Bloque 2 — Implementación backend
- [x] T2.1 — Crear `backend/app/services/routes_service.py` con la función que consulta `flights`, deduplica, ordena alfabéticamente orígenes y destinos-por-origen, y construye el mapa `{origins, routes}`
- [x] T2.2 — Añadir cacheo en memoria del resultado en `routes_service.py` (calculado una sola vez, reutilizado en llamadas sucesivas)
- [x] T2.3 — Añadir modelo de respuesta (`RoutesResponse` o equivalente) en `backend/app/schemas.py`, siguiendo el patrón de `QueryResponse`
- [x] T2.4 — Añadir ruta `GET /api/routes` en `backend/app/api/app.py` que delega en `routes_service` y devuelve el modelo de T2.3

## Bloque 3 — Implementación frontend
- [x] T3.1 — Crear `frontend/src/components/RouteExplorer.jsx`: `fetch('/api/routes')` al montar, estado de carga/error, estado de texto de filtro y de origen seleccionado
- [x] T3.2 — Implementar el filtro de texto client-side sobre la lista de orígenes (sin llamadas de red por tecleo)
- [x] T3.3 — Implementar la lista de destinos correspondiente al origen seleccionado (ordenada alfabéticamente, tal como llega de `routes[origen]`)
- [x] T3.4 — Integrar `<RouteExplorer />` en `frontend/src/App.jsx`, en la pestaña "Chat", a la derecha de `<ChatPanel />` (layout de dos columnas), sin tocar `DashboardPanel.jsx` ni la pestaña "Panel de estado"
- [x] T3.5 — Estilos del componente coherentes con el resto de la UI existente, sin introducir librerías nuevas

## Bloque 4 — Pruebas
- [x] T4.1 — Test unitario de `routes_service` (sin duplicados, orden alfabético en orígenes y en destinos por origen, la caché evita recalcular en la segunda llamada)
- [x] T4.2 — Test de integración de `GET /api/routes` con `TestClient` de FastAPI (código `200`, forma `{origins, routes}` esperada)
- [x] T4.3 — Validación manual en navegador siguiendo el checklist de `02_planificacion.md` §5: carga inicial ordenada alfabéticamente a la derecha del chat, filtro en tiempo real, destinos correctos al seleccionar un origen, confirmación (con herramientas de red del navegador) de que no se dispara ninguna llamada a `/api/query`, y ausencia visual de cualquier código de aeropuerto
  - Validada manualmente por el usuario, funciona correctamente.

## Bloque 5 — Cierre
- [x] T5.1 — Revisar con el usuario cómo proceder con el HTML de revisión de cierre, dado que `docs/templates/review-template.html` no existe (riesgo ya anotado en `01_analisis.md` y lección registrada en `prediccion-ml-real/04_lecciones_aprendidas.md`) — no generar estilos ad-hoc sin acuerdo explícito
  - Decisión del usuario: omitir el HTML de revisión por esta vez, sin inventar estilos ad-hoc.
- [ ] T5.2 — Generar `explorador-rutas-aeropuertos-review.html`
  - **Omitida por decisión explícita del usuario** (ver T5.1): no existe plantilla de referencia y se decidió no generar un HTML ad-hoc. No se marca como hecha porque no se ejecutó; se deja constancia de que el evolutivo se cierra sin este entregable, no por olvido.
