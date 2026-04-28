import os
import json
from dotenv import load_dotenv
from mistralai.client import Mistral

# -----------------------
# CONFIGURACIÓN
# -----------------------
load_dotenv()
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

def generar_plan_mitigacion(datos_analiticos: list[dict], contexto_operativo: str) -> str:
    """
    Agente Gestor de Disrupciones.
    Toma datos crudos de analítica y propone un plan de acción estructurado.
    
    :param datos_analiticos: Lista de diccionarios (ej. el output de top_delay_mes)
    :param contexto_operativo: La pregunta o contexto original del usuario
    """
    
    # 1. Definición del System Prompt (El 'Cerebro' del Gestor)
    system_prompt = """
    Eres un Gestor de Operaciones de Aviación de nivel Senior.
    Tu objetivo es analizar datos de disrupciones (retrasos) y proponer soluciones operativas estrictas, viables y rentables.
    
    Reglas de negocio:
    1. Basa tus recomendaciones ÚNICAMENTE en los datos analíticos proporcionados.
    2. Propón exactamente 3 acciones mitigadoras estructuradas a corto y medio plazo.
    3. Si los datos indican meses de verano o invierno, ajusta las soluciones a problemas climáticos o picos de demanda estacionales.
    """

    # 2. Inyección de Contexto (Prompt Engineering)
    # Convertimos los datos estructurados en un string formateado para el LLM
    datos_str = json.dumps(datos_analiticos, indent=2)
    
    user_prompt = f"""
    Contexto de la solicitud original: "{contexto_operativo}"
    
    Datos analíticos extraídos del sistema:
    {datos_str}
    
    Por favor, genera el plan de mitigación operativo basándote en estos resultados.
    """

    # 3. Llamada al Modelo
    # Usamos mistral-large-latest porque la planificación operativa requiere
    # mayor capacidad de razonamiento lógico que la simple extracción de datos.
    response = client.chat.complete(
        model="mistral-large-latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3 # Temperatura baja (0.3) para respuestas deterministas y menos creativas/alucinadas
    )

    return response.choices[0].message.content

# -----------------------
# PRUEBA UNITARIA (MOCK)
# -----------------------
if __name__ == "__main__":
    # Simulamos el output exacto que tu Agente Analítico devolvería:
    mock_output_analitico = [
        {'Month': 7, 'avg_dep_delay': 53.26},
        {'Month': 6, 'avg_dep_delay': 52.41},
        {'Month': 8, 'avg_dep_delay': 52.37}
    ]
    
    pregunta_usuario = "¿Cuales son los 3 meses con mayor posibilidad de retraso en mi vuelo y qué hacemos al respecto?"
    
    print("Iniciando Agente Gestor...\n")
    plan_accion = generar_plan_mitigacion(
        datos_analiticos=mock_output_analitico,
        contexto_operativo=pregunta_usuario
    )
    
    print(plan_accion)