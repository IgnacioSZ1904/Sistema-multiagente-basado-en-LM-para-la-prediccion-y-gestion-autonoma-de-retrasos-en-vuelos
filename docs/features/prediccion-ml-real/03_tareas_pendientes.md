# Tareas pendientes: prediccion-ml-real

> Estado: 🟢 Completado (cerrado por el usuario; T6.3 queda como deuda pendiente — ver nota)
> Última actualización: 2026-07-27

## Bloque 1 — Preparación
- [x] T1.1 — Añadir `scikit-learn>=1.4.0` a `requirements.txt`/`backend/requirements.txt`.
- [x] T1.2 — Añadir `DELAY_MODEL_PATH` (default `data/models/delay_model.joblib`) a `config/settings.py` y `.env.example`.
- [x] T1.3 — Añadir `data/models/` a `.gitignore`.

## Bloque 2 — Pipeline de entrenamiento (`data/train_delay_model.py`)
- [x] T2.1 — Crear `data/train_delay_model.py`: carga de `flights` desde `analytical_db.duckdb` y construcción de features (airline, origin, destination, month, scheduled_dep_hour, distance) + cálculo de la causa dominante por vuelo individual (mismo criterio de argmax que hoy usa el SQL de `get_flight_historical_stats`, aplicado fila a fila).
- [x] T2.2 — Implementar encoding de categóricas de alta cardinalidad (`OrdinalEncoder` con `handle_unknown="use_encoded_value"`) y split temporal train (2018-2022) / test (2023).
- [x] T2.3 — Entrenar `RandomForestRegressor` multi-salida (dep+arr delay) y `RandomForestClassifier` (main_cause).
- [x] T2.4 — Calcular métricas sobre el test (MAE/RMSE del regresor, accuracy/F1 macro del clasificador) y compararlas contra el heurístico actual recalculado sobre el mismo test set, como baseline.
- [x] T2.5 — Serializar el artefacto con `joblib` a `data/models/delay_model.joblib` (regressor, classifier, encoders, feature_columns, label_classes, trained_at, dataset_row_count, metrics) e imprimir un resumen por consola (mismo estilo que `data_ingestion.py`).
- [x] T2.6 — Ejecutar el script sobre el dataset real, verificar que el artefacto se genera correctamente y registrar las métricas obtenidas en el devlog.

## Bloque 3 — Integración en `analytical_agent.py`
- [x] T3.1 — Renombrar la función heurística actual a `_derive_delay_prediction_heuristic` (se conserva tal cual, como fallback).
- [x] T3.2 — Implementar `_load_delay_model()`: carga perezosa y cacheada a nivel de módulo del artefacto desde `Settings.DELAY_MODEL_PATH`; devuelve `None` (con log de warning) si el fichero no existe o falla la carga, sin propagar excepción.
- [x] T3.3 — Implementar `_lookup_route_distance(origin, destination)`: consulta determinista a DuckDB (no expuesta como `@tool`) para obtener la distancia media histórica de la ruta.
- [x] T3.4 — Implementar `_build_model_features(flight_context)`: construye el vector de features codificado a partir de `flight_context` + `_lookup_route_distance`.
- [x] T3.5 — Implementar `_derive_delay_prediction_ml(...)`: inferencia del regresor y del clasificador, cálculo de `confidence` a partir de la dispersión entre árboles del regresor, y derivación de `is_disruption` aplicando `Settings.DELAY_THRESHOLD_MINUTES` sobre la predicción de retraso en llegada.
- [x] T3.6 — Convertir `_derive_delay_prediction` en despachador: usa `_derive_delay_prediction_ml` si `_load_delay_model()` devuelve un modelo válido, si no cae en `_derive_delay_prediction_heuristic`; loguea qué camino se ha usado en cada llamada.

## Bloque 4 — Pruebas
- [x] T4.1 — `tests/unit/test_delay_model.py` (nuevo): entrena el pipeline sobre un dataset sintético pequeño (no las 30M filas reales) y verifica que produce un artefacto válido con métricas coherentes.
- [x] T4.2 — Tests unitarios: encoding de categorías no vistas (no lanza excepción), cálculo de `confidence` a partir de una dispersión simulada entre árboles, derivación de `is_disruption` desde una predicción ML simulada.
- [x] T4.3 — Reescribir la clase de tests de `_derive_delay_prediction` en `tests/integration/test_analytical_agent.py`: camino ML feliz (con artefacto de prueba) y camino fallback (sin artefacto/artefacto corrupto).
- [x] T4.4 — Verificar que `disruption_agent`/`communication_agent` siguen funcionando sin cambios (contrato `DelayPrediction` intacto) y ejecutar la suite completa (`pytest`) en verde. Nota: 1 fallo pre-existente y fuera de alcance queda documentado (ver devlog) — no relacionado con `delay_prediction`.

## Bloque 5 — Validación manual y rendimiento
- [x] T5.1 — Recalcular `delay_prediction` con el modelo para 2 consultas de ejemplo (una bien representada, una rara); registrado en el devlog heurístico vs. modelo. **Punto de validación con el usuario.** Nota: la carpeta `docs/features/reducir-tiempo-ejecucion/` ya no existe en disco (desapareció fuera de esta sesión, no se ha tocado desde aquí), así que no se han podido reutilizar los ejemplos exactos de ese evolutivo — se han elegido 2 combinaciones reales representativas en su lugar.
- [x] T5.2 — Medir el tiempo de inferencia del modelo y registrarlo, para no reabrir el problema de latencia de `reducir-tiempo-ejecucion`.

## Bloque 6 — Documentación y cierre
- [x] T6.1 — Generar `docs/features/prediccion-ml-real/model_evaluacion.md` con las métricas reales del modelo frente al heurístico (baseline).
- [x] T6.2 — Actualizar `README.md` con una sección breve sobre cómo entrenar el modelo (`python data/train_delay_model.py`), junto al paso existente de `data_ingestion.py`.
- [!] T6.3 — Leer `docs/templates/review-template.html` y generar `prediccion-ml-real-review.html` en la carpeta del feature. **Validación final del usuario.**
  - Bloqueada: `docs/templates/review-template.html` no existe en el repositorio (tampoco en ningún evolutivo anterior). El usuario decide cerrar el evolutivo sin este HTML por ahora; queda como deuda pendiente, no como tarea abandonada. Ver `04_lecciones_aprendidas.md`.
