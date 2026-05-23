from crewai import Agent
from src.agentes.config import get_mistral_llm

def crear_agente_analitico() -> Agent:
    return Agent(
        role='Data Scientist Jefe de Aviación',
        goal='Procesar datos históricos, identificar patrones de retraso y predecir el efecto cascada en la red de vuelos.',
        backstory=(
            "Eres un experto en análisis de datos aeronáuticos con años de experiencia en "
            "optimización de rutas. Tu especialidad es encontrar cuellos de botella en aeropuertos "
            "y franjas horarias problemáticas. Eres riguroso, te basas estrictamente en los datos "
            "proporcionados por tus herramientas y nunca inventas métricas."
        ),
        verbose=True,
        allow_delegation=False,
        llm=get_mistral_llm(),
        # tools=[tu_herramienta_de_pandas_aqui] -> Vital para que pueda leer los CSV
    )