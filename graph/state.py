"""
graph/state.py
==============
Define el estado compartido del grafo LangGraph de SGIDA.

El estado es el único canal de comunicación entre nodos. Cada agente
lee lo que necesita y escribe sus resultados en los campos que le
corresponden. LangGraph gestiona la inmutabilidad entre pasos.

Esquema de la tabla `flights` (analytical_db.duckdb):
------------------------------------------------------
Year, Month, DayofMonth         BIGINT
FlightDate                      VARCHAR
Marketing_Airline_Network       VARCHAR   (código de aerolínea)
OriginCityName, DestCityName    VARCHAR
CRSDepTime, CRSArrTime          BIGINT    (hora programada HHMM)
DepTime, ArrTime                DOUBLE    (hora real HHMM)
DepDelay, DepDelayMinutes       DOUBLE    (minutos de retraso en salida)
ArrDelay, ArrDelayMinutes       DOUBLE    (minutos de retraso en llegada)
TaxiOut, TaxiIn                 DOUBLE    (minutos en pista)
WheelsOff, WheelsOn             DOUBLE    (hora de despegue/aterrizaje)
CRSElapsedTime, ActualElapsedTime, AirTime  DOUBLE
Distance, DistanceGroup         DOUBLE / BIGINT
CarrierDelay, WeatherDelay      DOUBLE    (minutos por causa)
NASDelay, SecurityDelay         DOUBLE
LateAircraftDelay               DOUBLE
"""

from __future__ import annotations

from typing import Annotated, Optional
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


# ---------------------------------------------------------------------------
# Tipos auxiliares (reflejan el dominio del dataset BTS)
# ---------------------------------------------------------------------------

class FlightContext(TypedDict, total=False):
    """
    Contexto de un vuelo concreto sobre el que se ha lanzado una consulta.
    Los campos son opcionales porque el usuario puede proporcionar solo
    algunos (p.ej. solo aerolínea y ruta sin fecha concreta).
    """
    airline: str               # Marketing_Airline_Network  (ej. "AA")
    origin: str                # OriginCityName             (ej. "New York, NY")
    destination: str           # DestCityName               (ej. "Los Angeles, CA")
    flight_date: str           # FlightDate                 (ej. "2018-01-15")
    year: int                  # Year
    month: int                 # Month  (1-12)
    day: int                   # DayofMonth
    scheduled_dep: int         # CRSDepTime  (HHMM, ej. 830 → 08:30)
    scheduled_arr: int         # CRSArrTime  (HHMM)
    distance: float            # Distance (millas)


class DelayPrediction(TypedDict):
    """Resultado del análisis predictivo sobre un vuelo."""
    expected_dep_delay_min: float      # Retraso estimado en salida (minutos)
    expected_arr_delay_min: float      # Retraso estimado en llegada (minutos)
    is_disruption: bool                # Supera el umbral de disrupción
    confidence: float                  # Confianza del modelo (0.0–1.0)
    main_cause: str                    # Causa principal estimada
    #   Valores posibles de main_cause:
    #   "carrier" | "weather" | "nas" | "security" | "late_aircraft" | "unknown"


class DisruptionProposal(TypedDict):
    """Propuesta de actuación generada por el agente de disrupciones."""
    proposal_id: str                   # Identificador único de la propuesta
    severity: str                      # "low" | "medium" | "high" | "critical"
    actions: list[str]                 # Lista de acciones concretas propuestas
    affected_passengers_est: int       # Pasajeros afectados estimados
    alternative_flights: list[str]     # Vuelos alternativos sugeridos
    reasoning: str                     # Razonamiento del agente


class RouteStat(TypedDict):
    """Estadística de retraso para una ruta origen-destino."""
    origin: str
    destination: str
    avg_arr_delay_min: float
    total_flights: int


class AirportStat(TypedDict):
    """Estadística de retraso para un aeropuerto de origen."""
    origin: str
    avg_dep_delay_min: float
    total_flights: int
    pct_delayed: float


class AirlineStat(TypedDict):
    """Estadística de retraso para una aerolínea."""
    airline: str
    avg_arr_delay_min: float
    total_flights: int
    pct_delayed: float


class HourStat(TypedDict):
    """Estadística de retraso para una franja horaria de salida (0-23)."""
    hour: int
    avg_dep_delay_min: float
    total_flights: int


class MonthStat(TypedDict):
    """Estadística de retraso para un mes (1-12)."""
    month: int
    avg_arr_delay_min: float
    total_flights: int


class CauseStat(TypedDict):
    """Desglose del porcentaje de minutos de retraso por causa."""
    cause: str              # "carrier" | "weather" | "nas" | "security" | "late_aircraft"
    total_minutes: float
    pct: float


class FlightHistoricalStats(TypedDict):
    """
    Estadísticas históricas agregadas para un vuelo concreto
    (aerolínea + ruta + mes + franja horaria). Puramente factual:
    `dominant_delay_cause` es la causa que más minutos de retraso ha
    acumulado históricamente en esa combinación, no una predicción.
    """
    airline: str
    origin: str
    destination: str
    month: int
    scheduled_dep: int
    avg_dep_delay_min: Optional[float]
    avg_arr_delay_min: Optional[float]
    pct_over_threshold: Optional[float]
    sample_size: int
    dominant_delay_cause: str


class CascadeRiskFlight(TypedDict):
    """Vuelo con exposición histórica a retraso de aeronave tardía."""
    destination: str
    airline: str
    scheduled_dep: int
    avg_late_aircraft_delay_min: float
    total_flights: int


class AnalyticsResult(TypedDict, total=False):
    """
    Resultados de consultas analíticas sobre el dataset histórico.
    Todos los campos son opcionales: cada consulta rellena solo los
    que corresponden a las herramientas invocadas por el agente analítico.
    """
    top_delay_routes: list[RouteStat]
    top_delay_airports: list[AirportStat]
    top_delay_airlines: list[AirlineStat]
    delay_by_hour: list[HourStat]
    delay_by_month: list[MonthStat]
    delay_causes_breakdown: list[CauseStat]
    flight_historical_stats: FlightHistoricalStats
    cascade_risk_context: list[CascadeRiskFlight]
    tools_used: list[str]


# ---------------------------------------------------------------------------
# Estado principal del grafo
# ---------------------------------------------------------------------------

class SGIDAState(TypedDict):
    """
    Estado compartido entre todos los nodos del grafo LangGraph.

    Convenciones de escritura:
    - Solo el supervisor escribe en `next_agent` y `iteration`.
    - Solo el agente analítico escribe en `analytics_result` y `delay_prediction`.
    - Solo el agente de disrupciones escribe en `disruption_proposal`.
    - Solo el agente de comunicación escribe en `final_response`.
    - Cualquier agente puede escribir en `error`.

    El campo `messages` usa el reducer `add_messages` de LangGraph,
    que acumula mensajes en lugar de sobreescribirlos.
    """

    # --- Canal de mensajes (historial conversacional) --------------------
    messages: Annotated[list[BaseMessage], add_messages]

    # --- Entrada del usuario --------------------------------------------
    user_query: str
    # Texto literal de la consulta del operador.

    flight_context: Optional[FlightContext]
    # Vuelo concreto extraído de la consulta (None si la consulta es general).

    # --- Control de flujo (gestionado por el supervisor) ----------------
    next_agent: str
    # Nombre del próximo nodo al que debe saltar el supervisor.
    # Valores: "analytical_agent" | "disruption_agent" |
    #          "communication_agent" | "END"

    iteration: int
    # Contador de pasos del grafo. El supervisor lo incrementa en cada ciclo
    # y fuerza END si supera Settings.GRAPH_MAX_ITERATIONS.

    # --- Resultados por agente ------------------------------------------
    analytics_result: Optional[AnalyticsResult]
    # Rellenado por analytical_agent tras consultas al dataset histórico.

    delay_prediction: Optional[DelayPrediction]
    # Rellenado por analytical_agent de forma determinista (umbral de
    # disrupción + heurística de confianza según tamaño de muestra) a
    # partir de `flight_historical_stats`, no por interpretación del LLM.

    disruption_proposal: Optional[DisruptionProposal]
    # Rellenado por disruption_agent con las acciones propuestas.

    final_response: Optional[str]
    # Rellenado por communication_agent con el texto listo para el operador.

    # --- Control de errores ---------------------------------------------
    error: Optional[str]
    # Si algún agente captura una excepción, escribe aquí el mensaje.
    # El supervisor lo detecta y redirige al agente de comunicación
    # para informar al operador de forma amigable.


# ---------------------------------------------------------------------------
# Estado inicial (factory function)
# ---------------------------------------------------------------------------

def initial_state(user_query: str) -> SGIDAState:
    """
    Construye el estado inicial para una nueva consulta del operador.

    Parameters
    ----------
    user_query : str
        Texto de la consulta tal como la escribe el operador.

    Returns
    -------
    SGIDAState
        Estado limpio listo para ser inyectado en el grafo.
    """
    return SGIDAState(
        messages=[],
        user_query=user_query,
        flight_context=None,
        next_agent="supervisor",
        iteration=0,
        analytics_result=None,
        delay_prediction=None,
        disruption_proposal=None,
        final_response=None,
        error=None,
    )