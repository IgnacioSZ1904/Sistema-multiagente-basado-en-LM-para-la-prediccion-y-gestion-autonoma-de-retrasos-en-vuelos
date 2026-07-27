# Evaluación del modelo predictivo — prediccion-ml-real

> Generado tras cerrar el Bloque 5 (validación manual y de rendimiento). Ver `01_analisis.md` §7 para los criterios de aceptación y `99_devlog.md` para el detalle cronológico completo.

## 1. Datos de entrenamiento

| | |
|---|---|
| Fuente | `data/analytical_db.duckdb` (tabla `flights`, dataset BTS 2018-2023) |
| Filas totales disponibles | 30.132.672 |
| Split | Temporal — train: `Year <= 2022`, test: `Year = 2023` |
| Muestra usada (train) | 1.000.000 filas (reservoir sample de DuckDB) |
| Muestra usada (test) | 300.000 filas |
| Features | `airline`, `origin`, `destination`, `month`, `scheduled_dep_hour`, `distance` |
| Algoritmo | Random Forest (scikit-learn), CPU-only — regresor multi-salida (dep+arr delay) + clasificador (causa dominante) |
| Artefacto | `data/models/delay_model.joblib` (no versionado en git) |
| Entrenado el | 2026-07-27T17:11:30 UTC |

## 2. Métricas: modelo ML vs. heurístico (mismo test set, 300k vuelos de 2023)

| Métrica | Modelo ML | Heurístico (baseline) | Mejora |
|---|---|---|---|
| `dep_delay_mae` (min) | 23,59 | 24,67 | ✅ ~4% menor error |
| `dep_delay_rmse` (min) | 60,39 | 65,35 | ✅ ~8% menor error |
| `arr_delay_mae` (min) | 24,34 | 25,31 | ✅ ~4% menor error |
| `arr_delay_rmse` (min) | 60,49 | 65,50 | ✅ ~8% menor error |
| `main_cause_accuracy` | 0,424 | 0,594 | ❌ el heurístico acierta más en bruto |
| `main_cause_f1_macro` | 0,195 | 0,182 | ✅ el modelo es algo más equilibrado entre clases minoritarias |

**Lectura:** en la predicción de minutos de retraso (lo más importante para `is_disruption` y para las decisiones posteriores del `disruption_agent`), el modelo generaliza mejor que el heurístico en las 4 métricas. En la causa dominante, el heurístico tiene más accuracy bruta (tiende a acertar más veces prediciendo la clase mayoritaria), pero el modelo (entrenado con `class_weight="balanced"`) reparte mejor los aciertos entre causas minoritarias (F1 macro ligeramente superior). No se ha exigido ningún umbral mínimo de calidad para esta primera versión (decisión tomada en `01_analisis.md` §6: enfoque iterativo, "vamos viendo y mejorando").

## 3. Validación manual (T5.1) — casos ilustrativos

### Caso 1 — combinación bien representada
**DL, New York, NY → Atlanta, GA, marzo, 06:00** (307 vuelos históricos exactos, `avg_arr_delay_min` real = 7,29 min)

| Campo | Heurístico | Modelo ML |
|---|---|---|
| expected_dep_delay_min | 6,03 | 5,69 |
| expected_arr_delay_min | 7,29 | 6,28 |
| is_disruption | False | False |
| confidence | 0,82 | 0,85 |
| main_cause | nas | unknown |

Ambos métodos coinciden en lo esencial (sin disrupción, retraso bajo). `main_cause` difiere de forma razonable: con tan poco retraso, el heurístico fuerza una de las 5 causas por desempate SQL; el clasificador identifica que ninguna causa es realmente dominante.

### Caso 2 — combinación rara (el caso que justifica el cambio)
**F9, Denver, CO → Chicago, IL, diciembre, 07:00** (1 solo vuelo histórico exacto, ese vuelo llegó puntual)

| Campo | Heurístico | Modelo ML |
|---|---|---|
| expected_dep_delay_min | 0,0 | 4,49 |
| expected_arr_delay_min | 0,0 | 6,12 |
| is_disruption | False | False |
| confidence | 0,31 | 0,59 |
| main_cause | carrier | unknown |

El heurístico solo puede repetir el resultado de ese único vuelo histórico (confianza baja, 0,31). El modelo generaliza a partir de miles de vuelos similares en la red (misma aerolínea/temporada/franja horaria en otras rutas) y da una estimación con más confianza (0,59).

### Caso 3 — combinación con disrupción real
**DL, Chicago, IL → New York, NY, agosto, 18:00** (169 vuelos históricos, `avg_arr_delay_min` real = 80,3 min — congestión estival en hora punta)

```json
{
  "expected_dep_delay_min": 34.7,
  "expected_arr_delay_min": 35.8,
  "is_disruption": true,
  "confidence": 0.45,
  "main_cause": "nas"
}
```

Confirmado end-to-end por el usuario a través del frontend real (Ollama + modelo ML): activa correctamente `disruption_agent` (severidad, alternativas, coste estimado) igual que lo hacía antes con el heurístico, sin cambios de contrato.

## 4. Rendimiento (T5.2)

| Medición | Tiempo |
|---|---|
| Inferencia pura del modelo (regresor + clasificador + dispersión entre 150 árboles) | ~88 ms de media (10 repeticiones, 75-109 ms) |
| + búsqueda de distancia de ruta (`_lookup_route_distance`, abre conexión DuckDB nueva) | +~480 ms |
| **Total delay_prediction end-to-end** | **< 1 segundo en el peor caso** |

Muy por debajo de los 250-315 segundos por llamada LLM que motivaron el evolutivo `reducir-tiempo-ejecucion` — no reabre ese problema. La latencia real observada en las pruebas de extremo a extremo (~3 min por consulta) viene íntegramente de las llamadas al LLM (`bind_tools`/`with_structured_output`), no de la predicción ML.

**Mejora futura anotada (no bloqueante):** cachear la distancia por ruta (o precalcularla dentro del propio artefacto del modelo) eliminaría la mayor parte de esos ~480 ms.

## 5. Bugs encontrados y corregidos durante este evolutivo

Ver detalle completo en `04_lecciones_aprendidas.md`. Resumen:

1. **Propio, detectado por tests antes de producción:** indexación incorrecta de la dispersión entre árboles en `_derive_delay_prediction_ml` (forma del array `(n_árboles, 1, 2)`, no `(n_árboles, 2)`).
2. **Propio, en `data/train_delay_model.py`:** `CAST(CRSDepTime / 100 AS INTEGER)` redondea en vez de truncar en DuckDB — corregido a `CRSDepTime // 100`.
3. **Pre-existente, detectado al ejecutar la suite completa:** tests de `test_analytical_agent.py`/`test_supervisor.py` parcheaban `get_llm`, nombre obsoleto desde un refactor anterior (`get_tool_llm`) — corregido.
4. **Pre-existente, fuera de alcance, NO corregido:** el mismo bug de redondeo de horas (#2) existe también en `tools/analytical_tools.py`/`tools/disruption_tools.py` (afecta a `get_delay_by_hour` y otras tools de producción). Documentado como candidato a un evolutivo aparte.
5. **Pre-existente, detectado en validación manual real (usuario + Ollama):** `tool_call["args"]` puede traer `month`/`scheduled_dep` como string en vez de int; `_derive_flight_context` no los normalizaba, rompiendo `_ensure_cascade_risk_context` (y habría roto también `_build_model_features`) — corregido con `_coerce_int()`.

## 6. Conclusión

El modelo ML sustituye con éxito al heurístico determinista como fuente de `delay_prediction`, con mejor generalización en minutos de retraso (la métrica que más importa para `is_disruption` y para el resto del pipeline), latencia de inferencia irrelevante frente al cuello de botella real del sistema (los LLM locales), y sin cambios de contrato para el resto de agentes. Validado manualmente por el usuario de extremo a extremo, incluyendo un caso de disrupción real. **Evolutivo dado por cerrado por el usuario el 2026-07-27**, con dos líneas de trabajo futuro identificadas (no incluidas aquí): el bug de redondeo de horas en otras tools, y la latencia de `disruption_agent`/`communication_agent` (`reducir-tiempo-ejecucion`).
