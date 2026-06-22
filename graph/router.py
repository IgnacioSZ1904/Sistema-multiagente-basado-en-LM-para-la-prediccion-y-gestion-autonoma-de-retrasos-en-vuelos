"""
graph/router.py
================
Lógica de enrutamiento condicional del grafo y salvaguardas
deterministas.

El supervisor (graph/supervisor.py) decide el routing principal vía
LLM, tal como se ha decidido para este TFG. Este módulo NO sustituye
esa decisión: aporta una red de seguridad para los dos fallos típicos
de un routing basado en LLM con un modelo local (Ollama) — bucles
infinitos y nombres de nodo inválidos — sin alterar la lógica de
negocio que decide A QUÉ agente ir.
"""

from __future__ import annotations

from config.settings import Settings
from graph.state import SGIDAState

# Nombres de nodo válidos — deben coincidir exactamente con los
# registrados en graph/supervisor.py al construir el StateGraph.
VALID_AGENT_NODES = {
    "analytical_agent",
    "disruption_agent",
    "communication_agent",
}

END_NODE = "END"


def safe_next_node(state: SGIDAState, llm_decision: str) -> str:
    """
    Valida la decisión de routing del LLM y aplica salvaguardas
    deterministas antes de devolver el nombre de nodo definitivo.

    Salvaguardas aplicadas, en orden:
      1. Límite de iteraciones: si `state["iteration"]` alcanza
         `Settings.GRAPH_MAX_ITERATIONS`, se fuerza "communication_agent"
         (o "END" si ya hay final_response) para evitar bucles infinitos
         por indecisión del LLM.
      2. Nombre de nodo inválido: si el LLM devuelve algo que no es un
         nodo conocido ni "END", se aplica un fallback determinista
         basado en qué campos del estado ya están rellenos (mismas
         reglas que describe el prompt del supervisor, como red de
         seguridad).
      3. Re-ejecución de un agente que ya produjo su resultado: se
         evita reenviar al mismo agente dos veces (protección extra
         contra bucles cortos).

    Parameters
    ----------
    state : SGIDAState
        Estado actual del grafo.
    llm_decision : str
        Nombre de nodo devuelto por el supervisor (LLM).

    Returns
    -------
    str
        Nombre de nodo validado: uno de VALID_AGENT_NODES o "END".
    """
    decision = llm_decision.strip()

    # --- Salvaguarda 1: límite de iteraciones -----------------------------
    if state["iteration"] >= Settings.GRAPH_MAX_ITERATIONS:
        if Settings.DEBUG_MODE:
            print(
                f"[router] Límite de {Settings.GRAPH_MAX_ITERATIONS} "
                "iteraciones alcanzado; forzando salida del grafo."
            )
        return END_NODE if state.get("final_response") else "communication_agent"

    # --- Salvaguarda 2: nombre de nodo inválido ---------------------------
    if decision not in VALID_AGENT_NODES and decision != END_NODE:
        if Settings.DEBUG_MODE:
            print(f"[router] Decisión de routing inválida: '{decision}'. Aplicando fallback.")
        decision = _deterministic_fallback(state)

    # --- Salvaguarda 3: evitar repetir un agente ya completado ------------
    if decision == "analytical_agent" and (
        state.get("analytics_result") or state.get("delay_prediction")
    ):
        decision = _deterministic_fallback(state)

    if decision == "disruption_agent" and state.get("disruption_proposal"):
        decision = "communication_agent"

    return decision


def _deterministic_fallback(state: SGIDAState) -> str:
    """
    Aplica las mismas reglas descritas en el prompt del supervisor,
    pero de forma determinista, como red de seguridad cuando el LLM
    falla en producir una decisión válida.
    """
    if state.get("error") and not state.get("final_response"):
        return "communication_agent"

    if state.get("final_response"):
        return END_NODE

    if not state.get("analytics_result") and not state.get("delay_prediction"):
        return "analytical_agent"

    delay_prediction = state.get("delay_prediction")
    if (
        delay_prediction
        and delay_prediction.get("is_disruption")
        and not state.get("disruption_proposal")
    ):
        return "disruption_agent"

    return "communication_agent"