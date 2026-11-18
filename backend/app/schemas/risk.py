from datetime import datetime

from pydantic import BaseModel, Field


class RiskConfigUpdate(BaseModel):
    fee_pct: float | None = Field(None, ge=0.0, le=5.0)
    max_order_pct: float | None = Field(None, ge=1.0, le=10.0)
    max_allocation_pct: float | None = Field(None, ge=5.0, le=25.0)
    drawdown_halt_pct: float | None = Field(None, ge=1.0, le=10.0)
    auto_execute: bool | None = None


class RiskConfigResponse(BaseModel):
    fee: float  # Alias matching frontend settings object
    maxOrder: float
    maxAllocation: float
    drawdown: float
    auto_execute: bool
    updated_at: datetime


class RuleCheckResult(BaseModel):
    rule_name: str
    passed: bool
    description: str
    measured_value: str | None = None
    limit_value: str | None = None


class RiskDecisionResponse(BaseModel):
    id: int
    order_id: int | None
    outcome: str  # APPROVED, RESIZED, REJECTED
    reason: str
    evaluated_qty: int
    approved_qty: int
    rule_results: list[RuleCheckResult]
    timestamp: datetime
