"""
backend/app/services/routes_service.py
==========================================
Catálogo de rutas (aeropuertos de origen y destinos alcanzables desde cada
uno) presente en `flights`, para poblar el explorador de rutas del
frontend (evolutivo explorador-rutas-aeropuertos).

No es una tool del agente: es un dato de referencia estático para la UI,
igual que history_service.py alimenta el panel de estado. Los datos no
cambian entre ingestas (ver data/data_ingestion.py), así que el resultado
se cachea en memoria de proceso tras el primer cálculo.
"""

from __future__ import annotations

import duckdb

from config.settings import Settings

_cache: dict[str, object] | None = None


def get_routes() -> dict[str, object]:
    """Devuelve {"origins": [...], "routes": {origen: [destinos]}}, cacheado."""
    global _cache
    if _cache is None:
        _cache = _load_routes()
    return _cache


def _load_routes() -> dict[str, object]:
    with duckdb.connect(Settings.DB_PATH, read_only=True) as con:
        rows = con.execute(
            """
            SELECT DISTINCT OriginCityName AS origin, DestCityName AS destination
            FROM flights
            WHERE OriginCityName IS NOT NULL AND DestCityName IS NOT NULL
            """
        ).fetchall()

    routes: dict[str, set[str]] = {}
    for origin, destination in rows:
        routes.setdefault(origin, set()).add(destination)

    sorted_routes = {origin: sorted(destinations) for origin, destinations in routes.items()}
    origins = sorted(sorted_routes.keys())

    return {"origins": origins, "routes": sorted_routes}
