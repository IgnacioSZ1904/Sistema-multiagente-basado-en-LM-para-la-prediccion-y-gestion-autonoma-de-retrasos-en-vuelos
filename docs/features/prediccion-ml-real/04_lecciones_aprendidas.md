# Lecciones aprendidas: prediccion-ml-real

## [2026-07-27] — `docs/templates/review-template.html` no existe; ningún evolutivo anterior ha completado la fase de HTML de revisión

**Contexto:** T6.3, al ir a generar `prediccion-ml-real-review.html` tras el cierre validado del evolutivo.

**Qué pasó:** `docs/templates/review-template.html` (referenciado como obligatorio en `AGENTS.md` §4.6) no existe en el repositorio, y ninguno de los 5 evolutivos anteriores (`logs-trazabilidad-agentes`, `refactor-agente-analitico`, `refactor-agente-comunicacion`, `refactor-agente-disrupcion`, `revision-supervisor`) tiene un `<nombre>-review.html` generado.

**Causa raíz:** La plantilla de referencia nunca se creó; la fase de cierre con HTML de revisión, aunque está documentada en `AGENTS.md` como paso obligatorio antes de dar por cerrado cualquier evolutivo, no se ha ejecutado nunca en la práctica en este proyecto.

**Corrección aplicada:** No se ha inventado un template ad-hoc (regla explícita anti-deriva de `AGENTS.md` §7). Se ha preguntado al usuario cómo proceder en lugar de asumir un diseño no autorizado.

**Regla para el futuro:** Antes de la fase de cierre de cualquier evolutivo, verificar primero que `docs/templates/review-template.html` existe. Si no existe, es un bloqueo real que debe resolverse con el usuario (crear la plantilla como tarea propia, o acordar una alternativa) antes de generar cualquier HTML de revisión — no se debe inventar CSS/estructura por cuenta propia ni tampoco omitir el aviso.

**Tags:** `#proceso` `#documentación`

## [2026-07-27] — `USING SAMPLE` de DuckDB se aplica ANTES del `WHERE` si van al mismo nivel

**Contexto:** T2.1/T2.2, escribiendo `data/train_delay_model.py::_load_sample`.

**Qué pasó:** Un dry-run pidiendo 8000 filas de `Year = 2023` devolvía solo ~500. `USING SAMPLE n ROWS` colocado en la misma consulta que el `WHERE` muestrea sobre la tabla física completa (30M filas, 6 años) ANTES de filtrar; el filtro se aplica después sobre esa muestra ya reducida, así que el tamaño final depende de qué fracción de la muestra cruda cumple el filtro, no del número pedido.

**Causa raíz:** Se asumió que `FROM tbl WHERE cond USING SAMPLE n ROWS` se comporta como "primero filtra, luego muestrea n filas del resultado filtrado" (el orden lógico habitual de SQL), sin verificar el comportamiento real de DuckDB.

**Corrección aplicada:** Envolver el `SELECT ... WHERE ...` en una subconsulta y aplicar `USING SAMPLE n ROWS (reservoir, seed)` sobre esa subconsulta ya filtrada (`SELECT * FROM (SELECT ... WHERE ...) USING SAMPLE n ROWS (...)`), verificado empíricamente que entonces sí devuelve exactamente `n` filas.

**Regla para el futuro:** Al usar `USING SAMPLE` de DuckDB con cualquier filtro `WHERE`, verificar SIEMPRE con un recuento de filas que el muestreo se aplica después del filtro (envolviendo en subconsulta), no asumirlo por la sintaxis.

**Tags:** `#datos` `#duckdb`

## [2026-07-27] — `CAST(x / 100 AS INTEGER)` en DuckDB REDONDEA, no trunca

**Contexto:** T4.4, ejecutando la suite completa de tests tras terminar el Bloque 4. Apareció un fallo pre-existente no relacionado (`test_hours_are_in_valid_range`) que llevó a investigar por qué `hour` podía valer 24.

**Qué pasó:** `CAST(CRSDepTime / 100 AS INTEGER)` (patrón usado en `tools/analytical_tools.py`, `tools/disruption_tools.py`, y que yo mismo había copiado en `data/train_delay_model.py`) da 24 para `CRSDepTime=2359`: `/` entre dos BIGINT en DuckDB hace división real (2359/100 = 23,59), y `CAST(... AS INTEGER)` REDONDEA al entero más cercano (24), no trunca (23) como en Python o C.

**Causa raíz:** Se copió un patrón SQL ya presente en el proyecto (`tools/analytical_tools.py`) asumiendo que `CAST(... AS INTEGER)` trunca, sin verificar el comportamiento de redondeo de DuckDB para conversiones DOUBLE→INTEGER.

**Corrección aplicada:** En `data/train_delay_model.py` (código propio de este evolutivo, sí en alcance) se cambió a `CRSDepTime // 100` (división entera real, trunca correctamente) y se reentrenó el modelo. El mismo bug en `tools/analytical_tools.py`/`tools/disruption_tools.py` (pre-existente, afecta a `get_delay_by_hour`, `get_flight_historical_stats`, `get_cascade_risk_context`, y a las tools de `disruption_agent`) se ha dejado **sin corregir**: es un bug real pero fuera del alcance de `prediccion-ml-real` (afecta a tools de producción no tocadas por este evolutivo) — documentado en `99_devlog.md` para que el usuario decida si abre un evolutivo aparte.

**Regla para el futuro:** En DuckDB (y en general, verificar por SQL engine), usar siempre `//` para división entera con truncamiento; no asumir que `CAST(a / b AS INTEGER)` trunca — routine redondea. Al copiar un patrón SQL ya existente en el proyecto, no asumir que es correcto solo porque ya estaba en producción.

**Tags:** `#datos` `#duckdb` `#bug-preexistente`

## [2026-07-27] — `tree.predict()` de un RandomForest devuelve forma `(n_muestras, n_salidas)`, no `(n_salidas,)`, incluso con una sola muestra

**Contexto:** T4.3, escribiendo tests con un regresor "falso" (`_FakeRegressor`) para `_derive_delay_prediction_ml`.

**Qué pasó:** `_derive_delay_prediction_ml` calculaba `tree_preds = np.stack([tree.predict(features) for tree in regressor.estimators_])` y luego indexaba `tree_preds[:, 1]` esperando forma `(n_árboles, n_salidas)`. Con una sola fila de entrada, `tree.predict(features)` devuelve forma `(1, 2)` (1 muestra, 2 salidas), así que el `stack` da forma `(n_árboles, 1, 2)`, no `(n_árboles, 2)` — `tree_preds[:, 1]` lanzaba `IndexError` en cuanto se ejecutaba con datos reales (los tests con mocks lo detectaron antes de llegar a producción).

**Causa raíz:** No se verificó la forma real devuelta por `predict()` de un estimador individual de scikit-learn para una entrada de una sola fila; se asumió (por analogía con `regressor.predict(features)[0]`, que sí colapsa la primera dimensión) que el resultado por árbol también sería 1-D.

**Corrección aplicada:** Indexar `tree_preds[:, 0, 1]` (fila 0 = única muestra, columna 1 = `arr_delay`).

**Regla para el futuro:** Al operar con las predicciones de estimadores individuales de un ensemble de scikit-learn (`.estimators_`), verificar la forma real del array devuelto con una prueba concreta antes de indexar — no asumir que se comporta igual que el método `.predict()` del ensemble completo.

**Tags:** `#ml` `#testing`

## [2026-07-27] — `tool_call["args"]` conserva el tipo crudo del LLM, no el tipo coercionado por la tool

**Contexto:** T5.1, validación manual real por el usuario a través del frontend (no la validación directa en Python que yo había hecho). Consulta: "vuelo de Frontier (F9) desde Denver, CO hasta Chicago, IL en diciembre a las 07:00".

**Qué pasó:** `analytical_agent` falló con `TypeError: unsupported operand type(s) for //: 'str' and 'int'` en `_ensure_cascade_risk_context` (código ya existente, no de este evolutivo). El LLM (llama3.1 vía Ollama) invocó `get_flight_historical_stats` con `month="12"` y `scheduled_dep="0700"` como STRINGS, no ints. La propia tool funcionó bien (`tool_fn.invoke(tool_args)` sí coacciona tipos según la firma tipada de la tool antes de ejecutar el SQL), pero `_derive_flight_context` construye `FlightContext` a partir de `tool_args` -el diccionario CRUDO tal como lo generó el LLM en el mensaje, sin pasar por esa coerción-, así que `flight_context["scheduled_dep"]` seguía siendo `"0700"` (string) cuando `_ensure_cascade_risk_context` intentó `scheduled_dep // 100`. Mi propio `_build_model_features` (prediccion-ml-real) tiene el mismo patrón `scheduled_dep // 100` y habría fallado igual una vez llegado ahí.

**Causa raíz:** Se asumió que como la tool está tipada (`month: int`, `scheduled_dep: int`) los argumentos ya vendrían como int en cualquier punto donde se reutilizaran, sin distinguir entre "los argumentos que ve la tool al ejecutarse" (coaccionados) y "los argumentos crudos que trae el `AIMessage.tool_calls`" (tal cual el LLM los generó, potencialmente como string). Este bug ya existía en `_ensure_cascade_risk_context` antes de este evolutivo, pero solo se manifestó al hacer la validación manual real de `prediccion-ml-real` (mis pruebas anteriores invocaban las funciones en Python con ints ya correctos, sin pasar por un LLM real).

**Corrección aplicada:** Nueva función `_coerce_int()` en `agents/analytical_agent.py`, aplicada dentro de `_derive_flight_context()` a `month` y `scheduled_dep` — corrige el problema en el único punto donde se deriva `FlightContext`, beneficiando a todos los consumidores posteriores (`_ensure_cascade_risk_context`, `_build_model_features`) sin tocarlos uno a uno. Test de regresión añadido en `TestDeriveFlightContext`.

**Regla para el futuro:** Nunca asumir que `tool_call["args"]` (el diccionario dentro de `AIMessage.tool_calls`, antes de invocar la tool) tiene los tipos ya coaccionados según la firma de la tool — esa coerción solo ocurre al llamar `tool_fn.invoke(tool_args)`, no antes. Cualquier código que reutilice esos argumentos crudos para algo distinto de invocar la tool (como derivar `FlightContext` para otro propósito) debe normalizar los tipos él mismo. Además: la validación manual con el LLM real (no solo con mocks/tests unitarios) sigue siendo necesaria incluso cuando la lógica ya está bien cubierta por tests, porque el LLM puede producir formas de datos que ningún test anticipó.

**Tags:** `#llm` `#tipos` `#validación-manual`
