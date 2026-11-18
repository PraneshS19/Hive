from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_run_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # Market Analyst, Sentiment Analyst, Portfolio Manager
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED")  # ANALYZING, COMPLETED, FAILED
    execution_mode: Mapped[str] = mapped_column(String(30), default="deterministic_fallback")  # local_llm, deterministic_fallback
    value: Mapped[str] = mapped_column(String(100), default="")  # e.g. "Bullish", "+38 score", "BUY 50 RELIANCE"
    summary: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.85)
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
