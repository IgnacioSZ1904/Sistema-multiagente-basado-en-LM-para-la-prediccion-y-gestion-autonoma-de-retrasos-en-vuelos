"""
tools/disruption_tools.py
==========================
Herramientas LangChain del agente de gestión de disrupciones.

IMPORTANTE — Limitación del dataset:
El dataset BTS/Kaggle es un histórico de vuelos OPERADOS, no un sistema
de reservas en tiempo real. No contiene capacidad de aeronave, asientos
disponibles ni inventario actual. Por tanto:

  - "Vuelos alternativos" se aproxima buscando vuelos HISTÓRICOS
    comparables (misma ruta, franja horaria cercana, posiblemente otra
    aerolínea) que sirven como candidatos de reasignación.
  - "Recursos en tierra" se aproxima mediante la frecuencia histórica
    de operaciones en el aeropuerto/franja, como proxy de disponibilidad.

Esta es una limitación conocida y documentada del alcance del TFG:
el sistema no ejecuta reasignaciones reales contra un PSS (Passenger
Service System), solo razona sobre datos históricos para PROPONER
acciones. Todas las herramientas de este módulo son de solo lectura.
"""

from __future__ import annotations

import json

import duckdb
from langchain_core.tools import tool

from config.settings import Settings


# ---------------------------------------------------------------------------
# Utilidad interna
# ---------------------------------------------------------------------------

def _query(sql: str) -> list[dict]:
    """Ejecuta SQL de solo lectura y devuelve lista de dicts."""
    with duckdb.connect(Settings.DB_PATH, read_only=True) as con:
        rel = con.execute(sql)
        # rel.description can be None for some DuckDB query results
        # (e.g., when there are no columns). Guard against that to
        # avoid 'NoneType' not iterable errors.
        if not rel.description:
            return []
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, row)) for row in rel.fetchall()]


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

@tool
def find_alternative_flights(
    origin: str,
    destination: str,
    scheduled_dep: int,
    exclude_airline: str = "",
    max_hours_window: int = 4,
) -> str:
    """
    Busca vuelos históricos comparables que sirvan de alternativa de
    reasignación para pasajeros de un vuelo disrumpido.

    Aproximación basada en históricos: identifica combinaciones aerolínea +
    horario que han operado con frecuencia la misma ruta en una ventana
    horaria cercana a la salida original, priorizando las de menor retraso
    medio histórico (mayor fiabilidad).

    Args:
        origin:            Ciudad de origen (ej. "Chicago, IL").
        destination:        Ciudad de destino (ej. "Denver, CO").
        scheduled_dep:      Hora de salida programada del vuelo original (HHMM).
        exclude_airline:    Código de aerolínea a excluir (la del vuelo
                             disrumpido), para no proponerla como alternativa.
        max_hours_window:   Ventana de horas tras la salida original en la
                             que buscar alternativas (por defecto 4).

    Returns:
        JSON con lista de candidatos: airline, scheduled_dep, avg_arr_delay_min,
        reliability_pct (% de vuelos sin disrupción), total_flights.
    """
    dep_hour = scheduled_dep // 100
    window_end = min(dep_hour + max_hours_window, 23)

    exclude_clause = (
        f"AND Marketing_Airline_Network != '{exclude_airline}'"
        if exclude_airline else ""
    )

    sql = f"""
        SELECT
            Marketing_Airline_Network                         AS airline,
            CRSDepTime                                         AS scheduled_dep,
            ROUND(AVG(ArrDelayMinutes), 2)                     AS avg_arr_delay_min,
            ROUND(
                100.0 * SUM(CASE WHEN ArrDelayMinutes <= {Settings.DELAY_THRESHOLD_MINUTES}
                                 THEN 1 ELSE 0 END) / COUNT(*), 2
            )                                                  AS reliability_pct,
            COUNT(*)                                            AS total_flights
        FROM flights
        WHERE OriginCityName = '{origin}'
          AND DestCityName   = '{destination}'
          AND CAST(CRSDepTime / 100 AS INTEGER) BETWEEN {dep_hour} AND {window_end}
          AND ArrDelayMinutes IS NOT NULL
          {exclude_clause}
        GROUP BY Marketing_Airline_Network, CRSDepTime
        HAVING COUNT(*) >= 10
        ORDER BY reliability_pct DESC, avg_arr_delay_min ASC
        LIMIT 8
    """
    return json.dumps(_query(sql), ensure_ascii=False)


@tool
def estimate_affected_passengers(
    airline: str,
    origin: str,
    destination: str,
    month: int,
) -> str:
    """
    Estima el volumen de pasajeros afectados por un vuelo disrumpido.

    El dataset no incluye número de pasajeros por vuelo, así que se usa
    el tamaño de aeronave típico de la ruta (aproximado por AirTime/Distance
    como proxy de tipo de aeronave) y el volumen histórico de operaciones
    en esa combinación como referencia de carga.

    Args:
        airline:      Código de aerolínea (Marketing_Airline_Network).
        origin:        Ciudad de origen.
        destination:   Ciudad de destino.
        month:         Mes (1-12), para capturar estacionalidad de demanda.

    Returns:
        JSON con: total_historical_flights, avg_distance_miles,
        estimated_passenger_load (estimación heurística: 150 pax/vuelo
        como valor por defecto de capacidad media de avión comercial,
        ya que el dataset no reporta capacidad real).
    """
    sql = f"""
        SELECT
            COUNT(*)                          AS total_historical_flights,
            ROUND(AVG(Distance), 0)           AS avg_distance_miles
        FROM flights
        WHERE Marketing_Airline_Network = '{airline}'
          AND OriginCityName            = '{origin}'
          AND DestCityName              = '{destination}'
          AND Month                     = {month}
    """
    rows = _query(sql)
    result = rows[0] if rows else {"total_historical_flights": 0, "avg_distance_miles": None}

    # Heurística documentada: capacidad media de aeronave comercial.
    # El dataset no reporta pasajeros reales; esto es una estimación
    # declarada como tal para el agente y para la memoria del TFG.
    ESTIMATED_AVG_CAPACITY = 150
    result["estimated_passenger_load"] = ESTIMATED_AVG_CAPACITY
    result["estimation_note"] = (
        "Estimación heurística basada en capacidad media de aeronave "
        "comercial; el dataset no reporta pasajeros reales."
    )
    return json.dumps(result, ensure_ascii=False)


@tool
def get_airport_ground_activity(origin: str, scheduled_dep: int) -> str:
    """
    Estima la carga operativa de un aeropuerto en una franja horaria,
    como proxy de presión sobre recursos en tierra (puertas, personal).

    Cuenta el número histórico de salidas en la misma franja horaria,
    como indicador de congestión relativa del aeropuerto en ese momento.

    Args:
        origin:        Ciudad del aeropuerto (ej. "Atlanta, GA").
        scheduled_dep:  Hora de salida programada (HHMM) del vuelo de
                        referencia.

    Returns:
        JSON con: hour, avg_departures_in_hour, avg_taxi_out_min
        (TaxiOut elevado indica congestión en pista, proxy de saturación
        de recursos en tierra).
    """
    dep_hour = scheduled_dep // 100

    sql = f"""
        SELECT
            {dep_hour}                                  AS hour,
            ROUND(COUNT(*) / COUNT(DISTINCT FlightDate), 1) AS avg_departures_in_hour,
            ROUND(AVG(TaxiOut), 2)                       AS avg_taxi_out_min
        FROM flights
        WHERE OriginCityName = '{origin}'
          AND CAST(CRSDepTime / 100 AS INTEGER) = {dep_hour}
          AND TaxiOut IS NOT NULL
    """
    rows = _query(sql)
    result = rows[0] if rows else {
        "hour": dep_hour, "avg_departures_in_hour": None, "avg_taxi_out_min": None
    }
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Lista exportada para registrar en el agente
# ---------------------------------------------------------------------------

DISRUPTION_TOOLS = [
    find_alternative_flights,
    estimate_affected_passengers,
    get_airport_ground_activity,
]