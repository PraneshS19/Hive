from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StageStatus(BaseModel):
    name: str  # Market Data, Specialist Analysis, Portfolio Proposal, Risk Gate, Simulated Execution
    state: str  # idle, run, done, bad
    summary: str
    details: dict[str, Any] | None = None


class DecisionPipelineRunRequest(BaseModel):
    symbol: str = Field(default="RELIANCE")
    scenario_type: str | None = None
    severity: float | None = None
    auto_execute: bool | None = None


class DecisionPipelineResponse(BaseModel):
    run_id: str
    symbol: str
    scenario_id: int | None = None
    status: str  # completed, rejected, failed
    current_stage: str
    stages: list[StageStatus]
    proposal: dict[str, Any] | None = None
    risk_decision: dict[str, Any] | None = None
    execution_result: dict[str, Any] | None = None
    execution_mode: str = "deterministic_fallback"
    created_at: datetime
    completed_at: datetime | None = None
