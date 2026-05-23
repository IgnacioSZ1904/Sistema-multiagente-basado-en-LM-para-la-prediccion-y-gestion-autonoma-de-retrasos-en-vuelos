from fastapi import APIRouter
from src.api.schemas import AnalysisRequest, AnalysisResponse
from src.agenteOrquestador import ejecutar_flujo_analisis

router = APIRouter()

@router.post("/api/v1/analyze", response_model=AnalysisResponse)
async def analyze_flight_data(request: AnalysisRequest):
    # Pasamos la petición de la API a nuestro motor de agentes
    resultado_agentes = ejecutar_flujo_analisis(request.query, request.aerolinea_foco)
    
    return AnalysisResponse(
        status="success",
        result=resultado_agentes
    )