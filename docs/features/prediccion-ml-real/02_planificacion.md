# Planificación: prediccion-ml-real

## 1. Enfoque técnico

El heurístico SQL actual de `_derive_delay_prediction` se sustituye por dos modelos scikit-learn entrenados **offline** sobre el histórico completo (`data/analytical_db.duckdb`, 30,1M vuelos): un **regresor multi-salida** (Random Forest) que predice `expected_dep_delay_min`/`expected_arr_delay_min`, y un **clasificador multiclase** (Random Forest) que predice `main_cause`. `is_disruption` no necesita un tercer modelo: se sigue derivando de forma determinista aplicando `Settings.DELAY_THRESHOLD_MINUTES` sobre la predicción de retraso en llegada, exactamente igual que hoy, solo que alimentado por el modelo en vez de por una media SQL. `confidence` deja de basarse en `sample_size` y pasa a expresar la incertidumbre real del regresor, calculada a partir de la dispersión entre las predicciones de los árboles individuales del Random Forest.

El entrenamiento vive en un script independiente (`data/train_delay_model.py`, mismo patrón que `data/data_ingestion.py`), ejecutado manualmente una vez, que serializa un único artefacto (`data/models/delay_model.joblib`) con los modelos, los codificadores de categorías y metadatos. `analytical_agent.py` carga ese artefacto de forma perezosa (una vez por proceso) y lo usa en inferencia; si el artefacto no existe o falla la carga, cae automáticamente al heurístico SQL actual (mismo patrón de modo degradado que ya existe en el proyecto para "Ollama no disponible"). El contrato `DelayPrediction` (graph/state.py) no cambia de forma, así que `disruption_agent` y `communication_agent` no requieren ningún cambio.

## 2. Decisiones de diseño

| Decisión | Alternativas consideradas | Justificación |
|----------|---------------------------|----------------|
| Un modelo por tarea: regresor multi-salida (dep+arr delay) + clasificador de causa. `is_disruption` se deriva del umbral existente, sin modelo propio. | Un único modelo multi-tarea (red neuronal); tres modelos independientes (uno por campo) | El usuario pidió "como sea más eficiente": menos modelos que entrenar/mantener, sin sacrificar señal — `is_disruption` no aporta nada nuevo sobre el umbral ya validado en producción. |
| Algoritmo: Random Forest (regresor + clasificador), ambos de scikit-learn. | Regresión lineal/logística (más simple, peor con no linealidades); gradient boosting (xgboost/lightgbm, mejor rendimiento pero dependencia nueva y más pesada) | Robusto sin apenas ajuste de hiperparámetros, soporta features mixtas (categóricas + numéricas), da incertidumbre "gratis" vía dispersión entre árboles, 100% CPU y dentro de scikit-learn (librería ya aceptada por el usuario). |
| `confidence` = función de la dispersión entre árboles del regresor, normalizada a [0,1]. | Probabilidad del clasificador; mantener `sample_size` como complemento | El usuario pidió explícitamente "medida de incertidumbre", no soporte muestral. |
| Split temporal: entrenar con 2018-2022, evaluar con 2023. | Split aleatorio (k-fold) | Evita fuga de información entre vuelos muy correlacionados (misma ruta/día/temporada) y simula el caso de uso real: predecir sobre datos futuros, no interpolar dentro del mismo periodo. |
| Fallback automático al heurístico SQL si el artefacto del modelo no existe o no carga. | Eliminar el heurístico por completo | Mismo patrón ya usado en el proyecto (modo degradado sin Ollama); evita dejar el sistema sin predicción si el modelo no se ha entrenado todavía, y mantiene una red de seguridad mientras se valida el nuevo camino. |
| Feature `distance` se obtiene por lookup determinista (distancia media histórica de la ruta) si no viene en `flight_context`, no se le pide al operador. | Exigir que el operador la proporcione en la consulta | El operador nunca aporta distancia hoy; mantiene la interfaz de consulta actual intacta, y es un dato prácticamente constante por ruta. |
| `day_of_week` queda **fuera** del conjunto de features de esta primera versión. | Exigir fecha completa en la consulta para poder calcularlo | `flight_context` solo captura el mes, no el día exacto; abrir esto implicaría cambiar la interfaz de consulta, no solicitado en este evolutivo — se deja como mejora futura. |
| El contrato `DelayPrediction` (graph/state.py) no cambia de forma. | Añadir campos nuevos (p. ej. probabilidades por causa) | Cero impacto en `disruption_agent`/`communication_agent`; el cambio queda contenido en `analytical_agent`, respetando la lección de `refactor-agente-analitico` (no reabrir quién es dueño de qué). |

## 3. Cambios por módulo

### `data/train_delay_model.py` (nuevo)
- Lee `flights` desde `analytical_db.duckdb` (vía DuckDB, reutilizando `Settings.DB_PATH`).
- Construye el dataset de entrenamiento: features (airline, origin, destination, month, scheduled_dep_hour, distance) + targets (`DepDelayMinutes`, `ArrDelayMinutes` para el regresor; causa dominante por fila — mismo cálculo de argmax que hoy hace el SQL de `get_flight_historical_stats`, pero aplicado por vuelo individual — para el clasificador).
- Codifica categóricas de alta cardinalidad (`airline`, `origin`, `destination`) con `OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)` para poder manejar en inferencia rutas/aerolíneas no vistas en entrenamiento sin excepción.
- Split temporal 2018-2022 (train) / 2023 (test).
- Entrena `RandomForestRegressor` (multi-output) y `RandomForestClassifier`.
- Calcula métricas sobre el test: MAE/RMSE por salida del regresor, accuracy/F1 macro del clasificador — y las compara contra el heurístico actual recalculado sobre el mismo test set, como baseline.
- Serializa con `joblib.dump(...)` un único diccionario a `data/models/delay_model.joblib`: `regressor`, `classifier`, `encoders`, `feature_columns`, `label_classes`, `trained_at`, `dataset_row_count`, `metrics`.
- Imprime un resumen por consola (mismo estilo que `data_ingestion.py`).

### `agents/analytical_agent.py`
- `_derive_delay_prediction_heuristic(...)`: la función actual, renombrada, se conserva tal cual como fallback.
- `_load_delay_model()`: carga perezosa y cacheada (a nivel de módulo) del artefacto desde `Settings.DELAY_MODEL_PATH`; devuelve `None` si no existe o falla la carga (con log de warning, sin excepción propagada).
- `_lookup_route_distance(origin, destination)`: función determinista, consulta directa a DuckDB (no expuesta como `@tool`, igual que `_ensure_cascade_risk_context`) para obtener la distancia media histórica de la ruta cuando no viene en `flight_context`.
- `_build_model_features(flight_context)`: construye el vector de features codificado a partir de `flight_context` + `_lookup_route_distance`.
- `_derive_delay_prediction_ml(flight_context, stats)`: ejecuta la inferencia (regresor + clasificador), calcula `confidence` a partir de la dispersión entre árboles, y aplica el umbral existente para `is_disruption`.
- `_derive_delay_prediction(...)` pasa a ser un despachador: si `_load_delay_model()` devuelve un modelo válido, usa `_derive_delay_prediction_ml`; si no, usa `_derive_delay_prediction_heuristic`. Loguea cuál de los dos caminos se ha usado.

### `config/settings.py` / `.env.example`
- Nueva variable `DELAY_MODEL_PATH` (default `data/models/delay_model.joblib`).

### `requirements.txt` / `backend/requirements.txt`
- Añadir `scikit-learn>=1.4.0`.

### `.gitignore`
- Añadir `data/models/` (artefacto generado localmente, igual que el `.duckdb` y el `.parquet`).

### Tests
- `tests/integration/test_analytical_agent.py`: la clase de tests de `_derive_delay_prediction` se reescribe para cubrir ambos caminos (ML con un artefacto de prueba pequeño/mockeado, y fallback heurístico sin artefacto), en vez de testear solo la fórmula heurística concreta.
- `tests/unit/test_delay_model.py` (nuevo): entrena un modelo de juguete sobre una muestra sintética reducida (no el dataset de 30M filas) y verifica de punta a punta el pipeline de features + inferencia + manejo de categorías no vistas, para que la suite siga siendo rápida y no dependa de `analytical_db.duckdb`.

### Documentación
- `docs/features/prediccion-ml-real/model_evaluacion.md` (nuevo, generado en la fase de ejecución): métricas reales del modelo vs. heurístico, análogo a `benchmark_resultados.md` de `reducir-tiempo-ejecucion`.
- `README.md`: nueva sección breve sobre cómo entrenar el modelo (`python data/train_delay_model.py`), junto al paso existente de `data_ingestion.py`.

## 4. Modelo de datos / contratos

- `graph/state.py::DelayPrediction`: sin cambios de shape. Se actualiza el docstring para reflejar que `main_cause`/`confidence`/los retrasos esperados vienen de un modelo entrenado (con fallback heurístico), no de una fórmula fija.
- Artefacto `data/models/delay_model.joblib` (diccionario serializado con `joblib`):
  - `regressor`: `RandomForestRegressor` multi-salida (dep, arr delay en minutos).
  - `classifier`: `RandomForestClassifier` (5 clases de causa).
  - `encoders`: `dict[str, OrdinalEncoder]` por columna categórica.
  - `feature_columns`: lista ordenada de columnas de entrada.
  - `label_classes`: clases del clasificador en el orden de `predict_proba`.
  - `trained_at`, `dataset_row_count`, `metrics` (MAE/RMSE, accuracy/F1, y los mismos valores para el heurístico como baseline).
- Nueva variable de entorno: `DELAY_MODEL_PATH`.

## 5. Plan de pruebas

- **Unit**: encoding de categorías no vistas (no lanza excepción, usa el valor "unknown" configurado); cálculo de `confidence` a partir de una dispersión simulada entre árboles; derivación de `is_disruption` a partir del umbral existente aplicado a una predicción ML simulada.
- **Unit**: pipeline de entrenamiento (`train_delay_model.py`) ejecutado como función importable sobre un dataset sintético pequeño, no sobre las 30M filas reales — debe producir un artefacto válido y métricas coherentes.
- **Integración**: `test_analytical_agent.py` reescrito, cubriendo camino ML feliz y camino fallback; se verifica que el resto del grafo (`disruption_agent`, `communication_agent`) sigue funcionando sin cambios, porque el contrato no varía.
- **Validación manual**: recalcular `delay_prediction` con el modelo para las mismas 2-3 consultas de ejemplo usadas en `reducir-tiempo-ejecucion` (vuelo DL JFK→ATL, consulta exploratoria) y registrar en el devlog los valores heurístico vs. modelo, como evidencia para la memoria del TFG. Sin umbral de aceptación estricto (pregunta 6 resuelta en el análisis), pero sí documentado.
- **Rendimiento**: medir el tiempo de inferencia del modelo (objetivo: milisegundos) y registrarlo, para no reabrir `reducir-tiempo-ejecucion`.

## 6. Plan de despliegue / migración

- **Pasos previos**: `pip install -r requirements.txt` (nueva dependencia `scikit-learn`); ejecutar `python data/train_delay_model.py` una vez para generar el artefacto, igual que ya se hace con `data_ingestion.py`.
- **Pasos durante**: ningún cambio de esquema de estado ni de API pública; el cambio queda contenido dentro de `analytical_agent`. No requiere migración de datos existentes.
- **Rollback**: si el artefacto no existe o falla la carga, el sistema cae automáticamente al heurístico actual — no existe un "modo roto" posible por diseño (decisión de fallback de la sección 2).

## 7. Estimación de complejidad

- Nº aproximado de tareas: 16-18 (se detallan en `03_tareas_pendientes.md`).
- Áreas de mayor incertidumbre: calibración concreta de la fórmula de `confidence` (puede necesitar ajuste tras observar la dispersión real entre árboles); encoding robusto de categorías de alta cardinalidad (`origin`/`destination`, miles de valores distintos) sin explotar la dimensionalidad ni fallar ante rutas nuevas en producción.
