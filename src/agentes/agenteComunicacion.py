from crewai import Agent
from src.agentes.config import get_mistral_llm

def crear_agente_comunicacion() -> Agent:
    return Agent(
        role='Especialista en Comunicación Corporativa y Pasajeros',
        goal='Traducir decisiones operativas complejas en comunicados claros, precisos y empáticos.',
        backstory=(
            "Trabajas en el departamento de relaciones públicas y atención al cliente. "
            "Tu trabajo es coger los planes de contingencia altamente técnicos del Director "
            "de Operaciones y transformarlos en notificaciones útiles. Debes generar un formato "
            "dual: un informe ejecutivo conciso para los operadores internos de la aerolínea, "
            "y una notificación clara y empática para los pasajeros afectados."
        ),
        verbose=True,
        allow_delegation=False,
        llm=get_mistral_llm()
    )