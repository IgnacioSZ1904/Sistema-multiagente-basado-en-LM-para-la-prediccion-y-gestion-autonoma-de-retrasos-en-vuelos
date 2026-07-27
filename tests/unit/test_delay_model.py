"""
tests/unit/test_delay_model.py
=================================
Tests del pipeline de entrenamiento (data/train_delay_model.py).

Se entrena sobre un dataset SINTÉTICO pequeño construido en memoria
(no sobre las ~30M filas reales de analytical_db.duckdb), para que la
suite siga siendo rápida y no dependa del dataset descargado. Cubre
`add_dominant_cause`, el encoding de categóricas, el entrenamiento +
evaluación de punta a punta, y la serialización/carga del artefacto.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data import train_delay_model as m


# ---------------------------------------------------------------------------
# Dataset sintético
# ---------------------------------------------------------------------------

def _make_synthetic_frame(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    airlines = np.array(["AA", "DL", "UA"])
    origins = np.array(["Chicago, IL", "New York, NY", "Denver, CO"])
    destinations = np.array(["Los Angeles, CA", "Atlanta, GA", "Denver, CO"])

    dep_delay = rng.gamma(shape=1.5, scale=8.0, size=n)
    arr_delay = dep_delay + rng.normal(0, 3, size=n)
    arr_delay = np.clip(arr_delay, 0, None)

    # La mitad de los vuelos no tiene causa de retraso atribuida (0 en las
    # 5 columnas) -> dominant_cause debe salir "unknown" para esas filas.
    has_cause = rng.random(n) > 0.5
    carrier = np.where(has_cause, rng.gamma(1.0, 5.0, size=n), 0.0)
    weather = np.where(has_cause, rng.gamma(1.0, 2.0, size=n), 0.0)
    nas = np.where(has_cause, rng.gamma(1.0, 2.0, size=n), 0.0)
    security = np.zeros(n)
    late_aircraft = np.where(has_cause, rng.gamma(1.0, 1.0, size=n), 0.0)

    return pd.DataFrame({
        "airline": rng.choice(airlines, size=n),
        "origin": rng.choice(origins, size=n),
        "destination": rng.choice(destinations, size=n),
        "month": rng.integers(1, 13, size=n),
        "scheduled_dep_hour": rng.integers(0, 24, size=n),
        "distance": rng.uniform(200, 2000, size=n),
        "dep_delay": dep_delay,
        "arr_delay": arr_delay,
        "carrier_delay": carrier,
        "weather_delay": weather,
        "nas_delay": nas,
        "security_delay": security,
        "late_aircraft_delay": late_aircraft,
    })


@pytest.fixture
def synthetic_train_test():
    train_df = _make_synthetic_frame(400, seed=1)
    test_df = _make_synthetic_frame(150, seed=2)
    return train_df, test_df


@pytest.fixture(autouse=True)
def _small_forest(monkeypatch):
    """Bosques pequeños en los tests: mismo pipeline, mucho más rápido."""
    monkeypatch.setattr(m, "N_ESTIMATORS", 10)
    monkeypatch.setattr(m, "MAX_DEPTH", 6)
    monkeypatch.setattr(m, "DISPERSION_REFERENCE_SAMPLE", 50)


# ---------------------------------------------------------------------------
# Causa dominante por fila
# ---------------------------------------------------------------------------

class TestDominantCause:
    def test_all_zero_returns_unknown(self):
        row = pd.Series({c: 0.0 for c in m.CAUSE_COLUMNS})
        assert m._dominant_cause_row(row) == m.UNKNOWN_CAUSE

    def test_picks_the_column_with_more_minutes(self):
        row = pd.Series({
            "carrier_delay": 5.0, "weather_delay": 40.0, "nas_delay": 2.0,
            "security_delay": 0.0, "late_aircraft_delay": 3.0,
        })
        assert m._dominant_cause_row(row) == "weather"

    def test_tiebreak_prefers_carrier_over_others(self):
        row = pd.Series({
            "carrier_delay": 10.0, "weather_delay": 10.0, "nas_delay": 10.0,
            "security_delay": 10.0, "late_aircraft_delay": 10.0,
        })
        assert m._dominant_cause_row(row) == "carrier"

    def test_security_wins_when_strictly_greater(self):
        row = pd.Series({
            "carrier_delay": 5.0, "weather_delay": 5.0, "nas_delay": 5.0,
            "security_delay": 50.0, "late_aircraft_delay": 5.0,
        })
        assert m._dominant_cause_row(row) == "security"


# ---------------------------------------------------------------------------
# Encoding de categóricas
# ---------------------------------------------------------------------------

class TestEncoding:
    def test_fit_encoders_covers_all_categorical_columns(self, synthetic_train_test):
        train_df, _ = synthetic_train_test
        encoders = m.fit_encoders(train_df)
        assert set(encoders.keys()) == set(m.CATEGORICAL_COLUMNS)

    def test_encode_features_shape_matches_feature_columns(self, synthetic_train_test):
        train_df, _ = synthetic_train_test
        encoders = m.fit_encoders(train_df)
        features = m.encode_features(train_df, encoders)
        assert features.shape == (len(train_df), len(m.FEATURE_COLUMNS))

    def test_unseen_category_encodes_without_exception(self, synthetic_train_test):
        train_df, _ = synthetic_train_test
        encoders = m.fit_encoders(train_df)
        unseen = encoders["airline"].transform([["ZZ-no-existe"]])
        assert unseen[0][0] == -1


# ---------------------------------------------------------------------------
# Entrenamiento + evaluación de punta a punta
# ---------------------------------------------------------------------------

class TestTrainAndEvaluate:
    def test_produces_all_expected_artifact_components(self, synthetic_train_test):
        train_df, test_df = synthetic_train_test
        result = m.train_and_evaluate(train_df, test_df)

        assert "regressor" in result and "classifier" in result
        assert set(result["encoders"].keys()) == set(m.CATEGORICAL_COLUMNS)
        assert len(result["classifier"].classes_) > 0

    def test_metrics_have_expected_shape(self, synthetic_train_test):
        train_df, test_df = synthetic_train_test
        result = m.train_and_evaluate(train_df, test_df)
        metrics = result["metrics"]

        expected_keys = {
            "dep_delay_mae", "dep_delay_rmse", "arr_delay_mae",
            "arr_delay_rmse", "main_cause_accuracy", "main_cause_f1_macro",
        }
        assert expected_keys.issubset(metrics["ml"].keys())
        assert expected_keys.issubset(metrics["heuristic_baseline"].keys())
        assert metrics["arr_delay_dispersion_reference"] >= 0.0

    def test_regressor_predicts_two_outputs(self, synthetic_train_test):
        train_df, test_df = synthetic_train_test
        result = m.train_and_evaluate(train_df, test_df)
        encoders = result["encoders"]
        features = m.encode_features(test_df.head(3), encoders)
        prediction = result["regressor"].predict(features)
        assert prediction.shape == (3, 2)


# ---------------------------------------------------------------------------
# Serialización del artefacto
# ---------------------------------------------------------------------------

class TestSaveArtifact:
    def test_save_artifact_roundtrip(self, synthetic_train_test, tmp_path, monkeypatch):
        train_df, test_df = synthetic_train_test
        result = m.train_and_evaluate(train_df, test_df)

        artifact_path = tmp_path / "delay_model.joblib"
        monkeypatch.setattr(m, "MODEL_PATH", artifact_path)

        m.save_artifact(result, len(train_df), len(test_df))
        assert artifact_path.exists()

        import joblib
        loaded = joblib.load(artifact_path)
        assert loaded["feature_columns"] == m.FEATURE_COLUMNS
        assert loaded["dataset_row_count"] == {"train": len(train_df), "test": len(test_df)}
        assert "metrics" in loaded
