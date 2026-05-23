import os
from crewai import Crew, Process, Task
from dotenv import load_dotenv

# Importamos las funciones generadoras de nuestros agentes
# (Asumimos que cada archivo devuelve un objeto Agent de CrewAI)
from src.agentes.agenteGestor import crear_agente_gestor
from src.agentes.agenteAnalitico import crear_agente_analitico
from src.agentes.agenteComunicacion import crear_agente_comunicacion

# Cargar variables de entorno (MISTRAL_API_KEY)
load_dotenv()

def ejecutar_flujo_analisis(query_usuario: str, contexto_extra: str = None) -> str:
    """
    Punto de entrada principal para la API. Orquesta el equipo de agentes
    para resolver la consulta del usuario sobre los datos de vuelos.
    
    Args:
        query_usuario (str): La pregunta o petición cruda del usuario.
        contexto_extra (str, opcional): Ej. una aerolínea o mes específico.
        
    Returns:
        str: El informe final generado por el sistema multiagente.
    """
    
    # 1. Instanciación de Agentes
    # Al crearlos aquí, aseguramos que se inician limpios en cada petición HTTP
    gestor = crear_agente_gestor()
    analitico = crear_agente_analitico()
    comunicador = crear_agente_comunicacion()

    # 2. Definición del Grafo de Tareas (DAG)
    # Tarea 1: El gestor interpreta y planifica
    tarea_planificacion = Task(
        description=(
            f"Analiza la siguiente petición del usuario: '{query_usuario}'. "
            f"Contexto adicional: {contexto_extra}. "
            "Tu objetivo es trazar un plan de acción especificando qué datos, "
            "métricas y columnas deben ser extraídas del dataset de vuelos."
        ),
        expected_output="Un listado claro de variables a calcular y filtros a aplicar (ej. 'Filtrar por aerolínea DL y calcular media de DepDelay').",
        agent=gestor
    )

    # Tarea 2: El analítico ejecuta la extracción (usará tools de pandas internamente)
    tarea_analisis = Task(
        description=(
            "Basándote en el plan del Gestor, utiliza tus herramientas de análisis "
            "para extraer los insights matemáticos del dataset de vuelos. "
            "No deduzcas datos, usa resultados reales."
        ),
        expected_output="Un bloque de texto con los resultados estadísticos numéricos exactos de la consulta.",
        agent=analitico
    )

    # Tarea 3: El comunicador redacta el reporte final
    tarea_redaccion = Task(
        description=(
            "Toma los datos crudos obtenidos por el Agente Analítico y redacta "
            "un resumen ejecutivo profesional. Debe ser fácil de leer para un "
            "directivo y estar formateado en Markdown."
        ),
        expected_output="Informe ejecutivo en Markdown con títulos, viñetas y (si aplica) tablas.",
        agent=comunicador
    )

    # 3. Ensamblaje del "Crew" (Equipo)
    sistema_multiagente = Crew(
        agents=[gestor, analitico, comunicador],
        tasks=[tarea_planificacion, tarea_analisis, tarea_redaccion],
        process=Process.sequential, # Ejecución en cascada (A -> B -> C)
        verbose=True # Útil para ver la "cadena de pensamiento" en la terminal de FastAPI
    )

    # 4. Kickoff (Ejecución del pipeline)
    resultado_final = sistema_multiagente.kickoff()

    return str(resultado_final)