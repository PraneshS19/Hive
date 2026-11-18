from app.api.dependencies import get_db
from app.api.routes.risk import get_risk_config, update_risk_config
from app.core.security import require_operator
from app.schemas.risk import RiskConfigResponse, RiskConfigUpdate
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/settings", response_model=RiskConfigResponse)
def get_settings(db: Session = Depends(get_db)):
    return get_risk_config(db)


@router.put("/settings", response_model=RiskConfigResponse, dependencies=[Depends(require_operator)])
def update_settings(payload: RiskConfigUpdate, db: Session = Depends(get_db)):
    return update_risk_config(payload, db)
