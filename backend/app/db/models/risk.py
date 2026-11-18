from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class RiskConfig(Base):
    __tablename__ = "risk_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fee_pct: Mapped[float] = mapped_column(Float, default=0.1)
    max_order_pct: Mapped[float] = mapped_column(Float, default=10.0)
    max_allocation_pct: Mapped[float] = mapped_column(Float, default=25.0)
    drawdown_halt_pct: Mapped[float] = mapped_column(Float, default=10.0)
    auto_execute: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)


class RiskDecision(Base):
    __tablename__ = "risk_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # APPROVED, RESIZED, REJECTED
    reason: Mapped[str] = mapped_column(Text, default="")
    evaluated_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_results_json: Mapped[str] = mapped_column(Text, default="[]")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
