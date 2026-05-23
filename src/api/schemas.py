from pydantic import BaseModel, Field

class AnalysisRequest(BaseModel):
    query: str = Field(..., description="La pregunta del usuario (ej. 'Analiza los retrasos de Delta')")
    aerolinea_foco: str | None = Field(default=None, description="Aerolínea específica a filtrar")

class AnalysisResponse(BaseModel):
    status: str
    result: str