from crewai import Agent
from src.agentes.config import get_mistral_llm

def crear_agente_gestor() -> Agent:
    return Agent(
        role='Director de Operaciones y Resolución de Disrupciones',
        goal='Evaluar las predicciones de retraso y proponer soluciones operativas para minimizar el impacto en pasajeros y costes.',
        backstory=(
            "Eres el principal responsable de la toma de decisiones cuando ocurre un imprevisto "
            "en la aerolínea. Recibes alertas de retrasos del departamento analítico y tu deber "
            "es evaluar alternativas logísticas: reasignación de pasajeros, retención de vuelos "
            "de conexión o priorización de recursos en pista. Buscas el equilibrio entre coste "
            "operativo y satisfacción del cliente."
        ),
        verbose=True,
        allow_delegation=False, # En este diseño lineal, no delega hacia atrás
        llm=get_mistral_llm()
    )