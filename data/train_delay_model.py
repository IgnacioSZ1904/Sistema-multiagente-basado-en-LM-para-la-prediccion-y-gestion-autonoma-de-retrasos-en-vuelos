"""
data/train_delay_model.py
==========================
Script de entrenamiento offline del modelo predictivo de retrasos
(evolutivo `prediccion-ml-real`).

Sustituye el heurístico SQL de `_derive_delay_prediction`
(agents/analytical_agent.py) por dos modelos scikit-learn entrenados
sobre el histórico completo de `analytical_db.duckdb`:

  - Un RandomForestRegressor multi-salida que predice
    (DepDelayMinutes, ArrDelayMinutes).
  - Un RandomForestClassifier que predice la causa dominante de
    retraso (carrier | weather | nas | security | late_aircraft |
    unknown), con "unknown" para vuelos sin causa de retraso
    atribuida (todas las columnas de causa a 0/NULL) — mismo valor
    que ya usa `DelayPrediction.main_cause` para "sin datos".

`is_disruption` NO tiene modelo propio: se deriva en tiempo de
inferencia aplicando el mismo umbral que ya usa el sistema
(Settings.DELAY_THRESHOLD_MINUTES) sobre la predicción de retraso en
llegada. Entrenar un tercer modelo para esto sería redundante.

Split temporal (no aleatorio): se entrena con vuelos de 2018-2022 y se
evalúa con 2023, para evitar fuga de información entre vuelos muy
correlacionados (misma ruta/temporada) y simular el caso de uso real
(predecir sobre el futuro, no interpolar dentro del mismo periodo).

Por tamaño del dataset (30M+ filas) y ausencia de GPU, el entrenamiento
usa una muestra (reservoir sampling de DuckDB, barato en una sola
pasada) en vez de las filas completas — ver TRAIN_SAMPLE_ROWS /
TEST_SAMPLE_ROWS.

Uso:
    python data/train_delay_model.py

Salida:
    data/models/delay_model.joblib (artefacto cargado por
    agents/analytical_agent.py en tiempo de ejecución).
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    root_mean_squared_error,
)
from sklearn.preprocessing import OrdinalEncoder

DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "analytical_db.duckdb"
MODEL_PATH = DATA_DIR / "models" / "delay_model.joblib"

TRAIN_YEARS_MAX = 2022          # Entrena con Year <= este valor.
TEST_YEAR = 2023                # Evalúa con Year == este valor.

TRAIN_SAMPLE_ROWS = 1_000_000   # Reservoir sample de DuckDB (una pasada).
TEST_SAMPLE_ROWS = 300_000
DISPERSION_REFERENCE_SAMPLE = 5_000  # Submuestra para calibrar `confidence`.

RANDOM_STATE = 42
N_ESTIMATORS = 150
MAX_DEPTH = 20

CATEGORICAL_COLUMNS = ["airline", "origin", "destination"]
NUMERIC_COLUMNS = ["month", "scheduled_dep_hour", "distance"]
FEATURE_COLUMNS = CATEGORICAL_COLUMNS + NUMERIC_COLUMNS

CAUSE_COLUMNS = [
    "carrier_delay",
    "weather_delay",
    "nas_delay",
    "security_delay",
    "late_aircraft_delay",
]
CAUSE_LABELS = {
    "carrier_delay": "carrier",
    "weather_delay": "weather",
    "nas_delay": "nas",
    "security_delay": "security",
    "late_aircraft_delay": "late_aircraft",
}
# Orden de desempate: replica el CASE de tools/analytical_tools.py::
# get_flight_historical_stats (carrier > weather > nas > late_aircraft,
# "security" solo como ELSE final).
CAUSE_TIEBREAK_ORDER = ["carrier_delay", "weather_delay", "nas_delay", "late_aircraft_delay"]

UNKNOWN_CAUSE = "unknown"


# ---------------------------------------------------------------------------
# Carga de datos (DuckDB, reservoir sample de una sola pasada)
# ---------------------------------------------------------------------------

def _load_sample(con: duckdb.DuckDBPyConnection, year_filter: str, sample_rows: int) -> pd.DataFrame:
    # OJO: `USING SAMPLE` debe aplicarse sobre una subconsulta ya filtrada.
    # Si el WHERE va al mismo nivel que el FROM + USING SAMPLE, DuckDB
    # muestrea ANTES de filtrar (sobre la tabla física completa) y el
    # filtro se aplica después sobre esa muestra ya reducida, devolviendo
    # muchas menos filas de las pedidas (verificado empíricamente: pedir
    # 8000 filas de Year=2023 sin subconsulta devolvía ~500, no ~8000).
    #
    # OJO 2: `CRSDepTime // 100` (división entera), NUNCA
    # `CAST(CRSDepTime / 100 AS INTEGER)`. `/` entre BIGINTs en DuckDB
    # hace división real (float) y el CAST posterior REDONDEA, no
    # trunca: 2359/100 = 23.59 -> CAST redondea a 24, una hora
    # inexistente. Bug detectado en tools/analytical_tools.py al
    # ejecutar la suite completa de este evolutivo (pre-existente, no
    # se corrige allí porque está fuera de alcance de prediccion-ml-real).
    sql = f"""
        SELECT * FROM (
            SELECT
                Marketing_Airline_Network                    AS airline,
                OriginCityName                                AS origin,
                DestCityName                                  AS destination,
                Month                                         AS month,
                (CRSDepTime // 100)                            AS scheduled_dep_hour,
                Distance                                      AS distance,
                DepDelayMinutes                               AS dep_delay,
                ArrDelayMinutes                               AS arr_delay,
                COALESCE(CarrierDelay, 0)                     AS carrier_delay,
                COALESCE(WeatherDelay, 0)                     AS weather_delay,
                COALESCE(NASDelay, 0)                         AS nas_delay,
                COALESCE(SecurityDelay, 0)                    AS security_delay,
                COALESCE(LateAircraftDelay, 0)                AS late_aircraft_delay
            FROM flights
            WHERE {year_filter}
              AND DepDelayMinutes IS NOT NULL
              AND ArrDelayMinutes IS NOT NULL
              AND Distance IS NOT NULL
              AND CRSDepTime IS NOT NULL
        ) USING SAMPLE {sample_rows} ROWS (reservoir, {RANDOM_STATE})
    """
    return con.execute(sql).fetchdf()


def load_train_test_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga las muestras de train (<= TRAIN_YEARS_MAX) y test (== TEST_YEAR)."""
    print(f"[train_delay_model] Conectando a {DB_PATH} (solo lectura)...")
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        print(f"[train_delay_model] Cargando muestra de train (Year <= {TRAIN_YEARS_MAX}, {TRAIN_SAMPLE_ROWS:,} filas)...")
        train_df = _load_sample(con, f"Year <= {TRAIN_YEARS_MAX}", TRAIN_SAMPLE_ROWS)
        print(f"[train_delay_model] Cargando muestra de test (Year == {TEST_YEAR}, {TEST_SAMPLE_ROWS:,} filas)...")
        test_df = _load_sample(con, f"Year = {TEST_YEAR}", TEST_SAMPLE_ROWS)
    print(f"[train_delay_model] train={len(train_df):,} filas, test={len(test_df):,} filas")
    return train_df, test_df


# ---------------------------------------------------------------------------
# Etiqueta de causa dominante (aplicada fila a fila)
# ---------------------------------------------------------------------------

def _dominant_cause_row(row: pd.Series) -> str:
    """
    Causa dominante para una fila: la de mayor minutos entre las 5
    columnas de causa, con el mismo orden de desempate que usa el SQL
    de producción. "unknown" si todas son 0 (sin causa de retraso
    atribuida) — mismo valor que ya usa el contrato `DelayPrediction`
    para "sin datos suficientes".
    """
    values = {col: row[col] for col in CAUSE_COLUMNS}
    if max(values.values()) <= 0:
        return UNKNOWN_CAUSE
    best_col = max(CAUSE_TIEBREAK_ORDER, key=lambda c: (values[c], -CAUSE_TIEBREAK_ORDER.index(c)))
    # Si el máximo real no está entre los de desempate prioritario (poco
    # probable dado que CAUSE_TIEBREAK_ORDER cubre 4 de las 5 columnas),
    # se compara también con security_delay explícitamente.
    if values["security_delay"] > values[best_col]:
        best_col = "security_delay"
    return CAUSE_LABELS[best_col]


def add_dominant_cause(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["dominant_cause"] = df.apply(_dominant_cause_row, axis=1)
    return df


# ---------------------------------------------------------------------------
# Codificación de categóricas
# ---------------------------------------------------------------------------

def fit_encoders(train_df: pd.DataFrame) -> dict[str, OrdinalEncoder]:
    encoders: dict[str, OrdinalEncoder] = {}
    for col in CATEGORICAL_COLUMNS:
        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        encoder.fit(train_df[[col]])
        encoders[col] = encoder
    return encoders


def encode_features(df: pd.DataFrame, encoders: dict[str, OrdinalEncoder]) -> np.ndarray:
    columns = []
    for col in CATEGORICAL_COLUMNS:
        columns.append(encoders[col].transform(df[[col]]))
    for col in NUMERIC_COLUMNS:
        columns.append(df[[col]].to_numpy())
    return np.hstack(columns)


# ---------------------------------------------------------------------------
# Baseline heurístico (para comparar métricas), calculado SOLO con train
# ---------------------------------------------------------------------------

def _heuristic_baseline_predictions(train_df: pd.DataFrame, test_df: pd.DataFrame) -> pd.DataFrame:
    """
    Replica el heurístico actual (medias por combinación exacta
    aerolínea+ruta+mes+hora) usando SOLO datos de train, aplicado a
    test — equivalente offline de lo que hoy hace
    `get_flight_historical_stats` sobre el histórico completo, para
    poder comparar de forma justa contra el mismo test set del modelo.
    """
    group_cols = ["airline", "origin", "destination", "month", "scheduled_dep_hour"]
    agg = train_df.groupby(group_cols).agg(
        dep_delay_pred=("dep_delay", "mean"),
        arr_delay_pred=("arr_delay", "mean"),
        **{f"{c}_mean": (c, "mean") for c in CAUSE_COLUMNS},
    ).reset_index()

    def _group_dominant_cause(row: pd.Series) -> str:
        values = {c: row[f"{c}_mean"] for c in CAUSE_COLUMNS}
        if max(values.values()) <= 0:
            return UNKNOWN_CAUSE
        best_col = max(CAUSE_TIEBREAK_ORDER, key=lambda c: (values[c], -CAUSE_TIEBREAK_ORDER.index(c)))
        if values["security_delay"] > values[best_col]:
            best_col = "security_delay"
        return CAUSE_LABELS[best_col]

    agg["dominant_cause_pred"] = agg.apply(_group_dominant_cause, axis=1)

    merged = test_df.merge(agg, on=group_cols, how="left")

    global_dep_mean = train_df["dep_delay"].mean()
    global_arr_mean = train_df["arr_delay"].mean()
    merged["dep_delay_pred"] = merged["dep_delay_pred"].fillna(global_dep_mean)
    merged["arr_delay_pred"] = merged["arr_delay_pred"].fillna(global_arr_mean)
    merged["dominant_cause_pred"] = merged["dominant_cause_pred"].fillna(UNKNOWN_CAUSE)
    return merged


# ---------------------------------------------------------------------------
# Entrenamiento y evaluación
# ---------------------------------------------------------------------------

def train_and_evaluate(train_df: pd.DataFrame, test_df: pd.DataFrame) -> dict[str, Any]:
    train_df = add_dominant_cause(train_df)
    test_df = add_dominant_cause(test_df)

    encoders = fit_encoders(train_df)
    x_train = encode_features(train_df, encoders)
    x_test = encode_features(test_df, encoders)

    y_train_reg = train_df[["dep_delay", "arr_delay"]].to_numpy()
    y_test_reg = test_df[["dep_delay", "arr_delay"]].to_numpy()

    y_train_cls = train_df["dominant_cause"].to_numpy()
    y_test_cls = test_df["dominant_cause"].to_numpy()

    print(f"[train_delay_model] Entrenando RandomForestRegressor (n_estimators={N_ESTIMATORS}, max_depth={MAX_DEPTH})...")
    start = time.perf_counter()
    regressor = RandomForestRegressor(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    regressor.fit(x_train, y_train_reg)
    print(f"[train_delay_model] Regresor entrenado en {time.perf_counter() - start:.1f}s")

    print(f"[train_delay_model] Entrenando RandomForestClassifier (causa dominante)...")
    start = time.perf_counter()
    classifier = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        class_weight="balanced",
    )
    classifier.fit(x_train, y_train_cls)
    print(f"[train_delay_model] Clasificador entrenado en {time.perf_counter() - start:.1f}s")

    # --- Métricas del modelo ML -------------------------------------------
    pred_reg = regressor.predict(x_test)
    pred_cls = classifier.predict(x_test)

    ml_metrics = {
        "dep_delay_mae": float(mean_absolute_error(y_test_reg[:, 0], pred_reg[:, 0])),
        "dep_delay_rmse": float(root_mean_squared_error(y_test_reg[:, 0], pred_reg[:, 0])),
        "arr_delay_mae": float(mean_absolute_error(y_test_reg[:, 1], pred_reg[:, 1])),
        "arr_delay_rmse": float(root_mean_squared_error(y_test_reg[:, 1], pred_reg[:, 1])),
        "main_cause_accuracy": float(accuracy_score(y_test_cls, pred_cls)),
        "main_cause_f1_macro": float(f1_score(y_test_cls, pred_cls, average="macro")),
    }

    # --- Métricas del baseline heurístico (mismo test set) -----------------
    baseline_df = _heuristic_baseline_predictions(train_df, test_df)
    heuristic_metrics = {
        "dep_delay_mae": float(mean_absolute_error(baseline_df["dep_delay"], baseline_df["dep_delay_pred"])),
        "dep_delay_rmse": float(root_mean_squared_error(baseline_df["dep_delay"], baseline_df["dep_delay_pred"])),
        "arr_delay_mae": float(mean_absolute_error(baseline_df["arr_delay"], baseline_df["arr_delay_pred"])),
        "arr_delay_rmse": float(root_mean_squared_error(baseline_df["arr_delay"], baseline_df["arr_delay_pred"])),
        "main_cause_accuracy": float(accuracy_score(baseline_df["dominant_cause"], baseline_df["dominant_cause_pred"])),
        "main_cause_f1_macro": float(f1_score(baseline_df["dominant_cause"], baseline_df["dominant_cause_pred"], average="macro")),
    }

    # --- Referencia de dispersión entre árboles, para `confidence` --------
    # Submuestra pequeña de test: calcular, por fila, la desviación típica
    # de la predicción de ArrDelayMinutes entre los árboles individuales
    # del Random Forest, y quedarse con la media como constante de
    # calibración. analytical_agent normaliza la dispersión de cada
    # inferencia nueva contra esta referencia (ver `_derive_delay_prediction_ml`).
    rng = np.random.default_rng(RANDOM_STATE)
    sample_size = min(DISPERSION_REFERENCE_SAMPLE, x_test.shape[0])
    sample_idx = rng.choice(x_test.shape[0], size=sample_size, replace=False)
    x_dispersion_sample = x_test[sample_idx]
    tree_preds = np.stack([tree.predict(x_dispersion_sample) for tree in regressor.estimators_])
    arr_delay_std_per_row = tree_preds[:, :, 1].std(axis=0)
    arr_delay_dispersion_reference = float(arr_delay_std_per_row.mean())

    metrics = {
        "ml": ml_metrics,
        "heuristic_baseline": heuristic_metrics,
        "arr_delay_dispersion_reference": arr_delay_dispersion_reference,
    }

    return {
        "regressor": regressor,
        "classifier": classifier,
        "encoders": encoders,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Serialización del artefacto
# ---------------------------------------------------------------------------

def save_artifact(result: dict[str, Any], train_rows: int, test_rows: int) -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "regressor": result["regressor"],
        "classifier": result["classifier"],
        "encoders": result["encoders"],
        "feature_columns": FEATURE_COLUMNS,
        "categorical_columns": CATEGORICAL_COLUMNS,
        "numeric_columns": NUMERIC_COLUMNS,
        "label_classes": list(result["classifier"].classes_),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset_row_count": {"train": train_rows, "test": test_rows},
        "metrics": result["metrics"],
    }
    joblib.dump(artifact, MODEL_PATH)
    print(f"[train_delay_model] Artefacto guardado en {MODEL_PATH}")


def _print_summary(result: dict[str, Any]) -> None:
    metrics = result["metrics"]
    print()
    print("=" * 60)
    print("MODELO PREDICTIVO ENTRENADO")
    print("=" * 60)
    print(f"{'Métrica':<24}{'Modelo ML':>15}{'Heurístico':>15}")
    ml = metrics["ml"]
    heur = metrics["heuristic_baseline"]
    for key in ml:
        print(f"{key:<24}{ml[key]:>15.3f}{heur[key]:>15.3f}")
    print(f"\nReferencia dispersión (arr_delay): {metrics['arr_delay_dispersion_reference']:.3f} min")
    print()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        train_df, test_df = load_train_test_frames()
        result = train_and_evaluate(train_df, test_df)
        save_artifact(result, len(train_df), len(test_df))
        _print_summary(result)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
