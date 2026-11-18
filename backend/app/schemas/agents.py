from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentAnalyzeRequest(BaseModel):
    symbol: str = Field(default="RELIANCE")
    scenario_type: str | None = None
    severity: float | None = None
    custom_headline: str | None = None


class MarketAnalystOutput(BaseModel):
    trend: str  # Bullish, Bearish, Neutral
    momentum: str
    volatility_assessment: str
    key_observations: list[str]
    confidence: float
    indicators_summary: dict[str, Any]


class SentimentAnalystOutput(BaseModel):
    sentiment: str  # Positive, Negative, Neutral, Unverified
    sentiment_score: int  # -100 to +100
    headline_analyzed: str
    source_verification: str  # Verified, Synthetic, Unverified
    confidence: float


class PortfolioManagerOutput(BaseModel):
    action: str  # BUY, SELL, HOLD
    symbol: str
    target_quantity: int
    rationale: str
    evidence_citations: list[str]
    proposed_weight_pct: float
    confidence: float


class AgentRoleCard(BaseModel):
    name: str
    status: str  # Analyzing, Complete, Ready
    value: str  # Bullish, +38 score, HOLD
    text: str
    execution_mode: str  # local_llm, deterministic_fallback
    provider: str | None = "ollama"
    model: str | None = "qwen3.5:4b"
    latency_ms: float | None = None


class AgentRunResponse(BaseModel):
    id: int
    pipeline_run_id: str
    role: str
    status: str
    execution_mode: str
    value: str
    summary: str
    confidence: float
    output: dict[str, Any]
    created_at: datetime
