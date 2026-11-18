from datetime import datetime

from pydantic import BaseModel, Field


class ScenarioInjectRequest(BaseModel):
    scenario: str = Field(..., description="VOLATILITY_SURGE, RISK_OFF_PULLBACK, UNVERIFIED_RUMOR, or LIQUIDITY_SQUEEZE (also accepts CRASH, RALLY, MISLEADING_NEWS, LIQUIDITY_SHOCK)")
    symbol: str = Field(default="RELIANCE")
    severity: float = Field(default=60.0, ge=10.0, le=100.0)


class ScenarioResponse(BaseModel):
    id: int
    type: str
    severity: float
    headline: str
    time: str
    outcome: str
    target_symbol: str
    created_at: datetime


class ScenarioRunResult(BaseModel):
    scenario_id: int
    scenario_type: str
    symbol: str
    severity: float
    prior_price: float
    new_price: float
    price_change_pct: float
    headline: str
    status: str
    outcome: str
    order_id: int | None = None
    order_status: str | None = None
    reason: str
    time: str
    is_simulated: bool = Field(default=True, description="Strictly True: marks an isolated simulation run.")
    simulation_label: str = Field(default="SIMULATED SCENARIO · ISOLATED FROM LIVE DATA")
