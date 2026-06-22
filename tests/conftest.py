"""
tests/conftest.py
===================
Fixtures compartidas por toda la suite de tests de SGIDA.

Incluye, entre otras:
  - `db_available`: comprueba si analytical_db.duckdb existe, para que
    los tests que dependen de la base de datos real se salten (skip)
    automáticamente en entornos donde el dataset no está descargado
    (p. ej. CI), en lugar de fallar.
  - Constructores de SGIDAState de ejemplo para distintos escenarios,
    reutilizables en tests unitarios y de integración.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from graph.state import (
    AnalyticsResult,
    DelayPrediction,
    DisruptionProposal,
    FlightContext,
    initial_state,
)


# ---------------------------------------------------------------------------
# Disponibilidad de la base de datos real
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_available() -> bool:
    """True si analytical_db.duckdb existe en la ruta configurada."""
    return Path(Settings.DB_PATH).exists()


@pytest.fixture(autouse=True)
def _skip_if_no_db(request, db_available):
    """
    Salta automáticamente cualquier test marcado con
    @pytest.mark.requires_db si la base de datos real no está disponible.
    """
    if request.node.get_closest_marker("requires_db") and not db_available:
        pytest.skip(
            f"analytical_db.duckdb no encontrada en '{Settings.DB_PATH}'; "
            "se omite el test (requiere el dataset real)."
        )


# ---------------------------------------------------------------------------
# Datos de vuelo de ejemplo, coherentes con el dataset BTS real
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_flight_context() -> FlightContext:
    """Contexto de vuelo de ejemplo, con valores plausibles del dataset BTS."""
    return FlightContext(
        airline="AA",
        origin="Chicago, IL",
        destination="Denver, CO",
        flight_date="2018-03-10",
        year=2018,
        month=3,
        day=10,
        scheduled_dep=1400,
        scheduled_arr=1545,
        distance=920.0,
    )


@pytest.fixture
def sample_delay_prediction_disrupted() -> DelayPrediction:
    """Predicción de ejemplo que SÍ constituye una disrupción."""
    return DelayPrediction(
        expected_dep_delay_min=45.0,
        expected_arr_delay_min=52.0,
        is_disruption=True,
        confidence=0.75,
        main_cause="weather",
    )


@pytest.fixture
def sample_delay_prediction_ok() -> DelayPrediction:
    """Predicción de ejemplo que NO constituye una disrupción."""
    return DelayPrediction(
        expected_dep_delay_min=5.0,
        expected_arr_delay_min=3.0,
        is_disruption=False,
        confidence=0.9,
        main_cause="unknown",
    )


@pytest.fixture
def sample_disruption_proposal() -> DisruptionProposal:
    """Propuesta de disrupción de ejemplo."""
    return DisruptionProposal(
        proposal_id="PROP-test0001",
        severity="high",
        actions=[
            "Reasignar pasajeros al vuelo UA890 de las 16:10",
            "Notificar a personal de puerta sobre posible saturación",
        ],
        affected_passengers_est=150,
        alternative_flights=["UA890 - 16:10", "DL220 - 17:00"],
        reasoning="Retraso de 52 min por causa meteorológica, sin margen "
        "operativo suficiente en el aeropuerto de origen.",
    )


@pytest.fixture
def sample_analytics_result() -> AnalyticsResult:
    """Resultado analítico exploratorio de ejemplo."""
    return AnalyticsResult(
        top_delay_airports=[
            {"origin": "Chicago, IL", "avg_dep_delay_min": 18.4, "total_flights": 50000},
        ],
        delay_causes_pct={"carrier": 30.0, "weather": 15.0, "nas": 35.0,
                          "security": 1.0, "late_aircraft": 19.0},
    )


# ---------------------------------------------------------------------------
# Estados completos de ejemplo (para tests de router / supervisor)
# ---------------------------------------------------------------------------

@pytest.fixture
def state_fresh():
    """Estado recién creado, sin ningún agente ejecutado todavía."""
    return initial_state("¿Qué aeropuertos tienen más retrasos?")


@pytest.fixture
def state_with_exploratory_result(state_fresh, sample_analytics_result):
    """Estado tras ejecutar el agente analítico en modo exploratorio."""
    state = dict(state_fresh)
    state["analytics_result"] = sample_analytics_result
    state["iteration"] = 1
    return state


@pytest.fixture
def state_with_disruption_prediction(state_fresh, sample_flight_context, sample_delay_prediction_disrupted):
    """Estado tras ejecutar el agente analítico, con una disrupción detectada."""
    state = dict(state_fresh)
    state["flight_context"] = sample_flight_context
    state["delay_prediction"] = sample_delay_prediction_disrupted
    state["iteration"] = 1
    return state


@pytest.fixture
def state_with_disruption_proposal(state_with_disruption_prediction, sample_disruption_proposal):
    """Estado tras ejecutar también el agente de disrupciones."""
    state = dict(state_with_disruption_prediction)
    state["disruption_proposal"] = sample_disruption_proposal
    state["iteration"] = 2
    return state


@pytest.fixture
def state_with_error(state_fresh):
    """Estado en el que un agente ha fallado."""
    state = dict(state_fresh)
    state["error"] = "Error en analytical_agent: timeout de conexión a la base de datos."
    state["iteration"] = 1
    return state


@pytest.fixture
def state_with_final_response(state_with_exploratory_result):
    """Estado completo, listo para terminar (final_response ya generado)."""
    state = dict(state_with_exploratory_result)
    state["final_response"] = "Los aeropuertos con más retrasos son..."
    state["iteration"] = 2
    return state