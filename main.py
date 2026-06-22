"""
main.py
========
Punto de entrada de SGIDA — Sistema de Gestión Integral de Disrupciones
Aéreas.

Proporciona una interfaz conversacional por línea de comandos: el
operador escribe consultas en lenguaje natural y el sistema multiagente
(supervisor + agentes especializados) procesa cada una de forma
independiente, mostrando la respuesta final y, en modo debug, el
razonamiento intermedio de cada agente.

Cada consulta arranca con un estado limpio (graph.state.initial_state):
no hay memoria conversacional entre turnos en esta versión. Esto
simplifica el razonamiento del supervisor y facilita la depuración,
a costa de que el operador deba dar contexto completo en cada consulta.

Uso:
    python main.py
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from config.settings import Settings
from graph.state import initial_state
from graph.supervisor import build_graph

console = Console()

_BANNER = """\
[bold cyan]SGIDA[/bold cyan] — Sistema de Gestión Integral de Disrupciones Aéreas
[dim]Modelo local: {model}  |  Umbral de disrupción: {threshold} min[/dim]

Escribe tu consulta en lenguaje natural. Ejemplos:
  • "¿Qué aeropuertos tienen más retrasos?"
  • "¿Cuál es la causa principal de los retrasos?"
  • "Predice el retraso del vuelo AA en la ruta de Chicago, IL a Denver, CO en marzo a las 14:00"

Escribe [bold]salir[/bold] o [bold]exit[/bold] para terminar.
"""


def _print_banner() -> None:
    console.print(
        Panel(
            _BANNER.format(
                model=Settings.OLLAMA_MODEL,
                threshold=Settings.DELAY_THRESHOLD_MINUTES,
            ),
            border_style="cyan",
        )
    )


def _print_debug_trace(final_state: dict) -> None:
    """Muestra el estado intermedio relevante cuando DEBUG_MODE está activo."""
    trace = Text()
    trace.append("Traza interna (DEBUG_MODE)\n", style="bold yellow")
    trace.append(f"Iteraciones del grafo: {final_state.get('iteration')}\n")

    if final_state.get("analytics_result"):
        trace.append(f"analytics_result: {final_state['analytics_result']}\n", style="dim")
    if final_state.get("delay_prediction"):
        trace.append(f"delay_prediction: {final_state['delay_prediction']}\n", style="dim")
    if final_state.get("disruption_proposal"):
        trace.append(f"disruption_proposal: {final_state['disruption_proposal']}\n", style="dim")
    if final_state.get("error"):
        trace.append(f"error: {final_state['error']}\n", style="bold red")

    console.print(Panel(trace, border_style="yellow", title="Debug"))


def _run_single_query(user_query: str) -> None:
    """Ejecuta una consulta de extremo a extremo con estado limpio y muestra el resultado."""
    app = build_graph()

    try:
        with console.status("[bold green]Procesando consulta...", spinner="dots"):
            final_state = app.invoke(initial_state(user_query))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Error inesperado al ejecutar el grafo:[/bold red] {exc}")
        return

    response = final_state.get("final_response") or (
        "El sistema no generó una respuesta final. Esto no debería ocurrir; "
        "revisa los logs en modo debug."
    )

    console.print(
        Panel(Markdown(response), title="SGIDA", border_style="green")
    )

    if Settings.DEBUG_MODE:
        _print_debug_trace(final_state)


def main() -> None:
    """Bucle principal de la CLI conversacional."""
    _print_banner()

    while True:
        try:
            user_query = console.input("\n[bold blue]Operador >[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Sesión finalizada.[/dim]")
            break

        if not user_query:
            continue

        if user_query.lower() in {"salir", "exit", "quit"}:
            console.print("[dim]Sesión finalizada.[/dim]")
            break

        _run_single_query(user_query)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Error fatal:[/bold red] {exc}")
        sys.exit(1)