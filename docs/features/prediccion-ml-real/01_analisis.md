# Análisis: prediccion-ml-real

## 1. Petición original
> "vamos a mover la prediccion a un modelo estadistico ml real"
>
> Contexto inmediato: en la conversación anterior se había descrito el estado actual del sistema al usuario para explicárselo a su tutor, y entre las opciones de "siguiente paso" propuestas figuraba: *"Mover la predicción de un heurístico determinista a un modelo estadístico/ML real entrenado sobre el dataset (ahora mismo `delay_prediction` es una regla de umbral + confianza por tamaño de muestra, no un modelo predictivo aprendido)"*. El usuario elige explícitamente esa opción.

## 2. Objetivo
Sustituir el cálculo actual de `delay_prediction` — un heurístico 100% determinista que promedia por SQL una combinación exacta (aerolínea + ruta + mes + franja horaria) y estima la confianza por tramos de tamaño de muestra — por un modelo estadístico/ML entrenado sobre el histórico completo (~30M vuelos), capaz de generalizar a combinaciones con poca o ninguna muestra exacta y de aportar una confianza fundamentada en el propio modelo. No es un cambio cosmético: la predicción de retrasos es la pieza central que da nombre al TFG, y actualmente esa pieza no aprende nada, solo agrega datos históricos exactos.

## 3. Estado actual del proyecto

### Cómo se calcula `delay_prediction` hoy
`agents/analytical_agent.py::_derive_delay_prediction` (líneas 301-346), puramente determinista:
- `expected_dep_delay_min` / `expected_arr_delay_min`: medias SQL crudas para el match EXACTO (misma aerolínea, origen, destino, mes y hora programada), calculadas por la tool `get_flight_historical_stats`.
- `is_disruption`: `avg_arr_delay_min > Settings.DELAY_THRESHOLD_MINUTES` (15 min por defecto).
- `confidence`: fórmula por tramos de `sample_size` (menos de 30 vuelos comparables → confianza baja; 30-200 → media; más de 200 → alta, tope 0.95). No mide incertidumbre real del modelo, solo cuántos vuelos históricos idénticos hay.
- `main_cause`: causa dominante ya calculada por SQL (`CASE` sobre medias de columnas de causa) para ese mismo match exacto.

Si la combinación exacta tiene pocos o cero vuelos históricos, la "predicción" degenera en promedios ruidosos o en una predicción vacía con confianza 0 — no hay generalización entre combinaciones parecidas.

### Dataset disponible
`data/analytical_db.duckdb`, tabla `flights` (verificado en esta sesión):
- **30.132.672 filas**, años 2018-2023, 11 aerolíneas, 7.644 combinaciones origen-destino distintas.
- `ArrDelayMinutes` sin nulos en la tabla completa.
- ~**20,73%** de los vuelos superan los 15 min de retraso en llegada (clase positiva de "disrupción") — proporción razonable para entrenar un clasificador, aunque la fase de planificación debe comprobar el balance por segmentos (aerolínea/ruta/hora concretos), no solo global.

### Módulos y dependencias relevantes
- `tools/analytical_tools.py::get_flight_historical_stats` es la ÚNICA tool que alimenta `delay_prediction` hoy; devuelve agregados para el match exacto. Un modelo ML probablemente necesita un vector de features por predicción, no un agregado — este punto requiere diseño en la fase de planificación.
- `requirements.txt` (vía `backend/requirements.txt`): tiene `pandas`, `pyarrow`, `duckdb`, pero **no** tiene `scikit-learn`, `numpy` explícito, ni ninguna librería de serialización de modelos (`joblib`). Habrá que añadir dependencias nuevas.
- `config/settings.py`: `DELAY_THRESHOLD_MINUTES=15`, `DB_PATH`. No existe hoy ninguna configuración relativa a un artefacto de modelo (ruta, versión, etc.).
- No existe ningún pipeline de entrenamiento, script de train/test split, artefacto de modelo serializado, ni métrica de evaluación (MAE, accuracy, F1...) en el proyecto actualmente.

### Tests existentes que cubren el área
`tests/integration/test_analytical_agent.py` (líneas 307-374) dedica una clase entera a `_derive_delay_prediction`, con 6 tests que verifican el comportamiento exacto del heurístico actual: predicción "a cero" con `sample_size=0`, umbral de disrupción, tres tramos de confianza por tamaño de muestra, y que `main_cause` se toma literal de `dominant_delay_cause`. Estos tests quedarán obsoletos casi en su totalidad — testean la fórmula concreta, no el contrato de `DelayPrediction` en sí — y deberán reescribirse contra el nuevo mecanismo.

### Lecciones aprendidas relevantes de features anteriores
- `refactor-agente-analitico/04_lecciones_aprendidas.md`: ya hubo una confusión previa entre "qué agente calcula la predicción" y "cómo se calcula". Se decidió explícitamente que **`analytical_agent` conserva la propiedad de `delay_prediction`**, calculada de forma determinista (entonces, heurística; ahora, un modelo entrenado) — este evolutivo cambia el *cómo*, no el *quién*, y no debe reabrirse esa decisión.
- `reducir-tiempo-ejecucion/01_analisis.md`: confirmado que no hay GPU disponible; cualquier modelo debe funcionar en CPU. También confirmado que el coste de latencia problemático viene de las llamadas LLM (`with_structured_output`), no de las tools SQL — la inferencia de un modelo scikit-learn debería ser del orden de milisegundos, muy por debajo de ese problema, pero conviene medirlo para no reabrirlo.

## 4. Alcance

### Dentro de alcance
- Diseñar y entrenar un modelo (o varios) sobre el histórico de `analytical_db.duckdb` que sustituya el cálculo de `expected_dep_delay_min` / `expected_arr_delay_min` / `is_disruption` / `confidence` / `main_cause`.
- Un pipeline de entrenamiento offline (análogo a `data/data_ingestion.py`) que produzca un artefacto serializado, reproducible y versionable.
- Adaptar `analytical_agent.py` para cargar ese artefacto e inferir en tiempo de consulta, sin reintroducir el problema de latencia recién diagnosticado en `reducir-tiempo-ejecucion`.
- Evaluación cuantitativa del modelo (métricas de regresión/clasificación) frente al heurístico actual como baseline, como evidencia para la memoria del TFG.
- Actualizar/rediseñar los tests que hoy validan el heurístico determinista.
- Documentar en la memoria del TFG el proceso de modelado (features, algoritmo, validación) como aportación metodológica central del trabajo.

### Fuera de alcance
- Cambios en `disruption_agent` (severidad, scoring de alternativas, coste operativo) — sigue siendo determinista por reglas.
- Cambios en `communication_agent`.
- Cambios de arquitectura del grafo/routing (ya cerrado en `revision-supervisor`).
- Infraestructura MLOps compleja (registro de modelos, reentrenamiento automático, monitorización de drift) — un artefacto entrenado una vez y cargado en el proceso es suficiente para el alcance de un TFG, salvo que se decida lo contrario explícitamente.
- Eliminar `get_flight_historical_stats` como fuente de datos puramente factuales para el operador — sigue siendo útil mostrar el histórico real, independientemente de que exista un modelo.

## 5. Riesgos y dependencias

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Los 6 tests actuales de `_derive_delay_prediction` quedan invalidados al cambiar el mecanismo de cálculo | Alta | Medio | Reescribirlos contra el nuevo contrato (mismo shape de `DelayPrediction`, distinta fuente de cálculo), no contra la fórmula heurística vieja |
| Confundir de nuevo "qué agente calcula la predicción" con "cómo la calcula" (ver lección de `refactor-agente-analitico`) | Baja | Alto | Confirmar explícitamente en planificación: `analytical_agent` sigue siendo el único dueño de `delay_prediction` |
| Cargar/ejecutar el modelo introduce latencia o complejidad de arranque no deseada | Media | Medio | Entrenamiento 100% offline en script aparte; inferencia en runtime debe medirse y quedar en milisegundos |
| Desbalance de clases en subsegmentos concretos (aerolínea+ruta+mes+hora), igual que ya le pasaba al heurístico por `sample_size` bajo | Media | Medio | Evaluar el modelo por segmentos, no solo de forma global; no asumir generalización uniforme |
| No hay GPU disponible (confirmado en `reducir-tiempo-ejecucion`) | Alta (hecho) | Bajo | Elegir modelos ligeros de scikit-learn (regresión lineal/logística, árboles, gradient boosting ligero), no deep learning |
| Faltan librerías ML en `requirements.txt` | Alta (hecho) | Bajo | Añadir `scikit-learn` (+ `joblib`) en la fase de planificación |

## 6. Preguntas abiertas — RESUELTAS (2026-07-27)
- [x] **¿Separación por tarea o modelo multi-salida?** "Como sea más eficiente" — se delega la decisión concreta a la fase de planificación con criterio de eficiencia (menos modelos que mantener/entrenar, sin sacrificar señal). Propuesta a validar en planificación: 1 modelo de regresión (multi-salida, dep+arr) + 1 clasificador multiclase para `main_cause`; `is_disruption` se deriva del umbral ya existente aplicado sobre la predicción de retraso en llegada (regla determinista que ya existe, ahora alimentada por el modelo en vez de por SQL), evitando un tercer modelo redundante.
- [x] **¿De dónde sale `confidence`?** Medida de incertidumbre del propio modelo (no soporte por tamaño de muestra). Con un ensemble (p. ej. Random Forest) se puede derivar de la dispersión entre las predicciones de los árboles individuales; se concreta el cálculo exacto en planificación.
- [x] **¿Qué features de entrada?** Abrir el conjunto de features más allá de los 5 actuales de la tool (aerolínea, origen, destino, mes, hora programada) — se puede enriquecer con distancia, día de la semana, temporada, etc. Implica decidir en planificación cómo se obtienen esas features adicionales (algunas son propiedad de la ruta y se pueden derivar del propio histórico sin pedírselas al operador; otras, como día de la semana, requieren una fecha concreta que hoy la tool no exige).
- [x] **¿Librería/algoritmo?** Se acepta la propuesta por defecto: scikit-learn, CPU-only.
- [x] **¿Dónde y cuándo se entrena?** De acuerdo con la propuesta: script de entrenamiento offline independiente (`data/train_delay_model.py`), ejecutado manualmente como `data_ingestion.py`, con artefacto serializado que el agente carga en frío.
- [x] **¿Nivel de evaluación mínimo exigido?** Ninguno estricto por ahora — enfoque iterativo ("vamos viendo y mejorando"): se calculan y documentan métricas y comparación frente al heurístico como referencia, pero sin umbral de corte obligatorio en esta primera versión.

## 7. Criterios de aceptación
- [ ] `delay_prediction` se calcula mediante un modelo entrenado (no una fórmula de umbral/tramos), con un proceso de entrenamiento documentado y reproducible.
- [ ] El modelo se evalúa con métricas cuantitativas (a definir según las preguntas abiertas) y se documenta la comparación frente al heurístico actual como baseline.
- [ ] `analytical_agent` sigue siendo el único responsable de escribir `delay_prediction` en el estado (no se reabre la decisión de `refactor-agente-analitico`).
- [ ] La inferencia del modelo no introduce latencia perceptible (objetivo: milisegundos, no segundos) — no debe reabrir el problema de `reducir-tiempo-ejecucion`.
- [ ] Los tests existentes que hoy cubren el heurístico se actualizan/sustituyen y la suite completa (`pytest`) pasa en verde.
- [ ] Se documenta en la memoria del TFG el proceso de modelado como aportación metodológica.
