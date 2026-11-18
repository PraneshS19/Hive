from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class Asset(Base):
    __tablename__ = "assets"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sector: Mapped[str] = mapped_column(String(50), default="Technology")
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class Quote(Base):
    __tablename__ = "quotes"

    symbol: Mapped[str] = mapped_column(String(10), ForeignKey("assets.symbol"), primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    previous: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    change: Mapped[float] = mapped_column(Float, default=0.0)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=100000.0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    dataset_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, default=None)


class ScenarioRecord(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_type: Mapped[str] = mapped_column(String(50), nullable=False) # CRASH, RALLY, MISLEADING_NEWS, LIQUIDITY_SHOCK
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[float] = mapped_column(Float, default=50.0)
    target_symbol: Mapped[str] = mapped_column(String(10), ForeignKey("assets.symbol"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    outcome: Mapped[str] = mapped_column(String(30), default="APPROVED") # APPROVED, RESIZED, REJECTED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class MarketSnapshotRecord(Base):
    """
    Durable, auditable store of verified market snapshots.
    Preserves verified market observations during market closures, weekends,
    holidays, and provider outages without resorting to synthetic fabrication.
    """
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(30), default="NSE", nullable=False)
    exchange_segment: Mapped[str] = mapped_column(String(30), default="NSE_EQ", nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    previous_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    observation_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    receipt_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    price_type: Mapped[str] = mapped_column(String(50), default="LAST_OBSERVED_PRICE", nullable=False)  # LIVE_QUOTE, OFFICIAL_SESSION_CLOSE, LAST_OBSERVED_PRICE
    market_status: Mapped[str] = mapped_column(String(30), default="CLOSED", nullable=False)  # OPEN, CLOSED, WEEKEND, HOLIDAY, PRE_OPEN, POST_CLOSE
    feed_status: Mapped[str] = mapped_column(String(30), default="MARKET_CLOSED", nullable=False)  # LIVE, MARKET_CLOSED, STALE, CONNECTED_WAITING_FOR_DATA, DATA_UNAVAILABLE, PROVIDER_ERROR
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
