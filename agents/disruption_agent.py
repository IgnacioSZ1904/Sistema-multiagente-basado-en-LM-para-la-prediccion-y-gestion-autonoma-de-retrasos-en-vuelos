"""
agents/disruption_agent.py
=============================
Agente de Gestión de Disrupciones de SGIDA.

Responsabilidad: una vez que el Agente Analítico ha detectado o
predicho una disrupción, este agente reúne datos sobre alternativas de
reasignación, pasajeros afectados y congestión en tierra, evalúa
varias alternativas concretas según un criterio de optimización
configurable por el operador (minimizar pasajeros afectados o
minimizar coste operativo) y selecciona la mejor. La salida es un JSON
con formato predefinido (`DisruptionProposal`), autocontenido con el
contexto heredado del Agente Analítico, listo para un informe
posterior.

Diseño (decisión documentada en la memoria del TFG):
-------------------------------------------------------------------
Las 3 tools de este agente (`find_alternative_flights`,
`estimate_affected_passengers`, `get_airport_ground_activity`) son
*siempre* relevantes cuando este agente se ejecuta — no depende de que
el LLM decida cuáles llamar. Por eso ya no hay bucle ReAct: se invocan
directamente desde código con los argumentos derivados de
`flight_context`. Igualmente, `severity` (por rangos de minutos ya
conocidos), la selección de la mejor alternativa (puntuación por
criterio) y el proxy de coste operativo son cálculos deterministas, no
juicios del LLM. La única llamada al LLM que queda es para redactar
`actions` y `reasoning` a partir de todos esos datos ya calculados —
la parte que realmente requiere lenguaje natural, no aritmética.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from config.settings import Settings, get_llm
from graph.state import (
    AlternativeCandidate,
    DisruptionProposal,
    DisruptionSourceContext,
    SGIDAState,
)
from prompts.disruption_prompt import DISRUPTION_STRUCTURED_SYSTEM_PROMPT
from tools.disruption_tools import (
    estimate_affected_passengers,
    find_alternative_flights,
    get_airport_ground_activity,
)


# ---------------------------------------------------------------------------
# Esquema de salida estructurada (única llamada LLM: solo redacción)
# ---------------------------------------------------------------------------

class DisruptionNarrative(BaseModel):
    """
    Parte de la propuesta que sí requiere lenguaje natural. El resto de
    `DisruptionProposal` (severity, alternativa elegida, coste) se
    calcula de forma determinista antes de esta llamada.
    """

    actions: list[str] = Field(
        description="Lista de 2 a 5 acciones concretas y accionables propuestas."
    )
    reasoning: str = Field(
        description="Razonamiento breve (2-4 frases) que justifica la "
        "propuesta con los datos ya calculados (severidad, alternativa "
        "elegida, coste estimado, criterio de optimización activo)."
    )


# ---------------------------------------------------------------------------
# Recogida determinista de datos (sin LLM)
# ---------------------------------------------------------------------------

def _gather_disruption_data(flight_context: dict) -> dict:
    """
    Invoca directamente las 3 tools de disrupción con los argumentos
    derivados de `flight_context`, sin que el LLM decida nada. Si falta
    información necesaria para alguna, se omite (devuelve un valor
    vacío) en lugar de inventar datos.
    """
    origin = flight_context.get("origin")
    destination = flight_context.get("destination")
    airline = flight_context.get("airline")
    month = flight_context.get("month")
    scheduled_dep = flight_context.get("scheduled_dep")

    alternative_candidates: list[dict] = []
    passenger_estimate: dict = {}
    ground_activity: dict = {}

    if origin and destination and scheduled_dep is not None:
        try:
            alternative_candidates = json.loads(find_alternative_flights.invoke({
                "origin": origin,
                "destination": destination,
                "scheduled_dep": scheduled_dep,
                "exclude_airline": airline or "",
            }))
        except Exception:  # noqa: BLE001
            alternative_candidates = []

    if airline and origin and destination and month is not None:
        try:
            passenger_estimate = json.loads(estimate_affected_passengers.invoke({
                "airline": airline,
                "origin": origin,
                "destination": destination,
                "month": month,
            }))
        except Exception:  # noqa: BLE001
            passenger_estimate = {}

    if origin and scheduled_dep is not None:
        try:
            ground_activity = json.loads(get_airport_ground_activity.invoke({
                "origin": origin,
                "scheduled_dep": scheduled_dep,
            }))
        except Exception:  # noqa: BLE001
            ground_activity = {}

    return {
        "alternative_candidates": alternative_candidates,
        "passenger_estimate": passenger_estimate,
        "ground_activity": ground_activity,
    }


# ---------------------------------------------------------------------------
# Cálculos deterministas (sin LLM)
# ---------------------------------------------------------------------------

def _compute_severity(expected_arr_delay_min: float, has_reliable_alternative: bool) -> str:
    """
    Severidad por rangos de minutos de retraso esperado en llegada:
    "low" 15-30, "medium" 30-60, "high" 60-120, "critical" si supera
    120 min o si no hay ninguna alternativa fiable disponible.
    """
    if expected_arr_delay_min > 120 or not has_reliable_alternative:
        return "critical"
    if expected_arr_delay_min >= 60:
        return "high"
    if expected_arr_delay_min >= 30:
        return "medium"
    return "low"


def _score_candidate(candidate: dict, criterion: str) -> float:
    """
    Puntúa un candidato de vuelo alternativo según el criterio activo:
    - "min_passengers": prioriza la mayor fiabilidad histórica
      (`reliability_pct`), para minimizar el riesgo de que los
      pasajeros reasignados sufran un nuevo retraso.
    - "min_cost" (o cualquier otro valor): prioriza el menor retraso
      medio esperado (`avg_arr_delay_min`), como proxy de menor coste
      operativo de la reasignación.
    """
    if criterion == "min_cost":
        avg_delay = candidate.get("avg_arr_delay_min") or 0.0
        return max(0.0, 100.0 - avg_delay)
    return candidate.get("reliability_pct") or 0.0


def _select_best_alternative(
    candidates: list[dict], criterion: str
) -> tuple[Optional[dict], list[AlternativeCandidate]]:
    """
    Puntúa todos los candidatos y elige determinísticamente el de mayor
    puntuación según el criterio activo. Devuelve el elegido (o None si
    no hay candidatos) y la lista completa evaluada, marcando cuál fue
    seleccionado.
    """
    if not candidates:
        return None, []

    scored = sorted(
        ((round(_score_candidate(c, criterion), 2), c) for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best_candidate = scored[0]

    evaluated = [
        AlternativeCandidate(
            airline=candidate.get("airline", "unknown"),
            scheduled_dep=candidate.get("scheduled_dep", 0),
            avg_arr_delay_min=candidate.get("avg_arr_delay_min") or 0.0,
            reliability_pct=candidate.get("reliability_pct") or 0.0,
            score=score,
            selected=(candidate is best_candidate),
        )
        for score, candidate in scored
    ]

    return best_candidate, evaluated


def _estimate_operational_cost(ground_activity: dict, num_alternatives_available: int) -> float:
    """
    Proxy determinista de coste operativo (el dataset no reporta coste
    real): combina la congestión histórica del aeropuerto de origen
    (más congestión → más caro reubicar en tierra) con la escasez de
    alternativas disponibles (menos candidatos → más caro/complejo
    reasignar). Heurística explícita, análoga a `estimated_passenger_load`
    en `tools/disruption_tools.py`.
    """
    avg_taxi_out = ground_activity.get("avg_taxi_out_min") or 0.0
    avg_departures = ground_activity.get("avg_departures_in_hour") or 0.0
    congestion_score = avg_taxi_out + avg_departures
    scarcity_score = 50.0 / (num_alternatives_available + 1)
    return round(congestion_score + scarcity_score, 2)


# ---------------------------------------------------------------------------
# Única llamada LLM: redacción de actions/reasoning
# ---------------------------------------------------------------------------

def _synthesize(
    delay_prediction: Any,
    analytics_result: Any,
    severity: str,
    criterion: str,
    best_candidate: Optional[dict],
    alternatives_considered: list[AlternativeCandidate],
    estimated_cost: float,
    affected_passengers_est: int,
) -> DisruptionNarrative:
    """Única llamada LLM del agente: redacta `actions` y `reasoning` a partir de datos ya calculados."""
    structured_llm = get_llm().with_structured_output(DisruptionNarrative)

    context = {
        "delay_prediction": delay_prediction,
        "analytics_result": analytics_result,
        "severity": severity,
        "optimization_criterion": criterion,
        "best_alternative": best_candidate,
        "alternatives_considered": alternatives_considered,
        "estimated_operational_cost": estimated_cost,
        "affected_passengers_est": affected_passengers_est,
    }

    synthesis_prompt = (
        "Datos ya calculados (JSON), no recalcules nada, solo redacta "
        "las acciones y el razonamiento a partir de ellos:\n\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )

    result = structured_llm.invoke([
        SystemMessage(content=DISRUPTION_STRUCTURED_SYSTEM_PROMPT),
        HumanMessage(content=synthesis_prompt),
    ])

    if isinstance(result, DisruptionNarrative):
        return result

    model_dump_fn = getattr(result, "model_dump", None)
    if callable(model_dump_fn):
        result = model_dump_fn()
    elif not isinstance(result, dict):
        result = dict(result)

    return DisruptionNarrative.model_validate(result)


# ---------------------------------------------------------------------------
# Nodo del grafo
# ---------------------------------------------------------------------------

def disruption_agent(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del agente de gestión de disrupciones.

    Reúne datos deterministamente (sin LLM) sobre alternativas,
    pasajeros afectados y congestión en tierra; calcula severidad,
    selecciona la mejor alternativa según el criterio de optimización
    activo y estima el coste operativo, todo en código; y hace una
    única llamada LLM para redactar `actions`/`reasoning`.

    En caso de error, escribe en `error` en lugar de lanzar excepción.
    """
    delay_prediction = state.get("delay_prediction") or {}
    flight_context = state.get("flight_context") or {}
    analytics_result = state.get("analytics_result")
    criterion = state.get("optimization_criterion") or Settings.DEFAULT_OPTIMIZATION_CRITERION

    source_context = DisruptionSourceContext(
        delay_prediction=delay_prediction,
        cascade_risk_context=(analytics_result or {}).get("cascade_risk_context", []),
        flight_context=flight_context,
    )

    if not Settings.ollama_available() and not state.get("error"):
        return {
            "disruption_proposal": DisruptionProposal(
                proposal_id=f"PROP-{uuid.uuid4().hex[:8]}",
                severity="medium",
                actions=["Revisar manualmente la disrupción en el panel operativo"],
                affected_passengers_est=0,
                alternative_flights=[],
                reasoning="Ollama no está disponible; propuesta mínima generada en modo degradado.",
                optimization_criterion=criterion,
                alternatives_considered=[],
                estimated_operational_cost=None,
                source_context=source_context,
            ),
            "messages": [AIMessage(content="Modo degradado activado para disrupciones.")],
        }

    try:
        gathered = _gather_disruption_data(flight_context)
        candidates = gathered["alternative_candidates"]
        passenger_estimate = gathered["passenger_estimate"]
        ground_activity = gathered["ground_activity"]

        best_candidate, alternatives_considered = _select_best_alternative(candidates, criterion)
        expected_arr_delay_min = delay_prediction.get("expected_arr_delay_min") or 0.0
        severity = _compute_severity(expected_arr_delay_min, has_reliable_alternative=best_candidate is not None)
        affected_passengers_est = int(passenger_estimate.get("estimated_passenger_load") or 0)
        estimated_cost = _estimate_operational_cost(ground_activity, len(candidates))

        narrative = _synthesize(
            delay_prediction=delay_prediction,
            analytics_result=analytics_result,
            severity=severity,
            criterion=criterion,
            best_candidate=best_candidate,
            alternatives_considered=alternatives_considered,
            estimated_cost=estimated_cost,
            affected_passengers_est=affected_passengers_est,
        )

    except Exception as exc:  # noqa: BLE001
        return {"error": f"Error en disruption_agent: {exc}"}

    alternative_flights = (
        [f"{best_candidate['airline']} - {best_candidate['scheduled_dep']}"] if best_candidate else []
    )

    proposal = DisruptionProposal(
        proposal_id=f"PROP-{uuid.uuid4().hex[:8]}",
        severity=severity,
        actions=narrative.actions,
        affected_passengers_est=affected_passengers_est,
        alternative_flights=alternative_flights,
        reasoning=narrative.reasoning,
        optimization_criterion=criterion,
        alternatives_considered=alternatives_considered,
        estimated_operational_cost=estimated_cost,
        source_context=source_context,
    )

    return {
        "disruption_proposal": proposal,
        "messages": [AIMessage(content=narrative.reasoning)],
    }
