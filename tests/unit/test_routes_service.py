"""
tests/unit/test_routes_service.py
====================================
Tests de backend/app/services/routes_service.py contra un fichero DuckDB
temporal y pequeño (no el dataset real de 30M filas), para poder verificar
de forma determinista deduplicación, orden alfabético y cacheo en memoria.
"""

from __future__ import annotations

import duckdb
import pytest

from backend.app.services import routes_service
from config.settings import Settings


@pytest.fixture
def small_flights_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_flights.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE flights (OriginCityName VARCHAR, DestCityName VARCHAR)")
    con.executemany(
        "INSERT INTO flights VALUES (?, ?)",
        [
            ("Chicago, IL", "Denver, CO"),
            ("Chicago, IL", "Atlanta, GA"),
            ("Chicago, IL", "Atlanta, GA"),  # duplicado, debe deduplicarse
            ("Atlanta, GA", "Chicago, IL"),
            ("Denver, CO", None),  # destino nulo: la fila se descarta
        ],
    )
    con.close()

    monkeypatch.setattr(Settings, "DB_PATH", str(db_path))
    routes_service._cache = None
    yield db_path
    routes_service._cache = None


class TestGetRoutes:
    def test_origins_are_deduplicated_and_sorted(self, small_flights_db):
        data = routes_service.get_routes()
        assert data["origins"] == ["Atlanta, GA", "Chicago, IL"]

    def test_destinations_per_origin_are_deduplicated_and_sorted(self, small_flights_db):
        data = routes_service.get_routes()
        assert data["routes"]["Chicago, IL"] == ["Atlanta, GA", "Denver, CO"]
        assert data["routes"]["Atlanta, GA"] == ["Chicago, IL"]

    def test_origin_with_only_null_destination_is_excluded(self, small_flights_db):
        data = routes_service.get_routes()
        assert "Denver, CO" not in data["origins"]
        assert "Denver, CO" not in data["routes"]

    def test_result_is_cached_after_first_call(self, small_flights_db):
        first = routes_service.get_routes()

        # Elimina el fichero para forzar un fallo si se reconsultara la BD.
        small_flights_db.unlink()

        second = routes_service.get_routes()
        assert second == first
