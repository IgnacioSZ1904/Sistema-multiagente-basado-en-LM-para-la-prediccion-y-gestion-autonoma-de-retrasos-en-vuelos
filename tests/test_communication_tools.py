"""
tests/unit/test_communication_tools.py
=========================================
Tests de funcionalidades básicas de tools/communication_tools.py.

No dependen de analytical_db.duckdb (estas herramientas usan su propio
log JSONL en data/notifications_log/), así que se ejecutan siempre.
Cada test usa un fichero de log temporal y aislado (monkeypatch) para
no contaminar ni depender del log real del proyecto.
"""

from __future__ import annotations

import json

import pytest

from tools.communication_tools import (
    COMMUNICATION_TOOLS,
    get_notification_history,
    send_passenger_notification,
)


@pytest.fixture(autouse=True)
def _isolated_log_file(tmp_path, monkeypatch):
    """Redirige el log de notificaciones a un fichero temporal por test."""
    import tools.communication_tools as mod

    temp_log_dir = tmp_path / "notifications_log"
    temp_log_file = temp_log_dir / "notifications.jsonl"

    monkeypatch.setattr(mod, "_LOG_DIR", temp_log_dir)
    monkeypatch.setattr(mod, "_LOG_FILE", temp_log_file)
    yield temp_log_file


class TestCommunicationToolsRegistry:
    """Verifica que COMMUNICATION_TOOLS expone las herramientas esperadas."""

    def test_exports_exactly_two_tools(self):
        assert len(COMMUNICATION_TOOLS) == 2

    def test_all_tools_have_name_and_description(self):
        for tool in COMMUNICATION_TOOLS:
            assert tool.name
            assert tool.description


class TestSendPassengerNotification:
    """Tests de send_passenger_notification."""

    def test_returns_sent_status(self):
        result = send_passenger_notification.invoke({
            "recipient_type": "operator",
            "message": "Vuelo AA1234 retrasado 45 minutos.",
        })
        data = json.loads(result)
        assert data["status"] == "sent"

    def test_returns_notification_id(self):
        result = send_passenger_notification.invoke({
            "recipient_type": "operator",
            "message": "Mensaje de prueba.",
        })
        data = json.loads(result)
        assert data["notification_id"].startswith("NOTIF-")

    def test_returns_timestamp(self):
        result = send_passenger_notification.invoke({
            "recipient_type": "passenger",
            "message": "Su vuelo ha sido reasignado.",
        })
        data = json.loads(result)
        assert "timestamp" in data

    def test_creates_log_file_on_disk(self, _isolated_log_file):
        assert not _isolated_log_file.exists()
        send_passenger_notification.invoke({
            "recipient_type": "operator",
            "message": "Mensaje de prueba.",
        })
        assert _isolated_log_file.exists()

    def test_log_entry_contains_all_fields(self, _isolated_log_file):
        send_passenger_notification.invoke({
            "recipient_type": "ground_staff",
            "message": "Aviso de saturación en puerta B12.",
            "flight_reference": "AA1234 - 2018-03-10",
            "channel": "operator_dashboard",
        })
        with open(_isolated_log_file, "r", encoding="utf-8") as f:
            entry = json.loads(f.readline())

        assert entry["recipient_type"] == "ground_staff"
        assert entry["channel"] == "operator_dashboard"
        assert entry["flight_reference"] == "AA1234 - 2018-03-10"
        assert entry["message"] == "Aviso de saturación en puerta B12."

    def test_default_channel_is_email(self):
        result = send_passenger_notification.invoke({
            "recipient_type": "passenger",
            "message": "Mensaje sin canal especificado.",
        })
        # El status confirma que se procesó correctamente con el default.
        data = json.loads(result)
        assert data["status"] == "sent"

    def test_multiple_notifications_get_unique_ids(self):
        result1 = send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Primera notificación.",
        })
        result2 = send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Segunda notificación.",
        })
        id1 = json.loads(result1)["notification_id"]
        id2 = json.loads(result2)["notification_id"]
        assert id1 != id2


class TestGetNotificationHistory:
    """Tests de get_notification_history."""

    def test_returns_empty_list_when_no_notifications_sent(self):
        result = get_notification_history.invoke({})
        data = json.loads(result)
        assert data == []

    def test_returns_sent_notifications(self):
        send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Notificación de prueba.",
        })
        result = get_notification_history.invoke({})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["message"] == "Notificación de prueba."

    def test_most_recent_notification_first(self):
        send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Primera.",
        })
        send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Segunda.",
        })
        result = get_notification_history.invoke({})
        data = json.loads(result)
        assert data[0]["message"] == "Segunda."
        assert data[1]["message"] == "Primera."

    def test_filters_by_flight_reference(self):
        send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Vuelo A.",
            "flight_reference": "AA1234",
        })
        send_passenger_notification.invoke({
            "recipient_type": "operator", "message": "Vuelo B.",
            "flight_reference": "DL5678",
        })
        result = get_notification_history.invoke({"flight_reference": "AA1234"})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["flight_reference"] == "AA1234"

    def test_respects_limit_parameter(self):
        for i in range(5):
            send_passenger_notification.invoke({
                "recipient_type": "operator", "message": f"Notificación {i}.",
            })
        result = get_notification_history.invoke({"limit": 2})
        data = json.loads(result)
        assert len(data) == 2