"""
graph/supervisor.py
=====================
Agente orquestador (supervisor) y ensamblaje del StateGraph de SGIDA.

El supervisor es un nodo más del grafo, igual que los agentes
especializados, pero con una responsabilidad distinta: no produce
resultados de dominio, decide el routing.

Diseño 100% determinista (decisión documentada en la memoria del TFG,
evolutivo `revision-supervisor`): el supervisor solía consultar un LLM
para decidir el primer salto de cada consulta. Al auditar el sistema
se comprobó que esa decisión es matemáticamente redundante: en la
primera iteración, `initial_state()` garantiza que `analytics_result`
y `delay_prediction` están vacíos, así que la única regla de routing
que puede aplicar es "ir a `analytical_agent`" — exactamente la misma
que ya decide `graph/router.py::safe_next_node` de forma determinista.
El LLM nunca podía decidir algo distinto; solo añadía una llamada
completa de latencia y un punto de fallo más. Se elimina, siguiendo el
mismo patrón ya aplicado a los tres agentes especializados (sustituir
juicio de LLM por código determinista cuando el LLM no aporta valor
real).

`graph/router.py::safe_next_node` es ahora la ÚNICA fuente de verdad
del routing.
"""

from __future__ import annotations

import time
from typing import Callable, cast

from langgraph.graph import END, StateGraph

from agents.analytical_agent import analytical_agent
from agents.communication_agent import communication_agent
from agents.disruption_agent import disruption_agent
from config.logging_config import get_logger
from graph.router import END_NODE, safe_next_node
from graph.state import SGIDAState, initial_state

logger = get_logger("supervisor")
node_logger = get_logger("graph.node")


# ---------------------------------------------------------------------------
# Nodo del supervisor
# ---------------------------------------------------------------------------

def supervisor(state: SGIDAState) -> dict:
    """
    Nodo LangGraph del supervisor. Enteramente determinista: delega en
    `safe_next_node`, que ya aplica las reglas de negocio (qué agente
    sigue según lo que haya en el estado) y las salvaguardas (límite de
    iteraciones, nombres de nodo inválidos, no repetir un agente ya
    completado).
    """
    next_agent = safe_next_node(state, "")
    iteration = state["iteration"] + 1
    logger.info("Supervisor -> %s (iteracion %d)", next_agent, iteration)
    return {
        "next_agent": next_agent,
        "iteration": iteration,
    }


def _route_from_supervisor(state: SGIDAState) -> str:
    """
    Funcion de arista condicional: lee next_agent (ya validado por
    safe_next_node dentro de supervisor()) y lo traduce al
    identificador de destino que espera add_conditional_edges.
    """
    return END if state["next_agent"] == END_NODE else state["next_agent"]


# ---------------------------------------------------------------------------
# Instrumentación de nodos (trazabilidad de "qué agente está activo")
# ---------------------------------------------------------------------------

def _with_node_logging(name: str, fn: Callable[[SGIDAState], dict]) -> Callable[[SGIDAState], dict]:
    """
    Envuelve un nodo del grafo para loggear su entrada, salida y
    duración sin modificar el cuerpo de cada agente. Único punto de
    instrumentación para las 4 transiciones de nodo del grafo.
    """

    def _wrapped(state: SGIDAState) -> dict:
        node_logger.info(">> Entrando en nodo '%s'", name)
        start = time.perf_counter()
        result = fn(state)
        elapsed_ms = (time.perf_counter() - start) * 1000
        node_logger.info("<< Nodo '%s' completado en %.0f ms", name, elapsed_ms)
        return result

    return _wrapped


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

    graph.add_node("supervisor", _with_node_logging("supervisor", supervisor))
    graph.add_node("analytical_agent", _with_node_logging("analytical_agent", analytical_agent))
    graph.add_node("disruption_agent", _with_node_logging("disruption_agent", disruption_agent))
    graph.add_node("communication_agent", _with_node_logging("communication_agent", communication_agent))

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

def run_query(user_query: str, optimization_criterion: str | None = None) -> SGIDAState:
    """
    Ejecuta una consulta completa de extremo a extremo a traves del grafo.

    Parameters
    ----------
    user_query : str
        Consulta del operador en lenguaje natural.
    optimization_criterion : str | None
        Criterio de optimización elegido por el operador ("min_passengers" |
        "min_cost") para el agente de disrupciones. Si se omite, se usa
        Settings.DEFAULT_OPTIMIZATION_CRITERION.

    Returns
    -------
    SGIDAState
        Estado final tras la ejecucion del grafo (incluye final_response).
    """
    app = build_graph()
    return cast(SGIDAState, app.invoke(initial_state(user_query, optimization_criterion)))
