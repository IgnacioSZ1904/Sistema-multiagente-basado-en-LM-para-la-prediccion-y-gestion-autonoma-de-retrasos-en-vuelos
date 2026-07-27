# SGIDA — Sistema Multiagente para la Gestión Autónoma de Retrasos en el Tráfico Aéreo

## 📌 Descripción del proyecto

Este repositorio contiene el Trabajo de Fin de Grado (TFG) centrado en el diseño y desarrollo de un sistema multiagente basado en un Modelo de Lenguaje (LLM) local (Ollama). El objetivo es mitigar el impacto operativo de los retrasos aéreos, un problema que genera un efecto dominó en la red aeroportuaria.

El sistema analiza el histórico de vuelos, predice retrasos y su impacto sobre operaciones conectadas, y propone respuestas de forma autónoma, usando como base de conocimiento un dataset real de vuelos comerciales en EE. UU. (BTS/Kaggle).

## 🧠 Arquitectura del sistema multiagente

El núcleo es un grafo de agentes (LangGraph) coordinados por un supervisor determinista:

- **Supervisor** (`graph/supervisor.py`): decide a qué agente salta el flujo en cada paso. Es 100% determinista (sin LLM) — las reglas de routing dependen solo de qué campos del estado ya están rellenos.
- **Agente Analítico** (`agents/analytical_agent.py`): procesa el histórico de vuelos (DuckDB) para detectar patrones de retraso (rutas, aeropuertos, franjas horarias, causas) y, ante una consulta de vuelo concreto, calcula estadísticas históricas y predice el retraso esperado y su impacto en operaciones conectadas (cascade risk). La predicción usa un modelo Random Forest (scikit-learn) entrenado sobre el histórico completo (`data/train_delay_model.py`), con un heurístico SQL como respaldo automático si el modelo no está disponible — ver `docs/features/prediccion-ml-real/`. Devuelve siempre JSON estructurado, nunca lenguaje natural.
- **Agente de Gestión de Disrupciones** (`agents/disruption_agent.py`): ante una disrupción detectada, evalúa alternativas de reasignación según un criterio configurable (minimizar pasajeros afectados o coste operativo) y propone acciones concretas.
- **Agente de Comunicación** (`agents/communication_agent.py`): traduce las decisiones del sistema a lenguaje natural para el operador, y redacta (sin enviar) borradores de notificación para operador y pasajeros afectados.

## ⚙️ Funcionalidades principales

- Análisis exploratorio automatizado de causas, aeropuertos y rutas con mayor incidencia de retrasos.
- Predicción de retrasos en tiempo real y estimación de su impacto sobre operaciones conectadas.
- Generación autónoma de propuestas de actuación, con criterio configurable (pasajeros afectados vs. coste operativo).
- Interfaz conversacional (chat) para interactuar con el sistema en lenguaje natural.
- Panel de estado (dashboard) con vuelos en riesgo, decisiones del sistema y métricas de rendimiento global.

## 🛠️ Stack tecnológico

- **Backend**: Python, FastAPI, LangChain + LangGraph, Ollama (LLM local).
- **Datos**: DuckDB sobre un dataset histórico de vuelos (Parquet).
- **Frontend**: React + Vite.
- **Tests**: pytest.

---

## 🚀 Guía de inicio rápido

### 1. Requisitos previos

- Python 3.11+
- Node.js 18+ (para el frontend)
- [Ollama](https://ollama.com) instalado y corriendo localmente
- El dataset [Flight Delay (Kaggle)](https://www.kaggle.com/datasets/arvindnagaonkar/flight-delay) descargado como `data/Flight_Delay.parquet` (no se sube al repositorio, ver `.gitignore`)

Descarga el modelo de Ollama que vayas a usar (por defecto `llama3.1`):

```powershell
ollama pull llama3.1
```

### 2. Backend — instalación y datos

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env

python data\data_ingestion.py
```

`data_ingestion.py` valida `data/Flight_Delay.parquet` y construye `data/analytical_db.duckdb`, la base de datos que consultan las tools de los agentes. Es un paso único: solo hace falta repetirlo si cambia el dataset.

Con la base de datos ya creada, entrena el modelo predictivo de retrasos (evolutivo `prediccion-ml-real`):

```powershell
venv\Scripts\python data\train_delay_model.py
```

Este script entrena, sobre `data/analytical_db.duckdb`, un regresor y un clasificador (scikit-learn) que sustituyen al heurístico SQL como fuente de `delay_prediction`, y guarda el artefacto en `data/models/delay_model.joblib` (no versionado en git). Es también un paso único: solo hace falta repetirlo si cambia el dataset o si se quiere reentrenar con otros hiperparámetros. Si no se ejecuta (o el artefacto no existe), `analytical_agent` cae automáticamente al heurístico SQL anterior — el sistema funciona igualmente, solo que sin el modelo entrenado. Métricas y proceso de evaluación documentados en `docs/features/prediccion-ml-real/model_evaluacion.md`.

Revisa `.env` y ajusta lo que necesites (modelo de Ollama, umbral de disrupción, criterio de optimización por defecto, ruta del modelo predictivo, etc.) — ver `.env.example` para todas las variables disponibles.

### 3. Levantar el backend (API)

```powershell
venv\Scripts\python -m uvicorn backend.main:app --reload
```

La API queda disponible en `http://127.0.0.1:8000` (documentación interactiva en `http://127.0.0.1:8000/docs`). Endpoints principales, todos bajo `/api`: `/health`, `/query`, `/dashboard`, `/notifications/send`.

### 4. Levantar el frontend

En otra terminal:

```powershell
cd frontend
npm install
npm run dev
```

Vite sirve el frontend en `http://localhost:5173` (por defecto), con dos pestañas: **Chat** (consulta en lenguaje natural + selector de criterio de optimización) y **Panel de estado** (métricas y actividad reciente). El frontend espera el backend en `http://127.0.0.1:8000/api` (ver `frontend/src/api.js`).

### 5. Alternativa: CLI sin frontend

Para probar el sistema por terminal sin levantar API ni frontend:

```powershell
venv\Scripts\python main.py
```

### 6. Ejecutar los tests

```powershell
venv\Scripts\python -m pytest
```

Los tests marcados con `requires_db` se omiten automáticamente si `data/analytical_db.duckdb` no existe (en vez de fallar), y los tests de agentes mockean el LLM — no necesitas Ollama corriendo para ejecutar la suite completa.

---

## 📂 Estructura relevante del repositorio

```
agents/       Nodos LangGraph de cada agente (analítico, disrupción, comunicación)
graph/        Estado compartido, supervisor y ensamblaje del grafo
prompts/      Prompts de sistema de cada agente
tools/        Herramientas (@tool) que consultan DuckDB o simulan notificaciones
config/       Configuración central (Settings, factoría del LLM)
data/         Script de ingesta, entrenamiento del modelo predictivo y base de datos DuckDB (generados localmente)
backend/      API FastAPI (rutas, schemas, servicios) y CLI
frontend/     Interfaz React (chat + panel de estado)
tests/        Suite de tests (unit/ e integration/)
docs/features/  Documentación de cada evolutivo (metodología en AGENTS.md)
```

## 🔄 Metodología

El desarrollo de evolutivos (nuevas funcionalidades, refactors significativos) sigue la metodología descrita en [`AGENTS.md`](AGENTS.md): análisis → planificación → desglose de tareas → ejecución iterativa → cierre, con trazabilidad completa en `docs/features/<evolutivo>/`.
