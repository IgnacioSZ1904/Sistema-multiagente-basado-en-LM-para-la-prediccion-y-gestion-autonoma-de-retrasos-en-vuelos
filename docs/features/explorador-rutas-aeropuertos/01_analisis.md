# Análisis: explorador-rutas-aeropuertos

## 1. Petición original
> "y no podriamos poner en la misma pagina que el chat una pequeña tabla con los distintos aeropuertos de salida y que al seleccionar te muestre las distintas rutas, es decir los destinos a los que puedes llegar desde ese aeropuerto?"
>
> "vamos a comenzar con el evolutivo, quiero que sea solo informativo, que muestre nombre de ciudad y codigo de aeropuerto, y quiero que este en la misma pagina junto al chat"
>
> (Aclaración posterior, tras comprobar que no existe columna de código IATA en los datos): "Sin código, solo nombre de ciudad".

## 2. Objetivo
Reducir la sensación de "preguntar a ciegas" en el chat del sistema, dando al usuario visibilidad previa sobre qué orígenes y destinos existen realmente en la base de datos de vuelos. Se añade un widget informativo (no interactivo con el chat) en la misma página, que lista los aeropuertos de origen disponibles y, al seleccionar uno, muestra los destinos alcanzables desde él, usando nombres de ciudad tal como están en los datos.

## 3. Estado actual del proyecto
- **Frontend**: React 18 + Vite (`frontend/`), sin librerías de tablas/gráficas. `frontend/src/App.jsx` organiza la página en pestañas ("Chat" y "Panel de estado"); el chat vive en `frontend/src/components/ChatPanel.jsx`.
- **Backend**: FastAPI (`backend/app/api/app.py`) con rutas `GET /api/health`, `POST /api/query`, `GET /api/dashboard`, `POST /api/notifications/send`. No existe ningún endpoint que exponga listados de aeropuertos/rutas.
- **Datos**: DuckDB en `data/analytical_db.duckdb`, tabla única `flights`. Columnas relevantes confirmadas por esquema real (`DESCRIBE flights`): `OriginCityName` y `DestCityName` (ambas `VARCHAR`, texto tipo "Chicago, IL"). **No existe ninguna columna de código IATA** (verificado directamente contra el esquema, no solo contra la documentación de `tools/analytical_tools.py`).
- **Capa de consultas existente**: `tools/analytical_tools.py` contiene 8 `@tool` de solo lectura pensadas para que el LLM las invoque (agregados sobre retrasos, aeropuertos, aerolíneas, rutas, causas), no para exponer listados crudos vía REST. No hay endpoint de "listar aeropuertos" ni "listar destinos por origen".
- **Componentes de UI existentes**: `DashboardPanel.jsx` (pestaña "Panel de estado") solo muestra métricas de uso del propio chatbot (nº consultas, notificaciones, actividad reciente), no datos de vuelos.
- **Tests**: el frontend no tiene tests automatizados (decisión ya documentada en `docs/memoria/notas-api-y-tests.md`); la complejidad de test se concentra en agentes/grafo/tools.

## 4. Alcance

### Dentro de alcance
- Nuevo endpoint de solo lectura en el backend para: (a) listar los `OriginCityName` distintos presentes en `flights`, y (b) dado un origen, listar los `DestCityName` distintos alcanzables desde él.
- Nuevo componente de frontend, visible en el lado derecho del chat (misma página, no en una pestaña aparte), con dos listas ordenadas alfabéticamente: aeropuertos de origen (ciudad) y, al seleccionar uno, destinos disponibles desde ese origen.
- Buscador/filtro de texto sobre la lista de orígenes (reduce la lista a medida que se escribe).
- El widget es puramente informativo: seleccionar un origen/destino no modifica el chat, no envía preguntas ni interactúa con `ChatPanel.jsx`.
- Mostrar nombre de ciudad tal como aparece en los datos (`OriginCityName`/`DestCityName`), sin código de aeropuerto.

### Fuera de alcance
- Código IATA de aeropuerto (se descarta explícitamente: la tabla no lo tiene, y una ciudad puede tener varios aeropuertos sin forma de distinguirlos en los datos actuales).
- Cualquier interacción entre el widget y el chat (autocompletar preguntas, disparar consultas al seleccionar una ruta, etc.).
- Filtros adicionales (por aerolínea, fecha, retraso medio de la ruta, etc.) — el widget muestra solo existencia de la ruta, no estadísticas.
- Paginación/búsqueda avanzada sobre la lista de aeropuertos (a valorar en "Preguntas abiertas" si la lista resulta muy larga).
- Un explorador de datos genérico o panel de metadatos más amplio (quedaría como evolutivo aparte si se decide más adelante).
- Generación del HTML de revisión de cierre — ver riesgo en la tabla de riesgos.

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| La lista de aeropuertos de origen puede ser larga (decenas/cientos de ciudades) | Media | Media | Resuelto: se incorpora buscador/filtro de texto sobre la lista de orígenes (ver §4 y §6) |
| `docs/templates/review-template.html` no existe (lección de `prediccion-ml-real`); ningún evolutivo ha completado nunca la fase de HTML de revisión | Alta | Baja (solo afecta al cierre, no a la funcionalidad) | Al llegar a la fase 5, plantear de nuevo al usuario cómo proceder (crear plantilla como tarea propia u omitir) en vez de inventar estilos |
| Los nombres de ciudad en los datos pueden tener variantes/duplicados poco intuitivos (mismo aeropuerto con distinta grafía) | Baja | Baja | Usar `DISTINCT` tal cual sobre los datos existentes; no se normalizan nombres en este evolutivo (fuera de alcance) |
| Frontend sin tests automatizados: no hay red de seguridad para regresiones en `ChatPanel`/`App.jsx` al integrar el nuevo widget | Media | Baja | Validación manual explícita en navegador antes de cerrar el evolutivo (coherente con la práctica ya establecida en el proyecto) |

## 6. Preguntas abiertas
- [x] ¿La lista de aeropuertos de origen necesita buscador/filtro de texto, o una lista simple (`<select>`/lista desplegable) es suficiente dado el volumen real de ciudades distintas? → **Sí, con buscador/filtro de texto.**
- [x] ¿El widget debe ir en una posición fija de la página (ej. barra lateral junto al chat) o encima/debajo del chat? → **Al lado derecho del chat.**
- [x] ¿Se ordenan las listas alfabéticamente, o por algún otro criterio (ej. frecuencia de vuelos)? → **Alfabéticamente.**

## 7. Criterios de aceptación
- [ ] Al cargar la página, se ve un listado de aeropuertos de origen (nombre de ciudad), ordenado alfabéticamente, en el lado derecho del chat, sin necesidad de hacer ninguna pregunta al chat.
- [ ] El listado de orígenes tiene un buscador/filtro de texto que reduce la lista a medida que se escribe.
- [ ] Al seleccionar un aeropuerto de origen, se muestra la lista de ciudades destino alcanzables desde ese origen según los datos de `flights`, también ordenada alfabéticamente.
- [ ] Los datos mostrados (orígenes y destinos) coinciden exactamente con los valores distintos presentes en la tabla `flights` (verificable con una consulta `DISTINCT` de control).
- [ ] Seleccionar un origen o destino no modifica el estado del chat ni dispara ninguna consulta a `/api/query`.
- [ ] No se muestra ningún código de aeropuerto (solo nombre de ciudad).
