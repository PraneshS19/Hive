from app.api.dependencies import get_db
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_service import dashboard_service
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    return dashboard_service.get_summary(db)
