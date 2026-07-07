"""
backend/app/services/history_service.py
==========================================
Historial en memoria de la actividad reciente del sistema, para
alimentar el panel de estado del frontend (vuelos en riesgo, decisiones
de los agentes, métricas de rendimiento global).

Limitación conocida y documentada (TFG): es un historial EN MEMORIA del
proceso del backend, sin persistencia en disco ni base de datos. Se
pierde al reiniciar el backend, igual que otras simulaciones ya
existentes en el proyecto (p. ej. el envío de notificaciones).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_MAX_HISTORY = 50

_history: list[dict[str, Any]] = []


def record_activity(query: str, optimization_criterion: str, state: dict[str, Any]) -> None:
    """
    Registra un resumen de una consulta ya ejecutada. Se llama tras
    cada `run_query()` completado, desde `QueryService.execute`.
    """
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "query": query,
        "optimization_criterion": optimization_criterion,
        "flight_context": state.get("flight_context"),
        "delay_prediction": state.get("delay_prediction"),
        "disruption_proposal": state.get("disruption_proposal"),
        "error": state.get("error"),
    }

    _history.append(entry)
    if len(_history) > _MAX_HISTORY:
        del _history[0]


def get_recent_activity(limit: int = 20) -> list[dict[str, Any]]:
    """Devuelve la actividad más reciente primero, como máximo `limit` entradas."""
    return list(reversed(_history))[:limit]


def get_metrics() -> dict[str, Any]:
    """
    Métricas globales derivadas del historial en memoria:
    nº de consultas procesadas, nº de disrupciones detectadas y
    distribución de severidades entre las propuestas de disrupción.
    """
    total_queries = len(_history)
    total_disruptions = sum(
        1 for entry in _history
        if (entry.get("delay_prediction") or {}).get("is_disruption")
    )

    severity_distribution: dict[str, int] = {}
    for entry in _history:
        proposal = entry.get("disruption_proposal")
        if proposal:
            severity = proposal.get("severity", "unknown")
            severity_distribution[severity] = severity_distribution.get(severity, 0) + 1

    return {
        "total_queries": total_queries,
        "total_disruptions": total_disruptions,
        "severity_distribution": severity_distribution,
    }
