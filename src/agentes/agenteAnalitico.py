import os
import json
import pandas as pd
from dotenv import load_dotenv
from mistralai.client import Mistral

# -----------------------
# CONFIG
# -----------------------

load_dotenv()
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

# Carpeta base del script
BASE_DIR = os.path.dirname(__file__)

# Registro de datasets 
DATASETS = {
    "delay_por_ruta": os.path.join(BASE_DIR, "delay_por_ruta.csv"),
    "delay_por_aerolinea": os.path.join(BASE_DIR, "delay_por_aerolinea"),
    "delay_por_mes": os.path.join(BASE_DIR, "delay_por_mes.csv")
}

# -----------------------
# FUNCIONES (TOOLS)
# -----------------------

import pandas as pd

def top_delay_rutas(dataset: str, limit: int = 10) -> list[dict]:
    """
    Devuelve las rutas ordenadas por mayor retraso promedio.
    """
    if dataset not in DATASETS:
        raise ValueError(f"Dataset '{dataset}' no encontrado")

    csv_path = DATASETS[dataset]
    df = pd.read_csv(csv_path)

    # 1. Limpieza y conversión
    df["avg_delay"] = pd.to_numeric(df["avg_delay"], errors="coerce")
    df = df.dropna(subset=["avg_delay"])

    # 2. Ordenación (de mayor a menor)
    df_sorted = df.sort_values(by="avg_delay", ascending=False)

    # 3. Aplicar límite 
    if limit is not None:
        df_sorted = df_sorted.head(limit)

    # 4. Proyección y renombrado de columnas
    output_df = df_sorted[["OriginCityName", "DestCityName", "avg_delay", "vuelos"]].copy()
    output_df.rename(columns={
        "OriginCityName": "origen",
        "DestCityName": "destino"
    }, inplace=True)

    # 5. Casteo explícito a tipos nativos
    # Evita que Pandas devuelva tipos de numpy (ej. np.float64) que 
    # romperían la serialización JSON cuando el agente intente leer el output.
    output_df["avg_delay"] = output_df["avg_delay"].astype(float)
    output_df["vuelos"] = output_df["vuelos"].astype(int)

    # 6. Conversión final a lista de diccionarios
    return output_df.to_dict(orient="records")

def top_delay_mes(dataset: str, limit: int = 10) -> list[dict]:
    """
    Devuelve las rutas ordenadas por mayor retraso promedio.
    """
    if dataset not in DATASETS:
        raise ValueError(f"Dataset '{dataset}' no encontrado")

    csv_path = DATASETS[dataset]
    df = pd.read_csv(csv_path)

    # 1. Limpieza y conversión
    df["avg_dep_delay"] = pd.to_numeric(df["avg_dep_delay"], errors="coerce")
    df = df.dropna(subset=["avg_dep_delay"])

    # 2. Ordenación (de mayor a menor)
    df_sorted = df.sort_values(by="avg_dep_delay", ascending=False)

    # 3. Aplicar límite 
    if limit is not None:
        df_sorted = df_sorted.head(limit)

    # 4. Proyección y renombrado de columnas
    output_df = df_sorted[["Month", "avg_dep_delay"]].copy()

    # 5. Casteo explícito a tipos nativos
    # Evita que Pandas devuelva tipos de numpy (ej. np.float64) que 
    # romperían la serialización JSON cuando el agente intente leer el output.
    output_df["avg_dep_delay"] = output_df["avg_dep_delay"].astype(float)
    output_df["Month"] = output_df["Month"].astype(int)

    # 6. Conversión final a lista de diccionarios
    return output_df.to_dict(orient="records")


# -----------------------
# DEFINICIÓN DE TOOL
# -----------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "top_delay_rutas",
            "description": "Obtiene el orden de mayor a menor retraso de vuelos en las rutas",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "description": "delay_por_ruta.csv",
                        "enum": ["delay_por_ruta"]
                    }
                },
                "required": ["dataset"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "top_delay_mes",
            "description": "Obtiene el orden de los meses de mayor a menor retraso de media en vuelos",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "description": "delay_por_mes.csv",
                        "enum": ["delay_por_mes"]
                    }
                },
                "required": ["dataset"]
            }
        }
    }
]

# -----------------------
# 1. LLAMADA AL MODELO
# -----------------------

response = client.chat.complete(
    model="mistral-medium-latest",
    messages=[
        {
            "role": "user",
            "content": "¿Cuales son los 3 meses con mayor posibilidad de retraso en mi vuelo?"
        }
    ],
    tools=tools
)

choice = response.choices[0]

# -----------------------
# 2. EJECUCIÓN DE TOOL (DINÁMICA)
# -----------------------

# Diccionario que mapea el nombre de la herramienta a la función real de Python
available_functions = {
    "top_delay_rutas": top_delay_rutas,
    "top_delay_mes": top_delay_mes
}

if choice.finish_reason == "tool_calls":
    tool_call = choice.message.tool_calls[0]
    
    function_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)
    
    print(f"El agente ha decidido usar: {function_name}")
    print(f"Con los argumentos: {arguments}")

    # Extraemos la función del diccionario de forma segura
    function_to_call = available_functions.get(function_name)

    if function_to_call:
        # Ejecutamos la función de forma dinámica desempaquetando los kwargs
        result = function_to_call(**arguments)
        print("\nResultado función:", result)
    else:
        print(f"Error crítico: El modelo alucinó una función no registrada '{function_name}'")
else:
    print("Respuesta directa del modelo:")
    print(response.choices[0].message.content)