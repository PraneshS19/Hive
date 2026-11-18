from app.schemas.agents import AgentRoleCard
from app.schemas.market import QuoteResponse
from app.schemas.portfolio import PortfolioEquityHistoryPoint, PortfolioMetrics
from app.schemas.scenarios import ScenarioResponse
from pydantic import BaseModel


class DashboardSummary(BaseModel):
    metrics: PortfolioMetrics
    equity_curve: list[PortfolioEquityHistoryPoint]
    watchlist: list[QuoteResponse]
    agents: list[AgentRoleCard]
    recent_activity: list[ScenarioResponse]
    running: bool = False
