from datetime import UTC, datetime

from app.api.dependencies import get_db
from app.core.config import settings
from app.review.model_client import review_model_client
from app.schemas.common import HealthResponse
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def get_health(db: Session = Depends(get_db)):
    # Verify DB connectivity
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        db_status = f"unhealthy: {e!s}"

    ollama = await review_model_client.get_model_status()

    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        database_status=db_status,
        market_provider=settings.MARKET_DATA_PROVIDER,
        ollama_status=ollama["status_message"],
        timestamp=datetime.now(UTC),
    )
