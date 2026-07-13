"""
tests/unit/test_logging_config.py
====================================
Tests de config/logging_config.py: nombre jerárquico del logger, nivel
por defecto/configurable vía LOG_LEVEL, e idempotencia de
configure_logging() (no debe duplicar handlers).
"""

from __future__ import annotations

import logging

import pytest

import config.logging_config as logging_config


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Aísla cada test: resetea el logger raíz 'sgida' y el flag interno
    de configuración, restaurando el estado original al finalizar."""
    root_logger = logging.getLogger("sgida")
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_configured = logging_config._configured

    root_logger.handlers = []
    logging_config._configured = False

    yield

    root_logger.handlers = original_handlers
    root_logger.setLevel(original_level)
    logging_config._configured = original_configured


class TestGetLogger:
    def test_returns_logger_with_hierarchical_name(self):
        logger = logging_config.get_logger("my_module")
        assert logger.name == "sgida.my_module"

    def test_default_level_is_info_without_log_level_env(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        logging_config.get_logger("x")
        assert logging.getLogger("sgida").level == logging.INFO

    def test_respects_log_level_env_variable(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        logging_config.get_logger("x")
        assert logging.getLogger("sgida").level == logging.DEBUG


def _own_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """Filtra los handlers propios de logging_config, ignorando los que
    pytest pueda adjuntar al mismo logger para su propia captura de logs."""
    return [
        h for h in logger.handlers
        if getattr(h.formatter, "_fmt", None) == logging_config._LOG_FORMAT
    ]


class TestConfigureLoggingIdempotent:
    def test_does_not_duplicate_handlers_on_repeated_calls(self):
        logging_config.configure_logging()
        logging_config.configure_logging()
        logging_config.configure_logging()

        assert len(_own_handlers(logging.getLogger("sgida"))) == 1

    def test_get_logger_does_not_duplicate_handlers_either(self):
        logging_config.get_logger("a")
        logging_config.get_logger("b")
        logging_config.get_logger("c")

        assert len(_own_handlers(logging.getLogger("sgida"))) == 1
