"""
tools/communication_tools.py
=============================
Herramientas LangChain del agente de comunicación.

El agente de comunicación redacta los textos (informes, notificaciones)
directamente con el LLM a partir de su prompt — no requiere una @tool
para "escribir", solo para su propia razón de ser como agente.

Lo que SÍ necesita como herramienta es el envío/registro de la
notificación una vez redactada. En este TFG no se integra con un
proveedor real de email/SMS (fuera de alcance), así que el envío se
SIMULA mediante un log estructurado a fichero, dejando trazabilidad
de qué se habría comunicado, a quién y cuándo.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Configuración del log de notificaciones simuladas
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "notifications_log"
_LOG_FILE = _LOG_DIR / "notifications.jsonl"


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

@tool
def send_passenger_notification(
    recipient_type: str,
    message: str,
    flight_reference: str = "",
    channel: str = "email",
) -> str:
    """
    Simula el envío de una notificación a pasajeros o personal operativo.

    No realiza un envío real (fuera del alcance del TFG, requeriría
    integración con un proveedor de email/SMS). En su lugar, registra
    la notificación en un log estructurado para trazabilidad y para
    poder mostrarla en el panel de visualización del sistema.

    Args:
        recipient_type:    Tipo de destinatario: "passenger" | "operator"
                            | "ground_staff".
        message:            Texto completo de la notificación, ya redactado
                            por el agente en lenguaje natural.
        flight_reference:   Identificador del vuelo al que se refiere
                            (ej. "AA1234 - 2018-03-10"). Opcional.
        channel:            Canal simulado: "email" | "sms" | "push" |
                            "operator_dashboard". Por defecto "email".

    Returns:
        JSON con: status ("sent"), notification_id, timestamp.
    """
    _ensure_log_dir()

    timestamp = datetime.now().isoformat(timespec="seconds")
    notification_id = f"NOTIF-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    entry = {
        "notification_id": notification_id,
        "timestamp": timestamp,
        "recipient_type": recipient_type,
        "channel": channel,
        "flight_reference": flight_reference,
        "message": message,
    }

    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return json.dumps({
        "status": "sent",
        "notification_id": notification_id,
        "timestamp": timestamp,
    }, ensure_ascii=False)


@tool
def get_notification_history(flight_reference: str = "", limit: int = 20) -> str:
    """
    Recupera el historial de notificaciones simuladas enviadas.

    Útil para que el agente (o el panel de visualización) consulte qué
    comunicaciones se han generado previamente, por ejemplo para evitar
    notificar dos veces la misma disrupción.

    Args:
        flight_reference:  Si se indica, filtra solo notificaciones de
                            ese vuelo. Si se deja vacío, devuelve las
                            más recientes de cualquier vuelo.
        limit:              Número máximo de notificaciones a devolver
                            (por defecto 20).

    Returns:
        JSON con lista de notificaciones (las más recientes primero).
    """
    _ensure_log_dir()

    if not _LOG_FILE.exists():
        return json.dumps([], ensure_ascii=False)

    with open(_LOG_FILE, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    if flight_reference:
        lines = [e for e in lines if e.get("flight_reference") == flight_reference]

    lines.reverse()  # más recientes primero
    return json.dumps(lines[:limit], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Lista exportada para registrar en el agente
# ---------------------------------------------------------------------------

COMMUNICATION_TOOLS = [
    send_passenger_notification,
    get_notification_history,
]