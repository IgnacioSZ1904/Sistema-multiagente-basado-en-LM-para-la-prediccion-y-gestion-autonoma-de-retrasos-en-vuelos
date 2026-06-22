"""
tests/unit/test_disruption_tools.py
======================================
Tests de funcionalidades básicas de tools/disruption_tools.py.

Igual que test_analytical_tools.py, se ejecutan contra la base de datos
real y se omiten si no está disponible.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from tools.disruption_tools import (
    DISRUPTION_TOOLS,
    estimate_affected_passengers,
    find_alternative_flights,
    get_airport_ground_activity,
)


pytestmark = pytest.mark.requires_db


class TestDisruptionToolsRegistry:
    """Verifica que DISRUPTION_TOOLS expone las herramientas esperadas."""

    def test_exports_exactly_three_tools(self):
        assert len(DISRUPTION_TOOLS) == 3

    def test_all_tools_are_read_only_by_design(self):
        # Verificación documental: ninguna debe contener INSERT/UPDATE/DELETE
        # en su implementación (comprobación de que no se ha introducido
        # accidentalmente escritura, alineado con la decisión de alcance).
        import inspect
        for tool in DISRUPTION_TOOLS:
            tool_func = getattr(tool, "func", tool)
            source = inspect.getsource(tool_func)
            assert "INSERT" not in source.upper()
            assert "UPDATE" not in source.upper()
            assert "DELETE FROM" not in source.upper()


class TestFindAlternativeFlights:
    """Tests de find_alternative_flights."""

    def test_returns_valid_json_list(self):
        result = find_alternative_flights.invoke({
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        assert isinstance(data, list)

    def test_each_candidate_has_expected_fields(self):
        result = find_alternative_flights.invoke({
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        if data:
            row = data[0]
            assert "airline" in row
            assert "scheduled_dep" in row
            assert "reliability_pct" in row
            assert "total_flights" in row

    def test_excludes_specified_airline(self):
        result = find_alternative_flights.invoke({
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "scheduled_dep": 1400,
            "exclude_airline": "AA",
        })
        data = json.loads(result)
        airlines = {row["airline"] for row in data}
        assert "AA" not in airlines

    def test_filters_low_volume_combinations(self):
        # HAVING COUNT(*) >= 10 en la query.
        result = find_alternative_flights.invoke({
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        for row in data:
            assert row["total_flights"] >= 10

    def test_returns_at_most_eight_candidates(self):
        result = find_alternative_flights.invoke({
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        assert len(data) <= 8

    def test_reliability_pct_is_within_valid_range(self):
        result = find_alternative_flights.invoke({
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        for row in data:
            assert 0.0 <= row["reliability_pct"] <= 100.0


class TestEstimateAffectedPassengers:
    """Tests de estimate_affected_passengers."""

    def test_returns_estimation_note_field(self):
        result = estimate_affected_passengers.invoke({
            "airline": "AA",
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "month": 3,
        })
        data = json.loads(result)
        assert "estimation_note" in data
        assert isinstance(data["estimation_note"], str)

    def test_estimated_passenger_load_is_fixed_heuristic_value(self):
        # Documentado en el código: 150 es la heurística fija declarada.
        result = estimate_affected_passengers.invoke({
            "airline": "AA",
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "month": 3,
        })
        data = json.loads(result)
        assert data["estimated_passenger_load"] == 150

    def test_handles_nonexistent_combination_gracefully(self):
        result = estimate_affected_passengers.invoke({
            "airline": "ZZ",
            "origin": "Ciudad Inexistente, XX",
            "destination": "Otra Ciudad, YY",
            "month": 1,
        })
        data = json.loads(result)
        assert data["total_historical_flights"] == 0


class TestGetAirportGroundActivity:
    """Tests de get_airport_ground_activity."""

    def test_returns_expected_structure(self):
        result = get_airport_ground_activity.invoke({
            "origin": "Chicago, IL",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        assert "hour" in data
        assert "avg_departures_in_hour" in data
        assert "avg_taxi_out_min" in data

    def test_hour_matches_input_scheduled_dep(self):
        result = get_airport_ground_activity.invoke({
            "origin": "Chicago, IL",
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        assert data["hour"] == 14

    def test_handles_nonexistent_airport_gracefully(self):
        result = get_airport_ground_activity.invoke({
            "origin": "Aeropuerto Inexistente, ZZ",
            "scheduled_dep": 900,
        })
        data = json.loads(result)
        # No debe lanzar excepción; debe devolver None o estructura vacía.
        assert "hour" in data