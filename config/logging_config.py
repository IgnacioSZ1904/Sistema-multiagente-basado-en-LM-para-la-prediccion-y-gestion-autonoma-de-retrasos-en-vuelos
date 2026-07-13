"""
config/logging_config.py
=========================
Configuración centralizada del logging de trazabilidad de SGIDA.

Expone `get_logger(name)` para que cualquier módulo (grafo, agentes,
router) obtenga un logger jerárquico bajo el espacio de nombres
"sgida". La primera llamada configura de forma perezosa un único
`StreamHandler` a stdout con formato de texto plano; llamadas
posteriores son no-op (no se duplican handlers).

Deliberadamente no importa `config.settings.Settings` para evitar un
ciclo de imports (Settings también quiere poder loggear su propia
validación). El nivel se lee directamente de la variable de entorno
`LOG_LEVEL` (por defecto "INFO"), igual que `settings.py` lee sus
propias variables de entorno de forma independiente.
"""

from __future__ import annotations

import logging
import os
import sys

_ROOT_LOGGER_NAME = "sgida"
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_configured = False


def configure_logging() -> None:
    """
    Configura el logger raíz "sgida" con un StreamHandler a stdout.
    Idempotente: si ya se configuró, no hace nada (evita handlers
    duplicados cuando varios módulos importan `get_logger` en el mismo
    proceso, p.ej. bajo pytest).
    """
    global _configured
    if _configured:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger(_ROOT_LOGGER_NAME)
    root_logger.setLevel(level)
    root_logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root_logger.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Devuelve un logger jerárquico bajo "sgida.<name>", garantizando que
    el logging esté configurado antes de usarlo.
    """
    configure_logging()
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
