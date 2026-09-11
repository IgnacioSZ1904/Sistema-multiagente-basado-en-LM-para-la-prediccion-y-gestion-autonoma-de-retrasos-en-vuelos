# Devlog: explorador-rutas-aeropuertos

---

## [2026-09-08] — Inicio del evolutivo
- Carpeta creada en `docs/features/explorador-rutas-aeropuertos`
- Origen: el usuario señaló que el chat no permite visualizar datos de vuelos, obligando a "preguntar a ciegas"; tras valorar varias opciones (panel de metadatos, explorador de datos completo, aprovechar datos estructurados ya devueltos por `/api/query`), se decidió empezar por una opción acotada: listado de aeropuertos de origen con destinos alcanzables al seleccionar uno.
- Verificado el esquema real de la tabla `flights` en DuckDB (`DESCRIBE flights`): no existe columna de código IATA, solo `OriginCityName`/`DestCityName` como texto.
- Se preguntó al usuario cómo resolver el requisito de "código de aeropuerto" dado que los datos no lo contienen; decisión: se descarta el código, el widget mostrará solo nombre de ciudad.
- Análisis iniciado y redactado en `01_analisis.md`.

## [2026-09-08] — Análisis validado y planificación redactada
- Usuario respondió las 3 preguntas abiertas directamente en `01_analisis.md`: buscador/filtro de texto sí necesario, widget al lado derecho del chat, orden alfabético. Actualizadas §4, §6 y la tabla de riesgos de `01_analisis.md` en consecuencia.
- Redactada `02_planificacion.md`: endpoint único `GET /api/routes` (mapa completo origen→destinos, cacheado en memoria en el backend), nuevo `routes_service.py`, nuevo componente `RouteExplorer.jsx` a la derecha del chat, filtrado client-side.
- Riesgo de rendimiento anotado: la tabla `flights` es de gran volumen (según lo documentado en `prediccion-ml-real`), por lo que el cacheo en memoria tras el primer cálculo es la mitigación elegida.

## [2026-09-08] — Planificación validada y desglose de tareas redactado
- Redactada `03_tareas_pendientes.md`: 5 bloques (preparación, backend, frontend, pruebas, cierre), 13 tareas atómicas.
- T5.1 incluida explícitamente para replantear con el usuario el bloqueo de `review-template.html` antes de generar el HTML de cierre, en vez de asumir una solución.

## [2026-09-08] — Bloques 1-4 ejecutados
- T1.1: confirmado el patrón de conexión (`duckdb.connect(Settings.DB_PATH, read_only=True)`, usado en `tools/analytical_tools.py`), reutilizado tal cual en `routes_service.py`.
- T1.2: medido el tiempo real de la consulta `DISTINCT` sobre `flights` (30.132.672 filas): 0,39s, 382 orígenes, 7.644 pares origen-destino. Confirma que el cacheo en memoria es barato de mantener aunque no sea estrictamente imprescindible por rendimiento.
- T2.1-T2.4: creado `backend/app/services/routes_service.py` (cacheo con variable de módulo `_cache`, mismo patrón que `history_service._history`), `RoutesResponse` en `backend/app/schemas.py`, y `backend/app/api/routes/flight_routes.py` registrado en `app.py` bajo `GET /api/routes`. Nombrado `flight_routes.py` (no `routes.py`) para no colisionar con el directorio `backend/app/api/routes/`.
- T3.1-T3.5: creado `frontend/src/components/RouteExplorer.jsx`. Se refactorizó `ChatPanel.jsx` para que ya no posea su propio `<section className="grid">` — ahora `App.jsx` es quien compone el grid de dos columnas con `<ChatPanel />` y `<RouteExplorer />` como hijos, igual que `DashboardPanel` ya poseía su propio grid de dos tarjetas. Estilos añadidos en `styles.css` reutilizando la paleta y patrones existentes (sin librerías nuevas).
- T4.1: `tests/unit/test_routes_service.py` (4 tests) contra un DuckDB temporal pequeño, no el dataset real — verifica deduplicación, orden alfabético, exclusión de destino nulo y cacheo.
- T4.2: añadido `TestRoutesRoute` en `tests/integration/test_api_routes.py`.
- Suite completa ejecutada (`pytest tests/`): 225 passed, 1 deselected. Dos fallos preexistentes NO relacionados con este evolutivo, dejados sin tocar (fuera de alcance):
  1. `test_dashboard_returns_empty_state_when_no_activity` — falla por un log de notificaciones real ya presente en disco (`data/notifications_log/`, ya aparecía como "untracked" en git antes de empezar este evolutivo), no por código de este evolutivo.
  2. `test_hours_are_in_valid_range` — es el bug de redondeo de `CAST(x/100 AS INTEGER)` en DuckDB, ya documentado y explícitamente dejado sin corregir en `prediccion-ml-real/04_lecciones_aprendidas.md`.
- T4.3 (validación manual en navegador): el agente no puede abrir un navegador real en este entorno (se intentó con Playwright/chromium-cli, ninguno disponible sin instalación pesada; además `curl`/PowerShell desde las herramientas del agente no alcanzan de forma fiable `localhost` donde escuchan los servidores nativos de Windows, aunque `vite` y `uvicorn` sí arrancan correctamente). Se paró el backend/frontend que había arrancado el agente (puertos 8000/5173/5174) y el usuario los arrancó él mismo para validar.

## [2026-09-08] — T4.3 validada por el usuario; Bloque 4 completo
- El usuario confirma que la validación manual funciona correctamente (carga del listado a la derecha del chat, filtro, selección de destinos).
- Bloques 1-4 completos. Queda pendiente el Bloque 5 (cierre): decidir con el usuario cómo proceder con `docs/templates/review-template.html` (no existe) antes de generar el HTML de revisión.

## [2026-09-08] — Cierre del evolutivo
- Se preguntó al usuario cómo proceder con el HTML de revisión (T5.1): decisión = omitirlo por esta vez, sin generar estilos ad-hoc.
- T5.2 (generar `explorador-rutas-aeropuertos-review.html`) queda explícitamente omitida por esa decisión, no marcada como completada.
- Evolutivo `explorador-rutas-aeropuertos` cerrado: widget "Rutas disponibles" a la derecha del chat, con buscador y listas alfabéticas de origen→destino, respaldado por `GET /api/routes` (cacheado en memoria) y validado manualmente por el usuario en navegador.
- Es la segunda vez consecutiva (tras `prediccion-ml-real`) que un evolutivo se cierra sin HTML de revisión por falta de plantilla — señal de que crear `docs/templates/review-template.html` sería un buen candidato para un evolutivo `meta-*` futuro, si el usuario lo considera prioritario.
