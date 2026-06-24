"""
config/settings.py
==================
Configuración central de SGIDA.

Carga las variables de entorno desde .env y expone:
  - Parámetros globales del sistema (umbrales, rutas, debug).
  - Una función `get_llm()` que devuelve el ChatModel de Ollama configurado.

Requiere tener Ollama corriendo localmente (https://ollama.com) con el
modelo descargado, por ejemplo:
    ollama pull llama3.1
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Carga del fichero .env
# ---------------------------------------------------------------------------
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
class Settings:
    """Agrupa todos los parámetros de configuración del sistema."""

    # --- LLM (Ollama local) ----------------------------------------------
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1")
    OLLAMA_ENABLED: bool = os.getenv("OLLAMA_ENABLED", "true").lower() == "true"

    # --- Parámetros del LLM ----------------------------------------------
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    LLM_REQUEST_TIMEOUT: float = float(os.getenv("LLM_REQUEST_TIMEOUT", "20"))

    # --- Base de datos ---------------------------------------------------
    DB_PATH: str = os.getenv("DB_PATH", "data/analytical_db.duckdb")

    # --- Parámetros del grafo -------------------------------------------
    GRAPH_MAX_ITERATIONS: int = int(os.getenv("GRAPH_MAX_ITERATIONS", "6"))

    # --- Dominio aéreo ---------------------------------------------------
    DELAY_THRESHOLD_MINUTES: int = int(os.getenv("DELAY_THRESHOLD_MINUTES", "15"))

    # --- Depuración ------------------------------------------------------
    DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"

    @classmethod
    def validate(cls) -> None:
        """Valida que la configuración mínima esté presente."""
        if not cls.OLLAMA_MODEL:
            raise ValueError("Falta OLLAMA_MODEL en .env (ej. 'llama3.1').")

        if cls.DEBUG_MODE:
            print("[SGIDA·config] Configuración validada.")
            print(f"  Modelo     : {cls.OLLAMA_MODEL}")
            print(f"  Ollama URL : {cls.OLLAMA_BASE_URL}")
            print(f"  DB path    : {cls.DB_PATH}")
            print(f"  Threshold  : {cls.DELAY_THRESHOLD_MINUTES} min")

    @classmethod
    def ollama_available(cls) -> bool:
        if not cls.OLLAMA_ENABLED:
            return False

        try:
            response = httpx.get(
                f"{cls.OLLAMA_BASE_URL}/api/tags",
                timeout=min(cls.LLM_REQUEST_TIMEOUT, 5.0),
            )
            return response.is_success
        except httpx.HTTPError:
            return False


# ---------------------------------------------------------------------------
# Factoría de LLM
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_llm() -> Any:
    """
    Devuelve la instancia de ChatOllama configurada.
    Cacheada para reutilizar la misma instancia en todos los agentes.
    """
    from langchain_ollama import ChatOllama

    Settings.validate()

    return ChatOllama(
        model=Settings.OLLAMA_MODEL,
        base_url=Settings.OLLAMA_BASE_URL,
        temperature=Settings.LLM_TEMPERATURE,
        num_predict=Settings.LLM_MAX_TOKENS,
        client_kwargs={"timeout": Settings.LLM_REQUEST_TIMEOUT},
    )
