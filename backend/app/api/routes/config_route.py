from app.core.config import settings
from app.schemas.common import SystemConfigResponse
from fastapi import APIRouter

router = APIRouter()


@router.get("/config", response_model=SystemConfigResponse)
def get_config():
    return SystemConfigResponse(
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        api_version="v1",
        market_provider=settings.MARKET_DATA_PROVIDER,
        ollama_enabled=settings.OLLAMA_ENABLED,
        ollama_model=settings.OLLAMA_MODEL,
        initial_equity=settings.INITIAL_EQUITY,
        initial_cash=settings.INITIAL_CASH,
    )
