"""
tests/unit/test_analytical_tools.py
======================================
Tests de funcionalidades básicas de tools/analytical_tools.py.

Se ejecutan contra analytical_db.duckdb REAL (no mockeada, según se ha
decidido para este TFG). Todos los tests están marcados con
@pytest.mark.requires_db y se omiten automáticamente si el fichero no
existe en la ruta configurada (ver tests/conftest.py).

No se valida el VALOR exacto de los resultados (depende de los 30M
filas reales, que pueden variar si se reimporta el dataset), sino la
ESTRUCTURA y el TIPO de los resultados devueltos, que es lo que importa
para que los agentes puedan consumirlos de forma fiable.
"""

from __future__ import annotations

import json

import pytest

from tools.analytical_tools import (
    ANALYTICAL_TOOLS,
    get_delay_by_hour,
    get_delay_by_month,
    get_delay_causes_breakdown,
    get_top_delay_airlines,
    get_top_delay_airports,
    get_top_delay_routes,
    predict_flight_delay,
)


pytestmark = pytest.mark.requires_db


class TestAnalyticalToolsRegistry:
    """Verifica que ANALYTICAL_TOOLS expone las herramientas esperadas."""

    def test_exports_exactly_eight_tools(self):
        assert len(ANALYTICAL_TOOLS) == 8

    def test_all_tools_have_name_and_description(self):
        for tool in ANALYTICAL_TOOLS:
            assert tool.name
            assert tool.description


class TestGetTopDelayAirports:
    """Tests de get_top_delay_airports."""

    def test_returns_valid_json(self):
        result = get_top_delay_airports.invoke({"limit": 5})
        data = json.loads(result)
        assert isinstance(data, list)

    def test_respects_limit_parameter(self):
        result = get_top_delay_airports.invoke({"limit": 3})
        data = json.loads(result)
        assert len(data) <= 3

    def test_each_row_has_expected_fields(self):
        result = get_top_delay_airports.invoke({"limit": 5})
        data = json.loads(result)
        if data:  # puede estar vacío en datasets degenerados, pero no aquí
            row = data[0]
            assert "origin" in row
            assert "avg_dep_delay_min" in row
            assert "total_flights" in row
            assert "pct_delayed" in row

    def test_results_are_sorted_descending_by_delay(self):
        result = get_top_delay_airports.invoke({"limit": 10})
        data = json.loads(result)
        delays = [row["avg_dep_delay_min"] for row in data]
        assert delays == sorted(delays, reverse=True)

    def test_default_limit_is_ten(self):
        result = get_top_delay_airports.invoke({})
        data = json.loads(result)
        assert len(data) <= 10


class TestGetTopDelayAirlines:
    """Tests de get_top_delay_airlines."""

    def test_returns_valid_json_with_expected_fields(self):
        result = get_top_delay_airlines.invoke({"limit": 5})
        data = json.loads(result)
        assert isinstance(data, list)
        if data:
            assert "airline" in data[0]
            assert "avg_arr_delay_min" in data[0]

    def test_airline_codes_are_short_strings(self):
        # Los códigos IATA de aerolínea son típicamente 2 caracteres alfanuméricos.
        result = get_top_delay_airlines.invoke({"limit": 10})
        data = json.loads(result)
        for row in data:
            assert isinstance(row["airline"], str)
            assert 1 <= len(row["airline"]) <= 3


class TestGetTopDelayRoutes:
    """Tests de get_top_delay_routes."""

    def test_returns_origin_and_destination_pairs(self):
        result = get_top_delay_routes.invoke({"limit": 5})
        data = json.loads(result)
        if data:
            assert "origin" in data[0]
            assert "destination" in data[0]

    def test_filters_low_volume_routes(self):
        # La query tiene HAVING COUNT(*) > 100; ningún resultado debería
        # tener menos de 100 vuelos históricos.
        result = get_top_delay_routes.invoke({"limit": 10})
        data = json.loads(result)
        for row in data:
            assert row["total_flights"] > 100


class TestGetDelayByMonth:
    """Tests de get_delay_by_month."""

    def test_returns_at_most_twelve_months(self):
        result = get_delay_by_month.invoke({})
        data = json.loads(result)
        assert len(data) <= 12

    def test_months_are_in_valid_range(self):
        result = get_delay_by_month.invoke({})
        data = json.loads(result)
        for row in data:
            assert 1 <= row["month"] <= 12

    def test_months_are_ordered_ascending(self):
        result = get_delay_by_month.invoke({})
        data = json.loads(result)
        months = [row["month"] for row in data]
        assert months == sorted(months)


class TestGetDelayByHour:
    """Tests de get_delay_by_hour."""

    def test_hours_are_in_valid_range(self):
        result = get_delay_by_hour.invoke({})
        data = json.loads(result)
        for row in data:
            assert 0 <= row["hour"] <= 23

    def test_hours_are_ordered_ascending(self):
        result = get_delay_by_hour.invoke({})
        data = json.loads(result)
        hours = [row["hour"] for row in data]
        assert hours == sorted(hours)


class TestGetDelayCausesBreakdown:
    """Tests de get_delay_causes_breakdown."""

    def test_returns_exactly_five_causes(self):
        result = get_delay_causes_breakdown.invoke({})
        data = json.loads(result)
        assert len(data) == 5

    def test_causes_are_the_five_expected_values(self):
        result = get_delay_causes_breakdown.invoke({})
        data = json.loads(result)
        causes = {row["cause"] for row in data}
        assert causes == {"carrier", "weather", "nas", "security", "late_aircraft"}

    def test_percentages_sum_approximately_to_100(self):
        result = get_delay_causes_breakdown.invoke({})
        data = json.loads(result)
        total_pct = sum(row["pct"] for row in data)
        assert 99.0 <= total_pct <= 101.0  # margen por redondeos

    def test_results_sorted_descending_by_percentage(self):
        result = get_delay_causes_breakdown.invoke({})
        data = json.loads(result)
        pcts = [row["pct"] for row in data]
        assert pcts == sorted(pcts, reverse=True)


class TestPredictFlightDelay:
    """Tests de predict_flight_delay."""

    def test_returns_error_structure_for_nonexistent_combination(self):
        # Combinación inventada que no debería existir en el dataset real.
        result = predict_flight_delay.invoke({
            "airline": "ZZ",
            "origin": "Ciudad Inexistente, XX",
            "destination": "Otra Ciudad Inexistente, YY",
            "month": 1,
            "scheduled_dep": 130,
        })
        data = json.loads(result)
        assert data["sample_size"] == 0
        assert data["main_cause"] == "unknown"
        assert "error" in data

    def test_returns_expected_fields_structure(self):
        # Probamos con parámetros genéricos; no garantizamos que existan
        # datos, pero la estructura de la respuesta debe ser siempre la misma.
        result = predict_flight_delay.invoke({
            "airline": "AA",
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "month": 3,
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        expected_keys = {
            "avg_dep_delay_min", "avg_arr_delay_min",
            "pct_disrupted", "sample_size", "main_cause",
        }
        assert expected_keys.issubset(data.keys())

    def test_main_cause_is_one_of_expected_values(self):
        result = predict_flight_delay.invoke({
            "airline": "AA",
            "origin": "Chicago, IL",
            "destination": "Denver, CO",
            "month": 3,
            "scheduled_dep": 1400,
        })
        data = json.loads(result)
        assert data["main_cause"] in {
            "carrier", "weather", "nas", "security", "late_aircraft", "unknown"
        }