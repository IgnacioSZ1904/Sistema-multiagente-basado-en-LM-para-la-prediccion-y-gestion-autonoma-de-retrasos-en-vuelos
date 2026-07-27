# Devlog: prediccion-ml-real

---

## [2026-07-27] — Inicio del evolutivo
- Carpeta creada en `docs/features/prediccion-ml-real`.
- Detonante: tras describir el estado actual del sistema al usuario para explicárselo a su tutor, el usuario elige como siguiente paso sustituir el heurístico determinista de `delay_prediction` por un modelo estadístico/ML real.
- Leídas las lecciones aprendidas de `refactor-agente-analitico` (no reabrir qué agente calcula la predicción, solo cómo) y `reducir-tiempo-ejecucion` (sin GPU disponible; cuidado con reintroducir latencia).
- Verificado el tamaño y balance del dataset (`data/analytical_db.duckdb`): 30.132.672 filas, 2018-2023, 11 aerolíneas, 7.644 rutas, ~20,73% de vuelos por encima del umbral de disrupción (15 min).
- `01_analisis.md` redactado y pendiente de validación.

## [2026-07-27] — Análisis aprobado
- Usuario resuelve las 6 preguntas abiertas directamente en `01_analisis.md` ("dale, las respuestas han sido escritas en analisis"): decisión de eficiencia delegada (propuesta: regresión multi-salida + clasificador de causa, `is_disruption` derivado del umbral existente), `confidence` como medida de incertidumbre del modelo, features abiertas más allá de las 5 actuales, scikit-learn por defecto, script de entrenamiento offline confirmado, sin umbral mínimo de evaluación (enfoque iterativo).
- Se pasa a redactar `02_planificacion.md`.

## [2026-07-27] — Planificación aprobada y tareas generadas
- Usuario aprueba `02_planificacion.md` ("dale").
- `03_tareas_pendientes.md` generado: 6 bloques, 24 tareas (preparación, pipeline de entrenamiento, integración en `analytical_agent.py`, pruebas, validación manual/rendimiento, documentación y cierre).
- Pendiente de validación del desglose antes de ejecutar T1.1.

## [2026-07-27] — Ejecución de los bloques 1-4 (usuario: "hazlas todas hasta que toque validacion")

**Bloque 1 (T1.1-T1.3):** añadido `scikit-learn>=1.4.0` a `requirements.txt`/`backend/requirements.txt`; `DELAY_MODEL_PATH` añadido a `config/settings.py`, `.env` y `.env.example`; `data/models/` añadido a `.gitignore`.

**Bloque 2 (T2.1-T2.6):** creado `data/train_delay_model.py`. Validado primero con un dry-run pequeño (20k/8k filas) antes de lanzar el entrenamiento real.
- Bug detectado durante el dry-run: `USING SAMPLE n ROWS` de DuckDB muestrea ANTES de aplicar el `WHERE` si están al mismo nivel de la consulta (pedir 8000 filas de `Year=2023` devolvía ~500). Corregido envolviendo el filtro en una subconsulta y aplicando `USING SAMPLE` sobre ella.
- Entrenamiento real ejecutado sobre 1.000.000 filas (train, 2018-2022) / 300.000 filas (test, 2023): regresor en 196,8 s, clasificador en 148,9 s. Artefacto guardado en `data/models/delay_model.joblib`.
- Métricas (modelo ML vs. heurístico baseline, mismo test set): `dep_delay_mae` 23,58 vs 24,55; `arr_delay_mae` 24,33 vs 25,21; `dep/arr_delay_rmse` ~60,5 vs ~65,1 (el modelo generaliza mejor en los 4 casos). `main_cause_accuracy` 0,43 vs 0,60 (el heurístico gana en accuracy bruta, probablemente por predecir la clase mayoritaria con más frecuencia); `main_cause_f1_macro` 0,196 vs 0,182 (el modelo, con `class_weight="balanced"`, es ligeramente más equilibrado entre clases minoritarias). Sin umbral mínimo exigido (pregunta 6 del análisis), se documenta como primera versión.

**Bloque 3 (T3.1-T3.6):** `agents/analytical_agent.py` — heurístico renombrado a `_derive_delay_prediction_heuristic` (fallback); añadidas `_load_delay_model()`, `_lookup_route_distance()`, `_build_model_features()`, `_derive_delay_prediction_ml()`; `_derive_delay_prediction()` es ahora el despachador (ML si hay modelo, si no heurístico).
- Bug propio detectado por los tests nuevos (no por el usuario): `_derive_delay_prediction_ml` indexaba mal la dispersión entre árboles (`tree_preds[:, 1]` en vez de `tree_preds[:, 0, 1]`, porque `tree.predict()` de una sola muestra devuelve forma `(1, 2)`, no `(2,)`). Corregido antes de ejecutar la suite.

**Bloque 4 (T4.1-T4.4):** `tests/unit/test_delay_model.py` (nuevo, 11 tests, dataset sintético) y reescritura de la clase de tests de `delay_prediction` en `tests/integration/test_analytical_agent.py` (heurístico + ML + despachador + carga del modelo + construcción de features, 32 tests nuevos/reescritos). Al ejecutar la suite COMPLETA aparecieron 3 fallos no relacionados con este evolutivo, pre-existentes en el repositorio:
  - `tests/integration/test_analytical_agent.py` y `tests/integration/test_supervisor.py` parcheaban `agents.analytical_agent.get_llm`, nombre que ya no existe desde que un evolutivo anterior lo renombró a `get_tool_llm()` (commit `4537639`) sin actualizar los tests. Corregido (cambio mecánico de nombre en el `@patch`, sin tocar comportamiento) porque bloqueaba verificar que mi propio cambio no rompía nada.
  - `tests/unit/test_analytical_tools.py::TestGetDelayByHour::test_hours_are_in_valid_range` falla porque `CAST(CRSDepTime / 100 AS INTEGER)` en `tools/analytical_tools.py` (y en `tools/disruption_tools.py`) REDONDEA en vez de truncar (DuckDB hace división real con `/` entre BIGINTs; 2359/100=23,59 → CAST redondea a 24, hora inexistente). Bug real y pre-existente, pero **fuera de alcance de `prediccion-ml-real`** (afecta a varias tools de producción, no solo a la predicción) — NO se ha corregido en `tools/analytical_tools.py`/`tools/disruption_tools.py`, se deja documentado para que el usuario decida si abre un evolutivo aparte.
  - Mismo patrón de bug SÍ corregido en mi propio `data/train_delay_model.py` (`CRSDepTime // 100` en vez de `CAST(.../100 AS INTEGER)`), porque ahí sí está en alcance (afecta a la feature `scheduled_dep_hour` del modelo) — el modelo se ha reentrenado tras la corrección.
- Suite completa tras las correcciones: pendiente de confirmación final (ver siguiente entrada).

## [2026-07-27] — Bloque 4 cerrado: bug propio + bug ajeno detectados al ir a verde

Al ejecutar la suite completa (no solo `test_analytical_agent.py`) aparecieron 2 fallos adicionales, ambos causados por este evolutivo (no pre-existentes, a diferencia de los 3 de la entrada anterior):
- `tools/analytical_tools.py::TestGetDelayByHour` seguía en rojo por el bug de redondeo ya documentado (fuera de alcance, sin tocar).
- `test_supervisor.py::test_iteration_limit_forces_early_termination_before_disruption_agent` fallaba porque el test fabrica un `avg_arr_delay_min=95.0` vía una tool mockeada, asumiendo que eso basta para forzar `is_disruption=True` — cierto con el heurístico, pero ya no con el despachador: como `data/models/delay_model.joblib` existe físicamente en este entorno, `_derive_delay_prediction` prefiere el modelo ML, que ignora la tool mockeada y predice con datos reales (retraso bajo para esa combinación). Corregido añadiendo `@patch("agents.analytical_agent._load_delay_model", return_value=None)` a ese test para forzar el camino heurístico — el test valida el límite de iteraciones del supervisor, no el método de predicción, así que no debe depender de si hay un artefacto de modelo real en disco.
- Suite completa final: **220 passed, 1 failed** (el único fallo restante es `test_hours_are_in_valid_range`, pre-existente y fuera de alcance, documentado arriba).

## [2026-07-27] — T5.1/T5.2: validación manual y rendimiento

La carpeta `docs/features/reducir-tiempo-ejecucion/` (que contenía los ejemplos originales "vuelo DL JFK→ATL" y la consulta exploratoria) ya no existe en disco — desapareció fuera de esta sesión de trabajo, no se ha tocado desde aquí. En su lugar se han elegido 2 combinaciones reales de `analytical_db.duckdb`, corriendo `_derive_delay_prediction_heuristic` y `_derive_delay_prediction_ml` directamente (sin necesidad de Ollama) sobre el mismo `flight_historical_stats` real:

**Caso 1 — combinación bien representada** (DL, New York-Atlanta, marzo, 06:00, `sample_size`=307 vuelos históricos, `avg_arr_delay_min` real=7.29):
| Campo | Heurístico | Modelo ML |
|---|---|---|
| expected_dep_delay_min | 6.03 | 5.69 |
| expected_arr_delay_min | 7.29 | 6.28 |
| is_disruption | False | False |
| confidence | 0.82 | 0.85 |
| main_cause | nas | unknown |

Ambos coinciden en que no hay disrupción y en un retraso esperado bajo y similar (diferencia de ~1 min). `main_cause` difiere (heurístico dice "nas", el clasificador dice "unknown" al no haber una causa claramente dominante en un vuelo con tan poco retraso) — divergencia razonable, no una contradicción.

**Caso 2 — combinación rara** (F9, Denver-Chicago, diciembre, 07:00, `sample_size`=1 vuelo histórico, ese único vuelo llegó puntual):
| Campo | Heurístico | Modelo ML |
|---|---|---|
| expected_dep_delay_min | 0.0 | 4.49 |
| expected_arr_delay_min | 0.0 | 6.12 |
| is_disruption | False | False |
| confidence | 0.31 | 0.59 |
| main_cause | carrier | unknown |

Este es el caso que justifica el cambio: el heurístico solo tiene 1 vuelo histórico exacto y su "predicción" es literalmente el resultado de ese único vuelo (0 min, confianza baja 0.31); el modelo generaliza a partir de patrones de miles de vuelos similares (misma aerolínea/temporada/franja horaria en otras rutas) y da una estimación con más confianza (0.59) aunque también sin disrupción.

**Rendimiento (T5.2):** inferencia pura del modelo (regresor + clasificador + dispersión entre 150 árboles), con la distancia de ruta ya conocida: **~88 ms de media** (10 repeticiones, 75-109 ms). La consulta de distancia de ruta (`_lookup_route_distance`, abre una conexión DuckDB nueva cada vez) añade **~480 ms** adicionales cuando `flight_context` no trae la distancia. Total end-to-end por vuelo: bajo 1 segundo en el peor caso — muy por debajo de los 250-315 s por llamada que motivaron `reducir-tiempo-ejecucion`; no reabre ese problema. Nota para una futura iteración: cachear la distancia por ruta (o precalcularla en el artefacto) eliminaría la mayor parte de esos ~480 ms si se quisiera bajar de "milisegundos altos" a "milisegundos bajos".

**Pendiente de validación explícita del usuario antes de continuar con el Bloque 6 (documentación y cierre).**

## [2026-07-27] — Bug real encontrado en validación manual por el usuario (frontend + Ollama real)

El usuario probó la consulta sugerida ("vuelo F9 Denver-Chicago, diciembre, 07:00") a través del frontend real. `analytical_agent` falló con `TypeError: unsupported operand type(s) for //: 'str' and 'int'` en `_ensure_cascade_risk_context` (código pre-existente, no de este evolutivo): el LLM devolvió `month="12"` y `scheduled_dep="0700"` como strings en la tool_call, y `_derive_flight_context` los reenviaba tal cual sin normalizar. Ver lección detallada en `04_lecciones_aprendidas.md`.

**Corrección:** nueva función `_coerce_int()` aplicada en `_derive_flight_context()` (agents/analytical_agent.py), que normaliza `month`/`scheduled_dep` a `int` en el único punto de derivación de `FlightContext`, corrigiendo de una vez el bug pre-existente en `_ensure_cascade_risk_context` y previniendo el mismo fallo en mi propio `_build_model_features`. Test de regresión añadido en `TestDeriveFlightContext`. Suite completa tras la corrección: **221 passed, 1 failed** (el único fallo sigue siendo el pre-existente y fuera de alcance `test_hours_are_in_valid_range`).

Se le pide al usuario reintentar la misma consulta en el frontend para confirmar que ya funciona de extremo a extremo.

## [2026-07-27] — Validación manual confirmada por el usuario; ejemplo de disrupción real

Usuario confirma que ambas consultas se resuelven correctamente (~3 min cada una). Pide un ejemplo que sí sea disrupción (ninguna de las dos probadas lo era). Se identifica **DL, Chicago IL → New York NY, agosto, 18:00** (169 vuelos históricos, `avg_arr_delay_min` real 80,3 min) y se confirma con el modelo antes de sugerirlo: `is_disruption=true`, `expected_arr_delay_min≈35.8`, `confidence=0.45`. El usuario lo prueba en el frontend real y confirma que activa correctamente `disruption_agent`.

Usuario pregunta por qué una consulta con disrupción tarda más. Respuesta: no son las mismas 2 etapas más lentas, sino que se activa un tercer agente (`disruption_agent`) que en consulta normal ni se ejecuta, y ese agente hace su propia llamada `with_structured_output()` — el mismo mecanismo ya diagnosticado como desproporcionadamente lento en Ollama local en `reducir-tiempo-ejecucion` (275-315s por llamada). Se señala como línea de trabajo futura, no se toca en este evolutivo.

**Usuario da la validación por buena y pide cerrar el evolutivo** ("en general esta muy bien, yo daria la validacion por buena y cerraria este feature"). Se pasa al Bloque 6 (documentación y cierre).

## [2026-07-27] — Bloque 6: documentación y bloqueo en el cierre

- T6.1: generado `model_evaluacion.md` con el resumen completo de datos de entrenamiento, métricas ML vs. heurístico, los 3 casos de validación manual, rendimiento y bugs encontrados.
- T6.2: `README.md` actualizado — nueva instrucción para ejecutar `data/train_delay_model.py` tras `data_ingestion.py`, descripción del Agente Analítico actualizada para mencionar el modelo ML (con heurístico como respaldo), y árbol de estructura del repositorio actualizado.
- T6.3 **BLOQUEADO**: `docs/templates/review-template.html` no existe en el repositorio. Tampoco existe ningún `<nombre>-review.html` en ninguno de los evolutivos anteriores (`logs-trazabilidad-agentes`, `refactor-agente-analitico`, `refactor-agente-comunicacion`, `refactor-agente-disrupcion`, `revision-supervisor`) — esta fase de AGENTS.md nunca se ha completado en este proyecto. Regla del propio AGENTS.md §4.6: "No generar el HTML de revisión con estilos inventados: usar siempre los componentes de `docs/templates/review-template.html`". Se pregunta al usuario cómo proceder en lugar de inventar un template no autorizado.
- Usuario elige explícitamente: **"Cierra sin HTML por ahora"** — el evolutivo se da por cerrado (ya validado en la entrada anterior) dejando T6.3 marcada como bloqueada (`- [!]`) y anotada como deuda pendiente en `03_tareas_pendientes.md`, no como tarea completada ni abandonada.

## [2026-07-27] — Cierre del evolutivo

**Estado final: 🟢 Completado** (Bloques 1-5 completos y validados por el usuario; Bloque 6 completo salvo T6.3, bloqueada por falta de `docs/templates/review-template.html` — deuda documentada, no silenciada).

Resumen para la memoria del TFG: se sustituyó el heurístico determinista de `delay_prediction` (medias SQL de la combinación exacta + confianza por tamaño de muestra) por un modelo Random Forest (scikit-learn, CPU-only) entrenado sobre 1M vuelos históricos, con mejor generalización en minutos de retraso (4-8% menos error en test 2023) y capacidad de predecir sobre combinaciones sin apenas histórico exacto (caso F9 Denver-Chicago, sample_size=1). Contrato `DelayPrediction` sin cambios; `analytical_agent` conserva la propiedad de la predicción (decisión de `refactor-agente-analitico` respetada). Validado de extremo a extremo por el usuario con Ollama real, incluyendo un caso de disrupción real que activa correctamente `disruption_agent`. Durante el proceso se encontraron y corrigieron 3 bugs (2 propios, detectados por tests antes de producción o por el propio usuario en validación manual; 1 conjunto de renombrados de tests pre-existentes) y se documentó 1 bug pre-existente fuera de alcance (redondeo de horas en otras tools) para un futuro evolutivo.

**Líneas de trabajo futuro identificadas, no incluidas en este evolutivo:**
1. Retomar `reducir-tiempo-ejecucion` (quedó a medio cerrar, carpeta desaparecida) — la latencia de `disruption_agent`/`communication_agent` (`with_structured_output` en Ollama local) sigue siendo el cuello de botella dominante del sistema.
2. Corregir el bug de redondeo de horas en `tools/analytical_tools.py`/`tools/disruption_tools.py`.
3. Crear `docs/templates/review-template.html` para poder cerrar formalmente este y futuros evolutivos con su HTML de revisión.
4. Posible mejora menor: cachear la distancia por ruta en `_lookup_route_distance` para bajar los ~480 ms de ese lookup.
