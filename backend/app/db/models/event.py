from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # SCENARIO, PIPELINE, RISK, ORDER, BACKTEST
    source: Mapped[str] = mapped_column(String(50), default="SYSTEM")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
