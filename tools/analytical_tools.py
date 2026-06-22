"""
tools/analytical_tools.py
=========================
Herramientas LangChain del agente analítico.

Cada función está decorada con @tool para que LangChain pueda
invocarla de forma autónoma. Todas ejecutan SQL sobre la tabla
`flights` de analytical_db.duckdb y devuelven JSON serializable.

Columnas disponibles en `flights`:
  Year, Month, DayofMonth, FlightDate
  Marketing_Airline_Network, OriginCityName, DestCityName
  CRSDepTime, DepTime, DepDelay, DepDelayMinutes
  CRSArrTime, ArrTime, ArrDelay, ArrDelayMinutes
  TaxiOut, TaxiIn, WheelsOff, WheelsOn
  CRSElapsedTime, ActualElapsedTime, AirTime
  Distance, DistanceGroup
  CarrierDelay, WeatherDelay, NASDelay, SecurityDelay, LateAircraftDelay
"""

from __future__ import annotations

import json
from typing import Optional

import duckdb
from langchain_core.tools import tool

from config.settings import Settings


# ---------------------------------------------------------------------------
# Utilidad interna
# ---------------------------------------------------------------------------

def _query(sql: str) -> list[dict]:
    """Ejecuta SQL y devuelve lista de dicts. Conexión de solo lectura."""
    with duckdb.connect(Settings.DB_PATH, read_only=True) as con:
        rel = con.execute(sql)
        # rel.description can be None for statements that return no columns
        if rel.description is None:
            return []
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, row)) for row in rel.fetchall()]


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

@tool
def get_top_delay_airports(limit: int = 10) -> str:
    """
    Devuelve los aeropuertos de origen con mayor retraso medio en salida.

    Args:
        limit: Número de aeropuertos a devolver (por defecto 10).

    Returns:
        JSON con campos: origin, avg_dep_delay_min, total_flights, pct_delayed.
    """
    sql = f"""
        SELECT
            OriginCityName                                  AS origin,
            ROUND(AVG(DepDelayMinutes), 2)                  AS avg_dep_delay_min,
            COUNT(*)                                         AS total_flights,
            ROUND(
                100.0 * SUM(CASE WHEN DepDelayMinutes > {Settings.DELAY_THRESHOLD_MINUTES}
                                 THEN 1 ELSE 0 END) / COUNT(*), 2
            )                                               AS pct_delayed
        FROM flights
        WHERE DepDelayMinutes IS NOT NULL
        GROUP BY OriginCityName
        ORDER BY avg_dep_delay_min DESC
        LIMIT {limit}
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def get_top_delay_airlines(limit: int = 10) -> str:
    """
    Devuelve las aerolíneas con mayor retraso medio en llegada.

    Args:
        limit: Número de aerolíneas a devolver (por defecto 10).

    Returns:
        JSON con campos: airline, avg_arr_delay_min, total_flights, pct_delayed.
    """
    sql = f"""
        SELECT
            Marketing_Airline_Network                       AS airline,
            ROUND(AVG(ArrDelayMinutes), 2)                  AS avg_arr_delay_min,
            COUNT(*)                                         AS total_flights,
            ROUND(
                100.0 * SUM(CASE WHEN ArrDelayMinutes > {Settings.DELAY_THRESHOLD_MINUTES}
                                 THEN 1 ELSE 0 END) / COUNT(*), 2
            )                                               AS pct_delayed
        FROM flights
        WHERE ArrDelayMinutes IS NOT NULL
        GROUP BY Marketing_Airline_Network
        ORDER BY avg_arr_delay_min DESC
        LIMIT {limit}
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def get_top_delay_routes(limit: int = 10) -> str:
    """
    Devuelve las rutas origen-destino con mayor retraso medio en llegada.

    Args:
        limit: Número de rutas a devolver (por defecto 10).

    Returns:
        JSON con campos: origin, destination, avg_arr_delay_min, total_flights.
    """
    sql = f"""
        SELECT
            OriginCityName                                  AS origin,
            DestCityName                                    AS destination,
            ROUND(AVG(ArrDelayMinutes), 2)                  AS avg_arr_delay_min,
            COUNT(*)                                         AS total_flights
        FROM flights
        WHERE ArrDelayMinutes IS NOT NULL
        GROUP BY OriginCityName, DestCityName
        HAVING COUNT(*) > 100
        ORDER BY avg_arr_delay_min DESC
        LIMIT {limit}
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def get_delay_by_month() -> str:
    """
    Devuelve el retraso medio en llegada agrupado por mes (1-12).

    Returns:
        JSON con campos: month, avg_arr_delay_min, total_flights.
    """
    sql = """
        SELECT
            Month                                           AS month,
            ROUND(AVG(ArrDelayMinutes), 2)                  AS avg_arr_delay_min,
            COUNT(*)                                         AS total_flights
        FROM flights
        WHERE ArrDelayMinutes IS NOT NULL
        GROUP BY Month
        ORDER BY Month
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def get_delay_by_hour() -> str:
    """
    Devuelve el retraso medio en salida agrupado por franja horaria (0-23).

    La hora se extrae de CRSDepTime (formato HHMM, ej. 830 → hora 8).

    Returns:
        JSON con campos: hour, avg_dep_delay_min, total_flights.
    """
    sql = """
        SELECT
            CAST(CRSDepTime / 100 AS INTEGER)               AS hour,
            ROUND(AVG(DepDelayMinutes), 2)                  AS avg_dep_delay_min,
            COUNT(*)                                         AS total_flights
        FROM flights
        WHERE DepDelayMinutes IS NOT NULL
          AND CRSDepTime IS NOT NULL
          AND CRSDepTime BETWEEN 0 AND 2359
        GROUP BY hour
        ORDER BY hour
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def get_delay_causes_breakdown() -> str:
    """
    Devuelve el porcentaje de minutos de retraso atribuido a cada causa.

    Causas: carrier, weather, nas (National Airspace System),
            security, late_aircraft.

    Returns:
        JSON con campos: cause, total_minutes, pct.
    """
    sql = """
        WITH totals AS (
            SELECT
                SUM(CarrierDelay)       AS carrier,
                SUM(WeatherDelay)       AS weather,
                SUM(NASDelay)           AS nas,
                SUM(SecurityDelay)      AS security,
                SUM(LateAircraftDelay)  AS late_aircraft
            FROM flights
        ),
        grand AS (
            SELECT (carrier + weather + nas + security + late_aircraft) AS total
            FROM totals
        )
        SELECT
            'carrier'       AS cause, ROUND(carrier, 0)       AS total_minutes,
            ROUND(100.0 * carrier / total, 2)                 AS pct
        FROM totals, grand
        UNION ALL
        SELECT 'weather', ROUND(weather, 0), ROUND(100.0 * weather / total, 2)
        FROM totals, grand
        UNION ALL
        SELECT 'nas', ROUND(nas, 0), ROUND(100.0 * nas / total, 2)
        FROM totals, grand
        UNION ALL
        SELECT 'security', ROUND(security, 0), ROUND(100.0 * security / total, 2)
        FROM totals, grand
        UNION ALL
        SELECT 'late_aircraft', ROUND(late_aircraft, 0), ROUND(100.0 * late_aircraft / total, 2)
        FROM totals, grand
        ORDER BY pct DESC
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def predict_flight_delay(
    airline: str,
    origin: str,
    destination: str,
    month: int,
    scheduled_dep: int,
) -> str:
    """
    Estima el retraso esperado para un vuelo dado basándose en históricos.

    Calcula el retraso medio y la tasa de disrupción para vuelos con las
    mismas características (aerolínea, ruta, mes y franja horaria similar).

    Args:
        airline:       Código de aerolínea (Marketing_Airline_Network, ej. "AA").
        origin:        Ciudad de origen (ej. "New York, NY").
        destination:   Ciudad de destino (ej. "Los Angeles, CA").
        month:         Mes del vuelo (1-12).
        scheduled_dep: Hora de salida programada en formato HHMM (ej. 830).

    Returns:
        JSON con campos: avg_dep_delay_min, avg_arr_delay_min, pct_disrupted,
        sample_size, main_cause.
    """
    dep_hour = scheduled_dep // 100
    sql = f"""
        WITH base AS (
            SELECT
                DepDelayMinutes,
                ArrDelayMinutes,
                CarrierDelay,
                WeatherDelay,
                NASDelay,
                SecurityDelay,
                LateAircraftDelay
            FROM flights
            WHERE Marketing_Airline_Network = '{airline}'
              AND OriginCityName            = '{origin}'
              AND DestCityName              = '{destination}'
              AND Month                     = {month}
              AND CAST(CRSDepTime / 100 AS INTEGER) = {dep_hour}
              AND DepDelayMinutes IS NOT NULL
              AND ArrDelayMinutes IS NOT NULL
        ),
        causes AS (
            SELECT
                AVG(CarrierDelay)       AS carrier,
                AVG(WeatherDelay)       AS weather,
                AVG(NASDelay)           AS nas,
                AVG(SecurityDelay)      AS security,
                AVG(LateAircraftDelay)  AS late_aircraft
            FROM base
        )
        SELECT
            ROUND(AVG(b.DepDelayMinutes), 2)    AS avg_dep_delay_min,
            ROUND(AVG(b.ArrDelayMinutes), 2)    AS avg_arr_delay_min,
            ROUND(
                100.0 * SUM(CASE WHEN b.ArrDelayMinutes > {Settings.DELAY_THRESHOLD_MINUTES}
                                 THEN 1 ELSE 0 END) / COUNT(*), 2
            )                                   AS pct_disrupted,
            COUNT(*)                            AS sample_size,
            (SELECT
                CASE
                    WHEN carrier >= weather AND carrier >= nas
                         AND carrier >= security AND carrier >= late_aircraft
                         THEN 'carrier'
                    WHEN weather >= carrier AND weather >= nas
                         AND weather >= security AND weather >= late_aircraft
                         THEN 'weather'
                    WHEN nas >= carrier AND nas >= weather
                         AND nas >= security AND nas >= late_aircraft
                         THEN 'nas'
                    WHEN late_aircraft >= carrier AND late_aircraft >= weather
                         AND late_aircraft >= nas AND late_aircraft >= security
                         THEN 'late_aircraft'
                    ELSE 'security'
                END
             FROM causes)                       AS main_cause
        FROM base b
    """
    rows = _query(sql)
    if not rows or rows[0]["sample_size"] == 0:
        return json.dumps({
            "error": "Sin datos históricos suficientes para esta combinación.",
            "avg_dep_delay_min": None,
            "avg_arr_delay_min": None,
            "pct_disrupted": None,
            "sample_size": 0,
            "main_cause": "unknown",
        }, ensure_ascii=False)
    return json.dumps(rows[0], ensure_ascii=False)


@tool
def get_cascade_risk_flights(
    origin: str,
    flight_date: str,
    dep_hour: int,
    delay_minutes: float,
) -> str:
    """
    Identifica vuelos con riesgo de efecto cascada dado un retraso inicial.

    Busca vuelos que salgan del mismo aeropuerto en las 2 horas siguientes
    al retraso, operados por la misma aerolínea, que históricamente se ven
    afectados por retrasos de aeronave tardía (LateAircraftDelay).

    Args:
        origin:        Ciudad del aeropuerto afectado (ej. "Chicago, IL").
        flight_date:   Fecha en formato YYYY-MM-DD (ej. "2018-03-10").
        dep_hour:      Hora de salida del vuelo retrasado (0-23).
        delay_minutes: Minutos de retraso del vuelo inicial.

    Returns:
        JSON con lista de vuelos en riesgo: destination, airline,
        scheduled_dep, avg_late_aircraft_delay_min, total_flights.
    """
    # Extraemos mes para filtrar histórico similar
    try:
        month = int(flight_date.split("-")[1])
    except (IndexError, ValueError):
        month = 1

    window_start = dep_hour
    window_end = min(dep_hour + 2, 23)

    sql = f"""
        SELECT
            DestCityName                                AS destination,
            Marketing_Airline_Network                   AS airline,
            CRSDepTime                                  AS scheduled_dep,
            ROUND(AVG(LateAircraftDelay), 2)            AS avg_late_aircraft_delay_min,
            COUNT(*)                                     AS total_flights
        FROM flights
        WHERE OriginCityName = '{origin}'
          AND Month          = {month}
          AND CAST(CRSDepTime / 100 AS INTEGER) BETWEEN {window_start} AND {window_end}
          AND LateAircraftDelay > 0
        GROUP BY DestCityName, Marketing_Airline_Network, CRSDepTime
        HAVING COUNT(*) > 20
        ORDER BY avg_late_aircraft_delay_min DESC
        LIMIT 10
    """
    return json.dumps(_query(sql), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Lista exportada para registrar en el agente
# ---------------------------------------------------------------------------

ANALYTICAL_TOOLS = [
    get_top_delay_airports,
    get_top_delay_airlines,
    get_top_delay_routes,
    get_delay_by_month,
    get_delay_by_hour,
    get_delay_causes_breakdown,
    predict_flight_delay,
    get_cascade_risk_flights,
]