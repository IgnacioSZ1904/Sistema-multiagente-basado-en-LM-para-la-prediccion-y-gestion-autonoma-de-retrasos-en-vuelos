"""
tests/integration/test_analytical_agent.py
==============================================
Tests de integración del agente analítico CON EL LLM MOCKEADO.

No requieren Ollama corriendo. Se mockea get_llm() para simular
únicamente la fase ReAct (bind_tools + tool_calls); ya NO existe una
fase de síntesis con LLM — el ensamblaje de `analytics_result` y la
derivación de `delay_prediction` son deterministas (código puro), así
que se validan directamente sobre el resultado del nodo y, para la
predicción, también de forma unitaria.

Desde el evolutivo `prediccion-ml-real`, `delay_prediction` se calcula
con dos caminos posibles: el modelo entrenado
(`_derive_delay_prediction_ml`, usando el artefacto de
`data/train_delay_model.py`) o, si no está disponible, el heurístico
SQL anterior (`_derive_delay_prediction_heuristic`). El dispatcher
(`_derive_delay_prediction`) decide cuál usar. Ambos caminos se testean
por separado, con el modelo mockeado (no se depende de que el artefacto
real exista en disco para que la suite sea determinista).

Nota: los tests marcados con `requires_db` SÍ ejecutan las
herramientas reales contra DuckDB (no se mockean las tools), porque
son deterministas y rápidas; lo que se mockea es únicamente el LLM (y,
en su caso, el modelo predictivo). Los tests unitarios de predicción no
tocan la base de datos ni el LLM, por eso no llevan ese marcador.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from agents import analytical_agent as analytical_agent_module
from agents.analytical_agent import (
    _build_model_features,
    _derive_delay_prediction,
    _derive_delay_prediction_heuristic,
    _derive_delay_prediction_ml,
    _derive_flight_context,
    _load_delay_model,
    analytical_agent,
)
from config.settings import Settings
from data.train_delay_model import FEATURE_COLUMNS, fit_encoders
from graph.state import AnalyticsResult, SGIDAState


def _copy_state(state: dict) -> SGIDAState:
    """
    Copia superficial de un estado de prueba con el tipo correcto para
    el comprobador estático (Pylance/mypy). dict(state) en tiempo de
    ejecución ya produce un objeto perfectamente válido como SGIDAState
    (un TypedDict es un dict normal); este cast solo informa al analizador
    estático, no cambia el comportamiento en tiempo de ejecución.
    """
    return cast(SGIDAState, dict(state))


@pytest.fixture(autouse=True)
def _reset_delay_model_cache():
    """Evita fugas de estado entre tests a través de la caché a nivel de módulo."""
    analytical_agent_module._DELAY_MODEL_CACHE.clear()
    yield
    analytical_agent_module._DELAY_MODEL_CACHE.clear()


def _make_ai_message_with_tool_calls(calls: list[tuple[str, dict]]):
    """Construye un AIMessage que simula que el LLM pidió una o varias tools en el mismo turno."""
    msg = AIMessage(content="")
    msg.tool_calls = [
        {"name": name, "args": args, "id": f"call_{i}"}
        for i, (name, args) in enumerate(calls)
    ]
    return msg


def _make_ai_message_no_tool_call(content: str = ""):
    """Construye un AIMessage que simula que el LLM ya no necesita más tools."""
    msg = AIMessage(content=content)
    msg.tool_calls = []
    return msg


@pytest.mark.requires_db
class TestAnalyticalAgentExploratoryMode:
    """Integración: consulta exploratoria de extremo a extremo, LLM mockeado."""

    @patch("agents.analytical_agent.get_tool_llm")
    def test_multiple_tools_requested_in_one_turn_are_all_assembled(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([
                ("get_top_delay_airports", {"limit": 5}),
                ("get_delay_by_hour", {}),
            ]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        state["user_query"] = "¿Qué aeropuertos y qué franjas horarias son problemáticas?"

        result = analytical_agent(state)

        assert result["analytics_result"]["top_delay_airports"] is not None
        assert result["analytics_result"]["delay_by_hour"] is not None
        assert set(result["analytics_result"]["tools_used"]) == {
            "get_top_delay_airports", "get_delay_by_hour",
        }
        # Solo un turno para pedir ambas tools + un turno para confirmar que no hace falta más.
        assert react_llm.invoke.call_count == 2

    @patch("agents.analytical_agent.get_tool_llm")
    def test_exploratory_query_does_not_fill_delay_prediction(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert "delay_prediction" not in result

    @patch("agents.analytical_agent.get_tool_llm")
    def test_no_second_llm_call_is_made_for_synthesis(self, mock_get_llm, state_fresh):
        # Diseño clave de este evolutivo: el ensamblaje es determinista,
        # no debe existir ninguna llamada a with_structured_output().
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([("get_top_delay_routes", {"limit": 5})]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        analytical_agent(_copy_state(state_fresh))

        assert base_llm.with_structured_output.call_count == 0

    @patch("agents.analytical_agent.get_tool_llm")
    def test_messages_trace_is_built_deterministically_not_by_llm(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([("get_top_delay_airlines", {"limit": 5})]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        trace = result["messages"][0].content
        assert "get_top_delay_airlines" in trace


@pytest.mark.requires_db
class TestAnalyticalAgentFlightSpecificMode:
    """Integración: consulta sobre un vuelo concreto, LLM mockeado."""

    @patch("agents.analytical_agent.get_tool_llm")
    def test_flight_context_query_invokes_historical_stats_tool(
        self, mock_get_llm, state_fresh, sample_flight_context
    ):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([
                ("get_flight_historical_stats", {
                    "airline": "AA", "origin": "Chicago, IL",
                    "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
                }),
            ]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        state["flight_context"] = sample_flight_context
        state["user_query"] = "Analiza el histórico del vuelo AA Chicago-Denver en marzo a las 14:00"

        result = analytical_agent(state)

        assert result["analytics_result"]["flight_historical_stats"] is not None
        # sample_size puede ser 0 en el dataset real para esta combinación
        # concreta, pero delay_prediction siempre debe derivarse (con
        # confidence 0.0 en ese caso) porque la tool sí se invocó.
        assert "delay_prediction" in result
        assert result["delay_prediction"]["main_cause"] in {
            "carrier", "weather", "nas", "security", "late_aircraft", "unknown",
        }

    @patch("agents.analytical_agent.get_tool_llm")
    def test_flight_context_is_derived_without_being_pre_supplied(self, mock_get_llm, state_fresh):
        # Caso real de producción (ver revision-supervisor): nadie
        # rellena `flight_context` de antemano — el operador solo
        # escribe texto libre. El agente debe derivarlo él mismo de los
        # argumentos con los que el LLM invocó get_flight_historical_stats.
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([
                ("get_flight_historical_stats", {
                    "airline": "AA", "origin": "Chicago, IL",
                    "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
                }),
            ]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        assert state["flight_context"] is None
        state["user_query"] = "Predice el retraso del vuelo AA en la ruta de Chicago, IL a Denver, CO en marzo a las 14:00"

        result = analytical_agent(state)

        assert result["flight_context"] == {
            "airline": "AA", "origin": "Chicago, IL",
            "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
        }

    @patch("agents.analytical_agent.get_tool_llm")
    def test_cascade_risk_context_is_invoked_deterministically_even_if_llm_did_not_request_it(
        self, mock_get_llm, state_fresh, sample_flight_context
    ):
        # El LLM solo pide get_flight_historical_stats; nunca solicita
        # get_cascade_risk_context. Aun así, debe acabar presente en
        # analytics_result porque es un requisito de sistema, no una
        # decisión discrecional del LLM (ver refactor-agente-disrupcion).
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([
                ("get_flight_historical_stats", {
                    "airline": "AA", "origin": "Chicago, IL",
                    "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
                }),
            ]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        state = _copy_state(state_fresh)
        state["flight_context"] = sample_flight_context
        state["user_query"] = "Analiza el histórico del vuelo AA Chicago-Denver en marzo a las 14:00"

        result = analytical_agent(state)

        assert "cascade_risk_context" in result["analytics_result"]
        assert "get_cascade_risk_context" in result["analytics_result"]["tools_used"]

    @patch("agents.analytical_agent.get_tool_llm")
    def test_cascade_risk_context_not_forced_without_flight_context(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert "cascade_risk_context" not in result["analytics_result"]


class TestDeriveFlightContext:
    """
    Tests unitarios puros (sin DB, sin LLM) de la derivación determinista
    de FlightContext a partir de los argumentos de tool ya usados.
    """

    def test_returns_none_without_flight_historical_stats_call(self):
        assert _derive_flight_context([]) is None

    def test_returns_none_when_only_exploratory_tools_were_called(self):
        tool_results = [("get_top_delay_airports", {"limit": 5}, "[]")]
        assert _derive_flight_context(tool_results) is None

    def test_derives_flight_context_from_tool_args(self):
        tool_results = [
            ("get_flight_historical_stats", {
                "airline": "AA", "origin": "Chicago, IL",
                "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
            }, "{}"),
        ]

        flight_context = _derive_flight_context(tool_results)

        assert flight_context == {
            "airline": "AA", "origin": "Chicago, IL",
            "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
        }

    def test_last_call_wins_when_invoked_more_than_once(self):
        tool_results = [
            ("get_flight_historical_stats", {
                "airline": "AA", "origin": "Chicago, IL",
                "destination": "Denver, CO", "month": 3, "scheduled_dep": 1400,
            }, "{}"),
            ("get_flight_historical_stats", {
                "airline": "UA", "origin": "New York, NY",
                "destination": "Los Angeles, CA", "month": 6, "scheduled_dep": 900,
            }, "{}"),
        ]

        flight_context = _derive_flight_context(tool_results)

        assert flight_context["airline"] == "UA"

    def test_coerces_string_month_and_scheduled_dep_to_int(self):
        # Bug real detectado en validación manual (2026-07-27): un LLM
        # local puede devolver los argumentos numéricos de la tool_call
        # como string ("12", "0700") en vez de int. tool_call["args"]
        # guarda el valor tal cual el LLM lo generó, sin la coerción de
        # tipos que sí aplica LangChain al invocar la tool de verdad, así
        # que _derive_flight_context debe normalizarlos él mismo -si no,
        # el consumidor (_ensure_cascade_risk_context, _build_model_features)
        # revienta al hacer scheduled_dep // 100 sobre un string.
        tool_results = [
            ("get_flight_historical_stats", {
                "airline": "F9", "origin": "Denver, CO",
                "destination": "Chicago, IL", "month": "12", "scheduled_dep": "0700",
            }, "{}"),
        ]

        flight_context = _derive_flight_context(tool_results)

        assert flight_context["month"] == 12
        assert flight_context["scheduled_dep"] == 700
        assert isinstance(flight_context["month"], int)
        assert isinstance(flight_context["scheduled_dep"], int)


class TestDeriveDelayPredictionHeuristic:
    """
    Tests unitarios puros (sin DB, sin LLM) del heurístico SQL
    determinista que deriva delay_prediction a partir de
    flight_historical_stats. Es el camino FALLBACK cuando el modelo ML
    no está disponible (ver TestDeriveDelayPredictionDispatcher) — se
    conserva porque nunca deja al sistema sin predicción posible.
    """

    def test_returns_none_without_flight_historical_stats(self):
        assert _derive_delay_prediction_heuristic(AnalyticsResult()) is None

    def test_returns_zeroed_prediction_when_sample_size_is_zero(self):
        analytics_result = AnalyticsResult(flight_historical_stats={
            "airline": "ZZ", "origin": "X", "destination": "Y", "month": 1,
            "scheduled_dep": 100, "avg_dep_delay_min": None,
            "avg_arr_delay_min": None, "pct_over_threshold": None,
            "sample_size": 0, "dominant_delay_cause": "unknown",
        })
        prediction = _derive_delay_prediction_heuristic(analytics_result)
        assert prediction["is_disruption"] is False
        assert prediction["confidence"] == 0.0
        assert prediction["main_cause"] == "unknown"

    def test_is_disruption_true_when_avg_arrival_delay_exceeds_threshold(self):
        analytics_result = AnalyticsResult(flight_historical_stats={
            "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
            "month": 3, "scheduled_dep": 1400, "avg_dep_delay_min": 40.0,
            "avg_arr_delay_min": Settings.DELAY_THRESHOLD_MINUTES + 30.0,
            "pct_over_threshold": 70.0, "sample_size": 250,
            "dominant_delay_cause": "weather",
        })
        prediction = _derive_delay_prediction_heuristic(analytics_result)
        assert prediction["is_disruption"] is True
        assert prediction["main_cause"] == "weather"

    def test_is_disruption_false_when_avg_arrival_delay_below_threshold(self):
        analytics_result = AnalyticsResult(flight_historical_stats={
            "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
            "month": 3, "scheduled_dep": 1400, "avg_dep_delay_min": 2.0,
            "avg_arr_delay_min": max(Settings.DELAY_THRESHOLD_MINUTES - 10.0, 0.0),
            "pct_over_threshold": 5.0, "sample_size": 250,
            "dominant_delay_cause": "unknown",
        })
        prediction = _derive_delay_prediction_heuristic(analytics_result)
        assert prediction["is_disruption"] is False

    def test_confidence_increases_with_sample_size(self):
        def _confidence_for(sample_size: int) -> float:
            analytics_result = AnalyticsResult(flight_historical_stats={
                "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
                "month": 3, "scheduled_dep": 1400, "avg_dep_delay_min": 10.0,
                "avg_arr_delay_min": 10.0, "pct_over_threshold": 20.0,
                "sample_size": sample_size, "dominant_delay_cause": "carrier",
            })
            return _derive_delay_prediction_heuristic(analytics_result)["confidence"]

        confidence_low = _confidence_for(10)
        confidence_mid = _confidence_for(100)
        confidence_high = _confidence_for(500)

        assert confidence_low < confidence_mid < confidence_high
        assert confidence_low <= 0.5
        assert confidence_high >= 0.8

    def test_main_cause_is_taken_verbatim_from_dominant_delay_cause(self):
        analytics_result = AnalyticsResult(flight_historical_stats={
            "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
            "month": 3, "scheduled_dep": 1400, "avg_dep_delay_min": 10.0,
            "avg_arr_delay_min": 10.0, "pct_over_threshold": 20.0,
            "sample_size": 50, "dominant_delay_cause": "nas",
        })
        prediction = _derive_delay_prediction_heuristic(analytics_result)
        assert prediction["main_cause"] == "nas"


# ---------------------------------------------------------------------------
# Modelo ML (evolutivo prediccion-ml-real)
# ---------------------------------------------------------------------------

_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL = {
    "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
    "month": 3, "scheduled_dep": 1400,
}


class _FakeTree:
    """Simula un árbol individual del RandomForestRegressor (solo .predict)."""

    def __init__(self, dep_pred: float, arr_pred: float):
        self._pred = np.array([[dep_pred, arr_pred]])

    def predict(self, x):
        return self._pred


class _FakeRegressor:
    """Simula RandomForestRegressor: predicción fija + árboles con dispersión controlada."""

    def __init__(self, dep_pred: float, arr_pred: float, tree_arr_values: list[float]):
        self._dep_pred = dep_pred
        self._arr_pred = arr_pred
        self.estimators_ = [_FakeTree(dep_pred, v) for v in tree_arr_values]

    def predict(self, x):
        return np.array([[self._dep_pred, self._arr_pred]])


class _FakeClassifier:
    """Simula RandomForestClassifier: siempre predice la misma etiqueta."""

    def __init__(self, label: str):
        self._label = label
        self.classes_ = np.array([label])

    def predict(self, x):
        return np.array([self._label])


def _make_fake_artifact(
    dep_pred: float = 20.0,
    arr_pred: float = 25.0,
    tree_arr_values: list[float] | None = None,
    cause_label: str = "weather",
    dispersion_reference: float = 5.0,
) -> dict:
    """
    Artefacto de prueba con la misma forma que produce
    data/train_delay_model.py, pero con regresor/clasificador falsos
    para controlar exactamente la predicción y la dispersión entre
    árboles en cada test. Los encoders SÍ son reales (entrenados sobre
    un DataFrame mínimo con `fit_encoders`), para probar el encoding de
    verdad sin depender del dataset completo.
    """
    if tree_arr_values is None:
        tree_arr_values = [arr_pred] * 10  # sin dispersión por defecto

    small_df = pd.DataFrame({
        "airline": ["AA", "UA"],
        "origin": ["Chicago, IL", "New York, NY"],
        "destination": ["Denver, CO", "Los Angeles, CA"],
    })
    encoders = fit_encoders(small_df)

    return {
        "regressor": _FakeRegressor(dep_pred, arr_pred, tree_arr_values),
        "classifier": _FakeClassifier(cause_label),
        "encoders": encoders,
        "feature_columns": FEATURE_COLUMNS,
        "metrics": {"arr_delay_dispersion_reference": dispersion_reference},
    }


class TestBuildModelFeatures:
    """Tests unitarios puros de la construcción del vector de features del modelo."""

    def test_returns_none_when_required_field_missing(self):
        artifact = _make_fake_artifact()
        incomplete_context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "destination": None}
        assert _build_model_features(incomplete_context, artifact) is None

    def test_uses_distance_from_flight_context_when_present(self):
        artifact = _make_fake_artifact()
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 920.0}
        features = _build_model_features(context, artifact)
        assert features is not None
        assert features.shape == (1, len(FEATURE_COLUMNS))
        assert features[0][FEATURE_COLUMNS.index("distance")] == 920.0

    @patch("agents.analytical_agent._lookup_route_distance", return_value=750.0)
    def test_looks_up_distance_when_not_in_flight_context(self, mock_lookup):
        artifact = _make_fake_artifact()
        features = _build_model_features(_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, artifact)

        mock_lookup.assert_called_once_with("Chicago, IL", "Denver, CO")
        assert features[0][FEATURE_COLUMNS.index("distance")] == 750.0

    @patch("agents.analytical_agent._lookup_route_distance", return_value=None)
    def test_returns_none_when_distance_cannot_be_determined(self, mock_lookup):
        artifact = _make_fake_artifact()
        assert _build_model_features(_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, artifact) is None


class TestDeriveDelayPredictionMl:
    """Tests unitarios puros de la inferencia ML (regresor + clasificador + confidence)."""

    def test_returns_none_when_features_incomplete(self):
        artifact = _make_fake_artifact()
        incomplete_context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "airline": None}
        assert _derive_delay_prediction_ml(incomplete_context, artifact) is None

    def test_is_disruption_true_when_predicted_arrival_delay_exceeds_threshold(self):
        artifact = _make_fake_artifact(arr_pred=Settings.DELAY_THRESHOLD_MINUTES + 20.0)
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 900.0}
        prediction = _derive_delay_prediction_ml(context, artifact)
        assert prediction["is_disruption"] is True

    def test_is_disruption_false_when_predicted_arrival_delay_below_threshold(self):
        artifact = _make_fake_artifact(arr_pred=max(Settings.DELAY_THRESHOLD_MINUTES - 5.0, 0.0))
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 900.0}
        prediction = _derive_delay_prediction_ml(context, artifact)
        assert prediction["is_disruption"] is False

    def test_main_cause_comes_from_classifier(self):
        artifact = _make_fake_artifact(cause_label="nas")
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 900.0}
        prediction = _derive_delay_prediction_ml(context, artifact)
        assert prediction["main_cause"] == "nas"

    def test_confidence_is_high_when_trees_agree(self):
        artifact = _make_fake_artifact(arr_pred=30.0, tree_arr_values=[30.0] * 20)
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 900.0}
        prediction = _derive_delay_prediction_ml(context, artifact)
        assert prediction["confidence"] >= 0.9

    def test_confidence_is_lower_when_trees_disagree(self):
        agree_artifact = _make_fake_artifact(arr_pred=30.0, tree_arr_values=[30.0] * 20)
        disagree_artifact = _make_fake_artifact(
            arr_pred=30.0, tree_arr_values=[10.0, 20.0, 30.0, 40.0, 50.0] * 4
        )
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 900.0}

        confidence_agree = _derive_delay_prediction_ml(context, agree_artifact)["confidence"]
        confidence_disagree = _derive_delay_prediction_ml(context, disagree_artifact)["confidence"]

        assert confidence_disagree < confidence_agree

    def test_negative_delay_prediction_is_clipped_to_zero(self):
        artifact = _make_fake_artifact(dep_pred=-5.0, arr_pred=-3.0, tree_arr_values=[-3.0] * 10)
        context = {**_SAMPLE_FLIGHT_CONTEXT_FOR_MODEL, "distance": 900.0}
        prediction = _derive_delay_prediction_ml(context, artifact)
        assert prediction["expected_dep_delay_min"] == 0.0
        assert prediction["expected_arr_delay_min"] == 0.0


class TestLoadDelayModel:
    """Tests unitarios de la carga perezosa/cacheada del artefacto del modelo."""

    def test_returns_none_and_logs_warning_when_file_does_not_exist(self, tmp_path):
        missing_path = tmp_path / "no_existe.joblib"
        with patch.object(Settings, "DELAY_MODEL_PATH", str(missing_path)):
            assert _load_delay_model() is None

    def test_returns_none_when_load_raises(self, tmp_path):
        broken_path = tmp_path / "roto.joblib"
        broken_path.write_text("no es un joblib válido")
        with patch.object(Settings, "DELAY_MODEL_PATH", str(broken_path)):
            assert _load_delay_model() is None

    def test_loads_and_caches_valid_artifact(self, tmp_path):
        import joblib

        artifact_path = tmp_path / "delay_model.joblib"
        joblib.dump({"trained_at": "2026-01-01", "marker": "test-artifact"}, artifact_path)

        with patch.object(Settings, "DELAY_MODEL_PATH", str(artifact_path)):
            with patch("agents.analytical_agent.joblib.load", wraps=joblib.load) as spy_load:
                first = _load_delay_model()
                second = _load_delay_model()

        assert first["marker"] == "test-artifact"
        assert second is first
        spy_load.assert_called_once()


class TestDeriveDelayPredictionDispatcher:
    """
    Tests del despachador `_derive_delay_prediction`: decide entre el
    modelo ML y el heurístico SQL. Ninguno de los dos caminos internos
    se ejecuta de verdad aquí (ambos se mockean) — solo se verifica la
    lógica de decisión.
    """

    _STATS_WITH_DATA = {
        "airline": "AA", "origin": "Chicago, IL", "destination": "Denver, CO",
        "month": 3, "scheduled_dep": 1400, "avg_dep_delay_min": 10.0,
        "avg_arr_delay_min": 10.0, "pct_over_threshold": 20.0,
        "sample_size": 50, "dominant_delay_cause": "carrier",
    }

    def test_returns_none_without_flight_historical_stats(self):
        assert _derive_delay_prediction(AnalyticsResult(), _SAMPLE_FLIGHT_CONTEXT_FOR_MODEL) is None

    @patch("agents.analytical_agent._load_delay_model")
    def test_does_not_attempt_ml_without_flight_context(self, mock_load_model):
        analytics_result = AnalyticsResult(flight_historical_stats=self._STATS_WITH_DATA)
        prediction = _derive_delay_prediction(analytics_result, None)

        mock_load_model.assert_not_called()
        assert prediction == _derive_delay_prediction_heuristic(analytics_result)

    @patch("agents.analytical_agent._load_delay_model", return_value=None)
    def test_falls_back_to_heuristic_when_model_not_available(self, mock_load_model):
        analytics_result = AnalyticsResult(flight_historical_stats=self._STATS_WITH_DATA)
        prediction = _derive_delay_prediction(analytics_result, _SAMPLE_FLIGHT_CONTEXT_FOR_MODEL)

        assert prediction == _derive_delay_prediction_heuristic(analytics_result)

    @patch("agents.analytical_agent._derive_delay_prediction_ml")
    @patch("agents.analytical_agent._load_delay_model")
    def test_uses_ml_prediction_when_available(self, mock_load_model, mock_derive_ml):
        mock_load_model.return_value = {"fake": "artifact"}
        ml_prediction = {
            "expected_dep_delay_min": 12.0, "expected_arr_delay_min": 18.0,
            "is_disruption": True, "confidence": 0.8, "main_cause": "weather",
        }
        mock_derive_ml.return_value = ml_prediction

        analytics_result = AnalyticsResult(flight_historical_stats=self._STATS_WITH_DATA)
        prediction = _derive_delay_prediction(analytics_result, _SAMPLE_FLIGHT_CONTEXT_FOR_MODEL)

        assert prediction == ml_prediction

    @patch("agents.analytical_agent._derive_delay_prediction_ml", return_value=None)
    @patch("agents.analytical_agent._load_delay_model")
    def test_falls_back_to_heuristic_when_ml_returns_none(self, mock_load_model, mock_derive_ml):
        # El modelo está cargado, pero no pudo inferir (p.ej. features
        # incompletas) — no debe dejar al sistema sin predicción.
        mock_load_model.return_value = {"fake": "artifact"}

        analytics_result = AnalyticsResult(flight_historical_stats=self._STATS_WITH_DATA)
        prediction = _derive_delay_prediction(analytics_result, _SAMPLE_FLIGHT_CONTEXT_FOR_MODEL)

        assert prediction == _derive_delay_prediction_heuristic(analytics_result)


@pytest.mark.requires_db
class TestAnalyticalAgentReactLoopBehavior:
    """Integración: comportamiento del bucle ReAct ante distintos escenarios del LLM."""

    @patch("agents.analytical_agent.get_tool_llm")
    def test_stops_loop_when_llm_requests_no_tool_calls(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_no_tool_call()

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        analytical_agent(_copy_state(state_fresh))

        # El bucle debe parar tras la primera invocación, sin más llamadas.
        assert react_llm.invoke.call_count == 1

    @patch("agents.analytical_agent.get_tool_llm")
    def test_respects_max_react_turns_limit(self, mock_get_llm, state_fresh):
        # El LLM "insiste" en pedir tools indefinidamente; el bucle debe
        # detenerse tras _MAX_REACT_TURNS turnos (3), no continuar para siempre.
        react_llm = MagicMock()
        react_llm.invoke.return_value = _make_ai_message_with_tool_calls([
            ("get_delay_by_month", {}),
        ])

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert react_llm.invoke.call_count == 3  # _MAX_REACT_TURNS
        assert "error" not in result  # debe ensamblar igualmente, no fallar

    @patch("agents.analytical_agent.get_tool_llm")
    def test_unknown_tool_name_does_not_crash_the_agent(self, mock_get_llm, state_fresh):
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([("herramienta_inexistente", {})]),
            _make_ai_message_no_tool_call(),
        ]

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        result = analytical_agent(_copy_state(state_fresh))

        assert "error" not in result
        assert result["analytics_result"] is not None
        # La tool desconocida no debe rellenar ningún campo real.
        assert "herramienta_inexistente" not in result["analytics_result"]


class TestAnalyticalAgentDegradedMode:
    """Modo degradado: Ollama no disponible."""

    @patch("agents.analytical_agent.Settings.ollama_available", return_value=False)
    def test_degraded_mode_returns_typed_empty_result_without_calling_llm(
        self, mock_ollama_available, state_fresh
    ):
        with patch("agents.analytical_agent.get_tool_llm") as mock_get_llm:
            result = analytical_agent(_copy_state(state_fresh))

            mock_get_llm.assert_not_called()

        assert result["analytics_result"]["tools_used"] == []
        assert "delay_prediction" not in result


class TestAnalyticalAgentErrorHandling:
    """Integración: el agente debe degradar a state['error'], no lanzar excepción."""

    @patch("agents.analytical_agent.get_tool_llm")
    def test_llm_exception_is_captured_as_state_error(self, mock_get_llm, state_fresh):
        mock_get_llm.side_effect = RuntimeError("Ollama no responde")

        result = analytical_agent(_copy_state(state_fresh))

        assert "error" in result
        assert "analytical_agent" in result["error"]

    @patch("agents.analytical_agent.get_tool_llm")
    def test_malformed_tool_json_is_skipped_without_crashing(self, mock_get_llm, state_fresh):
        # Simula una tool que devuelve texto no-JSON (p.ej. un error de
        # ejecución capturado como string): el ensamblaje determinista
        # debe ignorarlo sin lanzar excepción.
        react_llm = MagicMock()
        react_llm.invoke.side_effect = [
            _make_ai_message_with_tool_calls([("get_top_delay_airports", {"limit": -1})]),
            _make_ai_message_no_tool_call(),
        ]

        broken_tool = MagicMock()
        broken_tool.invoke.side_effect = Exception("boom")

        base_llm = MagicMock()
        base_llm.bind_tools.return_value = react_llm
        mock_get_llm.return_value = base_llm

        with patch.dict("agents.analytical_agent._TOOLS_BY_NAME", {"get_top_delay_airports": broken_tool}):
            result = analytical_agent(_copy_state(state_fresh))

        assert "error" not in result
        assert result["analytics_result"] is not None
