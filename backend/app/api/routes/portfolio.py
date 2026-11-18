
from app.api.dependencies import get_db
from app.core.security import require_operator
from app.db.init_db import reset_simulation
from app.portfolio.service import portfolio_service
from app.schemas.portfolio import PortfolioMetrics, PortfolioResponse, PositionResponse
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(db: Session = Depends(get_db)):
    return portfolio_service.get_portfolio_summary(db)


@router.get("/portfolio/positions", response_model=list[PositionResponse])
def get_positions(db: Session = Depends(get_db)):
    summary = portfolio_service.get_portfolio_summary(db)
    return summary["positions"]


@router.get("/portfolio/metrics", response_model=PortfolioMetrics)
def get_metrics(db: Session = Depends(get_db)):
    summary = portfolio_service.get_portfolio_summary(db)
    return summary["metrics"]


@router.post("/portfolio/reset", dependencies=[Depends(require_operator)])
def reset_portfolio_and_simulation(db: Session = Depends(get_db)):
    """Reset all simulation holdings, orders, and equity to baseline."""
    reset_simulation(db)
    return {"success": True, "message": "Simulation reset successfully."}
