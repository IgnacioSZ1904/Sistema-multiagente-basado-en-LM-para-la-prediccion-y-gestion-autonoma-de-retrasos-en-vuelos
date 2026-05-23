from fastapi import FastAPI
from src.api.routes import router

app = FastAPI(
    title="API Sistema Multiagente TFG",
    description="Backend para análisis de vuelos usando Mistral AI",
    version="1.0.0"
)

app.include_router(router)