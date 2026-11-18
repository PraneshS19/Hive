from pydantic import BaseModel


class PositionResponse(BaseModel):
    symbol: str
    name: str
    qty: int  # matching frontend Position type
    average: float  # matching frontend Position type
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    allocation_pct: float | None = None
    valuation_status: str = "LIVE_VALUED"


class PortfolioEquityHistoryPoint(BaseModel):
    time: str
    price: float
    equity: float


class PortfolioMetrics(BaseModel):
    equity: float
    cash: float
    invested: float | None = 0.0
    unrealized_pnl: float | None = 0.0
    realized_pnl: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    risk_status: str = "Guarded"
    valuation_complete: bool = True
    valuation_note: str | None = None


class PortfolioResponse(BaseModel):
    equity: float
    cash: float
    invested: float | None = 0.0
    currency: str = "INR"
    positions: list[PositionResponse]
    metrics: PortfolioMetrics
    history: list[PortfolioEquityHistoryPoint]
    valuation_complete: bool = True
    valuation_note: str | None = None
