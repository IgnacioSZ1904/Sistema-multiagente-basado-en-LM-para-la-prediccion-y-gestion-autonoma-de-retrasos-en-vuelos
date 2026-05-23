import os
from dotenv import load_dotenv
from crewai import LLM  # <-- Usamos la clase nativa de CrewAI

load_dotenv()

def get_mistral_llm():
    """Devuelve la instancia nativa del LLM configurada para Mistral."""
    
    # Verificamos que la clave exista para evitar errores silenciosos
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("CRÍTICO: No se ha encontrado MISTRAL_API_KEY en el entorno.")

    # Instanciamos el LLM usando la sintaxis de proveedor/modelo
    return LLM(
        model="mistral/mistral-large-latest",
        temperature=0.2,
        api_key=api_key
    )