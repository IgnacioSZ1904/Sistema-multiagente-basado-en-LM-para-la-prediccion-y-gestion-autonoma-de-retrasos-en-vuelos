"""
graph/supervisor.py
=====================
Agente orquestador (supervisor) y ensamblaje del StateGraph de SGIDA.

El supervisor es un nodo más del grafo, igual que los agentes
especializados, pero con una responsabilidad distinta: no produce
resultados de dominio, decide el routing. Usa salida estructurada
(Pydantic con un Literal) en lugar de texto libre, por la misma razón
que el resto del sistema: con Ollama, forzar el esquema de salida es
más fiable que parsear texto.

La decisión final de routing pasa SIEMPRE por `safe_next_node()`
(graph/router.py) antes de devolverse, como salvaguarda determinista.
"""

from __future__ import annotations

from typing import Literal, cast

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from langgraph.graph import END, StateGraph

from agents.analytical_agent import analytical_agent
from agents.communication_agent import communication_agent
from agents.disruption_agent import disruption_agent
from config.settings import Settings, get_llm
from graph.router import END_NODE, safe_next_node
from graph.state import SGIDAState, initial_state
from prompts.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Esquema de salida estructurada del supervisor
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    """Decisión de enrutamiento del supervisor."""

    next_node: Literal[
        "analytical_agent", "disruption_agent", "communication_agent", "END"
    ] = Field(description="Nombre del siguiente nodo al que debe saltar el grafo.")
    rationale: str = Field(
        description="Justificacion breve (1 frase) de por que se elige este nodo."
    )


def _build_state_summary(state: SGIDAState) -> str:
    """Resume el estado actual en texto plano para que el LLM decida el routing."""
    return (
        f"user_query: {state['user_query']}\n"
        f"flight_context: {state.get('flight_context')}\n"
        f"analytics_result presente: {state.get('analytics_result') is not None}\n"
        f"delay_prediction: {state.get('delay_prediction')}\n"
        f"disruption_proposal presente: {state.get('disruption_proposal') is not None}\n"
        f"final_response presente: {state.get('final_response') is not None}\n"
        f"error: {state.get('error')}\n"
        f"iteracion actual: {state['iteration']} / max. {Settings.GRAPH_MAX_ITERATIONS}"
    )


# ---------------------------------------------------------------------------
# Nodo del supervisor
# ---------------------------------------------------------------------------

def supervisor(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del supervisor. Prioriza routing determinista para
    evitar bloqueos innecesarios y solo usa LLM si Ollama está disponible.
    """
    llm_choice = safe_next_node(state, "")

    if state["iteration"] == 0:
        try:
            structured_llm = get_llm().with_structured_output(RoutingDecision)
            decision_raw = structured_llm.invoke([
                SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
                HumanMessage(content=_build_state_summary(state)),
            ])
            decision = RoutingDecision.model_validate(decision_raw)
            llm_choice = safe_next_node(state, decision.next_node)
            if Settings.DEBUG_MODE:
                print(f"[supervisor] LLM propone: {decision.next_node} - {decision.rationale}")
        except Exception as exc:  # noqa: BLE001
            if Settings.DEBUG_MODE:
                print(f"[supervisor] Error en decision de routing: {exc}")
            llm_choice = "communication_agent"

    next_node = safe_next_node(state, llm_choice)

    return {
        "next_agent": next_node,
        "iteration": state["iteration"] + 1,
    }


def _route_from_supervisor(state: SGIDAState) -> str:
    """
    Funcion de arista condicional: lee next_agent (ya validado por
    safe_next_node dentro de supervisor()) y lo traduce al
    identificador de destino que espera add_conditional_edges.
    """
    return END if state["next_agent"] == END_NODE else state["next_agent"]


# ---------------------------------------------------------------------------
# Ensamblaje del grafo
# ---------------------------------------------------------------------------

def build_graph():
    """
    Construye y compila el StateGraph de SGIDA.

    Topologia:
        supervisor -> {analytical_agent, disruption_agent,
                       communication_agent, END}
        analytical_agent -> supervisor
        disruption_agent -> supervisor
        communication_agent -> supervisor

    Todos los agentes especializados devuelven SIEMPRE el control al
    supervisor; es el supervisor quien decide si el flujo continua o
    termina. Esto mantiene una unica fuente de verdad para el routing.

    Returns
    -------
    CompiledGraph
        Grafo compilado, listo para .invoke() o .stream().
    """
    graph = StateGraph(SGIDAState)

    graph.add_node("supervisor", supervisor)
    graph.add_node("analytical_agent", analytical_agent)
    graph.add_node("disruption_agent", disruption_agent)
    graph.add_node("communication_agent", communication_agent)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "analytical_agent": "analytical_agent",
            "disruption_agent": "disruption_agent",
            "communication_agent": "communication_agent",
            END: END,
        },
    )

    # Todos los agentes vuelven al supervisor tras completar su trabajo.
    graph.add_edge("analytical_agent", "supervisor")
    graph.add_edge("disruption_agent", "supervisor")
    graph.add_edge("communication_agent", "supervisor")

    return graph.compile()


# ---------------------------------------------------------------------------
# Punto de entrada de conveniencia
# ---------------------------------------------------------------------------

def run_query(user_query: str) -> SGIDAState:
    """
    Ejecuta una consulta completa de extremo a extremo a traves del grafo.

    Parameters
    ----------
    user_query : str
        Consulta del operador en lenguaje natural.

    Returns
    -------
    SGIDAState
        Estado final tras la ejecucion del grafo (incluye final_response).
    """
    app = build_graph()
    return cast(SGIDAState, app.invoke(initial_state(user_query)))