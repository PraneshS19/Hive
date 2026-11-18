from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    asset_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exchange: Mapped[str] = mapped_column(String(20), default="NSE")
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # NSE_OFFICIAL, LOCAL_CSV, YFINANCE, KAGGLE_ARCHIVE
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(20), default="1d")
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    adjustment_status: Mapped[str] = mapped_column(String(30), default="UNADJUSTED")  # ADJUSTED, UNADJUSTED, UNKNOWN
    quality_status: Mapped[str] = mapped_column(String(30), default="VALIDATED")  # VALIDATED, WARNINGS, REJECTED
    validation_report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_info: Mapped[str] = mapped_column(String(200), default="Public educational / research usage")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)
