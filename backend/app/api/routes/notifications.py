from __future__ import annotations

import json

from fastapi import APIRouter

from backend.app.schemas import NotificationSendRequest
from tools.communication_tools import send_passenger_notification

router = APIRouter(tags=["notifications"])


@router.post("/notifications/send")
def send_notification(payload: NotificationSendRequest) -> dict:
    """
    Envía (simulado) una notificación previamente redactada como
    borrador por el agente de comunicación. Acción explícita del
    operador desde el frontend — nunca automática.
    """
    result = send_passenger_notification.invoke(payload.model_dump())
    return json.loads(result)
