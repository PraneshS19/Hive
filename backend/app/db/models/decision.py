from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class DecisionPipelineRun(Base):
    __tablename__ = "decision_pipeline_runs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # UUID or run timestamp
    scenario_id: Mapped[int] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="completed")  # running, completed, rejected, failed
    current_stage: Mapped[str] = mapped_column(String(50), default="Simulated Execution")
    stages_json: Mapped[str] = mapped_column(Text, default="[]")  # List of stage statuses & evidence
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
