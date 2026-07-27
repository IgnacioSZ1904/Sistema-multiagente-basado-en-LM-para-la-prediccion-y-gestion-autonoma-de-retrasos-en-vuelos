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
    # Los turnos ReAct de bind_tools (analytical_agent) solo emiten
    # tool_calls, nunca prosa larga, así que usan un límite mucho menor que
    # LLM_MAX_TOKENS (que sí necesitan communication_agent/disruption_agent
    # para redactar su narrativa). Esto acota el peor caso de latencia de
    # decodificación en CPU sin tocar el límite de los otros agentes.
    LLM_MAX_TOKENS_TOOLS: int = int(os.getenv("LLM_MAX_TOKENS_TOOLS", "256"))
    LLM_REQUEST_TIMEOUT: float = float(os.getenv("LLM_REQUEST_TIMEOUT", "20"))
    LLM_CONNECT_TIMEOUT: float = float(os.getenv("LLM_CONNECT_TIMEOUT", "10"))
    # Cuanto tiempo mantiene Ollama el modelo cargado en memoria entre
    # llamadas (formato Ollama: "30m", "1h", etc.). Sin esto, Ollama usa su
    # default de 5 minutos y descarga el modelo entre turnos del grafo,
    # forzando una recarga completa (decenas de segundos) en cada llamada.
    OLLAMA_KEEP_ALIVE: str = os.getenv("OLLAMA_KEEP_ALIVE", "5m")

    # --- Base de datos ---------------------------------------------------
    DB_PATH: str = os.getenv("DB_PATH", "data/analytical_db.duckdb")

    # --- Modelo predictivo de retrasos (evolutivo prediccion-ml-real) ----
    # Artefacto entrenado por data/train_delay_model.py. Si el fichero no
    # existe o falla la carga, analytical_agent cae al heurístico SQL
    # anterior (mismo patrón de modo degradado que ollama_available()).
    DELAY_MODEL_PATH: str = os.getenv("DELAY_MODEL_PATH", "data/models/delay_model.joblib")

    # --- Parámetros del grafo -------------------------------------------
    GRAPH_MAX_ITERATIONS: int = int(os.getenv("GRAPH_MAX_ITERATIONS", "6"))

    # --- Dominio aéreo ---------------------------------------------------
    DELAY_THRESHOLD_MINUTES: int = int(os.getenv("DELAY_THRESHOLD_MINUTES", "15"))

    # --- Criterio de optimización del agente de disrupción ---------------
    OPTIMIZATION_CRITERIA: tuple[str, ...] = ("min_passengers", "min_cost")
    DEFAULT_OPTIMIZATION_CRITERION: str = os.getenv(
        "DEFAULT_OPTIMIZATION_CRITERION", "min_passengers"
    )

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
            print(f"  LLM timeout: {cls.LLM_REQUEST_TIMEOUT}s (connect {cls.LLM_CONNECT_TIMEOUT}s)")
            print(f"  Keep-alive : {cls.OLLAMA_KEEP_ALIVE}")

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
        keep_alive=Settings.OLLAMA_KEEP_ALIVE,
        client_kwargs={
            "timeout": httpx.Timeout(
                Settings.LLM_REQUEST_TIMEOUT, connect=Settings.LLM_CONNECT_TIMEOUT
            )
        },
    )


@lru_cache(maxsize=1)
def get_tool_llm() -> Any:
    """
    Devuelve la instancia de ChatOllama para el bucle ReAct de bind_tools
    (analytical_agent). Misma configuración que get_llm() salvo
    num_predict, mucho más bajo (ver LLM_MAX_TOKENS_TOOLS) porque estos
    turnos solo deciden qué tool_call emitir.
    """
    from langchain_ollama import ChatOllama

    Settings.validate()

    return ChatOllama(
        model=Settings.OLLAMA_MODEL,
        base_url=Settings.OLLAMA_BASE_URL,
        temperature=Settings.LLM_TEMPERATURE,
        num_predict=Settings.LLM_MAX_TOKENS_TOOLS,
        keep_alive=Settings.OLLAMA_KEEP_ALIVE,
        client_kwargs={
            "timeout": httpx.Timeout(
                Settings.LLM_REQUEST_TIMEOUT, connect=Settings.LLM_CONNECT_TIMEOUT
            )
        },
    )
