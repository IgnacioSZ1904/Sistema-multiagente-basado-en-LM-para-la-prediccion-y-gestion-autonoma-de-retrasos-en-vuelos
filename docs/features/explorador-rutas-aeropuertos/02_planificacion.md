# Planificación: explorador-rutas-aeropuertos

## 1. Enfoque técnico
Se añade un endpoint de solo lectura (`GET /api/routes`) que calcula, mediante una única consulta de agregación sobre la tabla `flights` en DuckDB, el conjunto de ciudades de origen distintas y, para cada una, las ciudades de destino distintas alcanzables desde ella. El resultado se cachea en memoria en el backend tras el primer cálculo (los datos son estáticos: se ingestan una vez desde el parquet, no cambian en caliente), de forma que el frontend recibe el mapa completo origen→destinos en una sola llamada al montar la página, sin round-trips adicionales al seleccionar un origen.

En el frontend, un nuevo componente (`RouteExplorer.jsx`) se coloca en `App.jsx` a la derecha del chat (layout de dos columnas), con un campo de texto que filtra la lista de orígenes en tiempo real (cliente, sin llamadas de red por tecleo) y, al seleccionar un origen, una segunda lista con sus destinos, ambas ordenadas alfabéticamente. El componente es autocontenido y no se comunica con `ChatPanel.jsx` ni con el estado del chat.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| Un único endpoint `GET /api/routes` que devuelve el mapa completo `{origins: [...], routes: {origen: [destinos]}}`, en vez de un endpoint de orígenes + un endpoint de destinos-por-origen bajo demanda | (a) Dos endpoints REST separados, con una llamada de red cada vez que se selecciona un origen | El dataset de referencia es estático y de tamaño acotado (cientos de ciudades, no miles), así que traerlo entero de una vez evita N llamadas de red, hace el filtrado y la selección instantáneos en el cliente, y simplifica el backend a una sola query. Si en el futuro el volumen de ciudades creciera mucho, tocaría revisar este enfoque (paginación o carga bajo demanda) — no es el caso con los datos actuales. |
| Cachear el resultado en memoria en el backend (calculado una vez, reutilizado en peticiones sucesivas) | Consultar DuckDB en cada request a `/api/routes` | La tabla `flights` tiene un volumen considerable (del orden de decenas de millones de filas, según lo documentado al entrenar el modelo en `prediccion-ml-real`); recalcular el `GROUP BY` en cada carga de página sería un coste repetido innecesario sobre datos que no cambian entre ingestas. |
| Nuevo módulo de servicio `backend/app/services/routes_service.py`, junto a `query_service.py` / `history_service.py`, en vez de una tool de `tools/analytical_tools.py` | Añadir esto como una tool más invocable por el LLM | No es una consulta que deba invocar el agente analítico ni pasar por el grafo de agentes: es un dato de referencia estático para poblar la UI directamente, análogo a lo que ya hace `history_service.py` para el panel de estado. Mantener la separación entre "tools del agente" y "servicios de la API" evita mezclar responsabilidades. |
| Filtrado del listado de orígenes en el cliente (JavaScript sobre el array ya cargado), no en el servidor | Endpoint con parámetro de búsqueda (`?q=...`) que filtre en SQL | Con el mapa completo ya en memoria del navegador, filtrar client-side es instantáneo y no añade latencia de red por cada tecla pulsada; el volumen de datos (nombres de ciudad) es pequeño para el navegador. |

## 3. Cambios por módulo

### `backend/app/services/`
- Nuevo fichero `routes_service.py`: función que ejecuta la consulta de agregación sobre `flights` (origen, destino distintos) contra `data/analytical_db.duckdb`, ordena alfabéticamente, construye el mapa `{origins, routes}` y lo cachea en memoria (variable de módulo, recalculada solo si no existe).

### `backend/app/api/`
- `app.py`: nueva ruta `GET /api/routes` que delega en `routes_service` y devuelve el mapa como JSON.

### `backend/app/schemas.py` (si aplica según convenciones ya usadas para `QueryResponse`)
- Nuevo modelo de respuesta (`RoutesResponse` o similar) con `origins: list[str]` y `routes: dict[str, list[str]]`, siguiendo el mismo patrón que `QueryResponse`.

### `frontend/src/components/`
- Nuevo fichero `RouteExplorer.jsx`: hace `fetch('/api/routes')` al montar, mantiene estado local de texto de filtro y origen seleccionado, renderiza lista de orígenes filtrada + lista de destinos del origen seleccionado. Sin dependencias externas nuevas (mismo criterio que el resto del frontend, que no usa librerías de tablas/gráficas).

### `frontend/src/`
- `App.jsx`: se ajusta el layout de la pestaña "Chat" para colocar `<RouteExplorer />` a la derecha de `<ChatPanel />` (dos columnas), sin tocar la pestaña "Panel de estado" ni `DashboardPanel.jsx`.

## 4. Modelo de datos / contratos

**`GET /api/routes`** — sin parámetros, respuesta `200 OK`:

```json
{
  "origins": ["Albany, NY", "Albuquerque, NM", "Atlanta, GA", "..."],
  "routes": {
    "Albany, NY": ["Atlanta, GA", "Chicago, IL", "..."],
    "Albuquerque, NM": ["Denver, CO", "Phoenix, AZ", "..."]
  }
}
```

- `origins`: todas las `OriginCityName` distintas de `flights`, ordenadas alfabéticamente.
- `routes[origen]`: todas las `DestCityName` distintas alcanzadas desde ese origen, ordenadas alfabéticamente.
- No incluye estadísticas de retraso, frecuencia ni ningún dato agregado adicional — solo existencia de la ruta (fuera de alcance según `01_analisis.md`).

## 5. Plan de pruebas
- **Unitario (backend)**: test de `routes_service` con una fixture pequeña de filas simuladas (o una tabla DuckDB en memoria de prueba) que verifique: orígenes sin duplicados y ordenados alfabéticamente, destinos por origen sin duplicados y ordenados, y que la caché no vuelve a golpear la BD en una segunda llamada.
- **Integración (backend)**: test con `TestClient` de FastAPI sobre `GET /api/routes` verificando código `200` y las claves `origins`/`routes` en la forma esperada.
- **Validación manual (frontend)**, dado que el frontend no tiene tests automatizados (decisión ya documentada en el proyecto):
  1. Cargar la página y comprobar que la lista de orígenes aparece a la derecha del chat, ordenada alfabéticamente.
  2. Escribir en el buscador y comprobar que la lista se filtra en tiempo real.
  3. Seleccionar un origen y comprobar que aparecen sus destinos, ordenados alfabéticamente.
  4. Con las herramientas de red del navegador, confirmar que seleccionar un origen/destino no dispara ninguna llamada a `/api/query`.
  5. Confirmar visualmente que no se muestra ningún código de aeropuerto, solo nombres de ciudad.

## 6. Plan de despliegue / migración
No aplica: no hay cambios de esquema de datos ni migración. El endpoint nuevo es aditivo (no modifica rutas existentes) y el componente de frontend es aditivo dentro de la pestaña "Chat" ya existente.

## 7. Estimación de complejidad
- Nº aproximado de tareas: 9
- Áreas de mayor incertidumbre:
  - Coste real de la consulta de agregación sobre el volumen completo de `flights` (potencialmente varias decenas de millones de filas) — mitigado por el cacheo en memoria, pero conviene medir el tiempo de la primera carga.
  - Formato exacto del nombre de ciudad en los datos (posibles variantes/duplicados de grafía) podría hacer que la lista tenga entradas que parezcan redundantes al ojo humano; no se normaliza en este evolutivo (ya reflejado como riesgo aceptado en `01_analisis.md`).
