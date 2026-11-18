from datetime import UTC, datetime

from app.db.base import Base
from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text


class DhanFeedState(Base):
    """
    Real-time feed connection and health status.
    Truthfully records whether live feed is connected, stale, market closed, or unavailable.
    """
    __tablename__ = "dhan_feed_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(50), default="dhanhq", nullable=False)
    connection_status = Column(String(30), default="DISCONNECTED", nullable=False)  # LIVE, STALE, DISCONNECTED, MARKET_CLOSED, UNAVAILABLE
    feed_mode = Column(String(20), default="QUOTE", nullable=False)
    last_connected_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    last_source_timestamp = Column(DateTime, nullable=True)
    last_ingestion_timestamp = Column(DateTime, nullable=True)
    valid_ticks_count = Column(Integer, default=0, nullable=False)
    invalid_ticks_count = Column(Integer, default=0, nullable=False)
    dropped_ticks_count = Column(Integer, default=0, nullable=False)
    active_subscriptions_count = Column(Integer, default=0, nullable=False)
    is_market_session = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class InstrumentRegistryItem(Base):
    """
    Configurable broad market watchlist of 25-50 instruments.
    Maps authoritative security_id, exchange segment, symbol, and subscription status.
    """
    __tablename__ = "instrument_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    security_id = Column(String(50), unique=True, index=True, nullable=False)
    symbol = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=False)
    exchange_segment = Column(String(30), default="NSE_EQ", nullable=False)  # NSE_EQ, NSE_FNO, IDX
    instrument_type = Column(String(30), default="EQUITY", nullable=False)   # EQUITY, INDEX, ETF
    lot_size = Column(Integer, default=1, nullable=False)
    tick_size = Column(Float, default=0.05, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_subscribed = Column(Boolean, default=False, nullable=False)
    subscription_mode = Column(String(20), default="QUOTE", nullable=False)
    last_price = Column(Float, nullable=True)
    last_volume = Column(Integer, default=0, nullable=False)
    last_source_time = Column(DateTime, nullable=True)
    last_ingested_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class MarketTickRecord(Base):
    """
    Batched persistence of normalized market updates for auditing and bar construction.
    """
    __tablename__ = "market_ticks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    security_id = Column(String(50), index=True, nullable=False)
    symbol = Column(String(50), index=True, nullable=False)
    exchange_segment = Column(String(30), default="NSE_EQ", nullable=False)
    ltp = Column(Float, nullable=False)
    volume = Column(Integer, default=0, nullable=False)
    open_price = Column(Float, nullable=True)
    high_price = Column(Float, nullable=True)
    low_price = Column(Float, nullable=True)
    close_price = Column(Float, nullable=True)
    source_timestamp = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True, nullable=False)

    __table_args__ = (
        Index("idx_market_ticks_symbol_time", "symbol", "ingested_at"),
    )


class MarketEventRecord(Base):
    """
    Meaningful market events detected via deterministic rules
    (price surge, volume anomaly, volatility expansion, MA cross, user trigger).
    """
    __tablename__ = "market_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(80), unique=True, index=True, nullable=False)
    event_type = Column(String(50), index=True, nullable=False)  # PRICE_SURGE, VOLUME_SPIKE, VOLATILITY_EXPANSION, MA_CROSSOVER, USER_TRIGGER
    symbol = Column(String(50), index=True, nullable=False)
    security_id = Column(String(50), nullable=True)
    severity = Column(Integer, default=50, nullable=False)  # 0 to 100
    headline = Column(String(255), nullable=False)
    trigger_value = Column(Float, nullable=True)
    baseline_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    event_time = Column(DateTime, default=lambda: datetime.now(UTC), index=True, nullable=False)
    cooldown_until = Column(DateTime, nullable=True)
    status = Column(String(30), default="DETECTED", nullable=False)  # DETECTED, ANALYZING, COMPLETED, DISMISSED
    run_id = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class EvidenceSnapshotRecord(Base):
    """
    Immutable frozen evidence packet constructed at the moment of an event.
    Guarantees time-consistency for subsequent review, replay, and benchmarking.
    """
    __tablename__ = "evidence_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(String(80), unique=True, index=True, nullable=False)
    event_id = Column(String(80), index=True, nullable=True)
    symbol = Column(String(50), index=True, nullable=False)
    security_id = Column(String(50), nullable=True)
    market_source = Column(String(50), default="DHAN_LIVE", nullable=False)
    source_timestamp = Column(DateTime, nullable=True)
    ingestion_timestamp = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    quote_json = Column(Text, nullable=False)          # Price, volume, OHLC, bid/ask
    indicators_json = Column(Text, nullable=False)     # 20/50 SMA, RSI, annualized vol, MACD
    macro_json = Column(Text, nullable=False)          # RBI repo rate, USD/INR, Brent crude
    freshness_status = Column(String(30), default="FRESH", nullable=False)  # FRESH, STALE, HISTORICAL_FROZEN
    historical_context_json = Column(Text, nullable=True)  # Past candles available up to event_time
    provenance_info = Column(Text, nullable=True)      # Detailed source lineage & hash
    is_replay = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True, nullable=False)


class PaperTradeProposal(Base):
    """
    Paper-trading proposal generated from evidence-backed analysis.
    Subject to deterministic risk checks and requires explicit human confirmation.
    """
    __tablename__ = "paper_trade_proposals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(String(80), unique=True, index=True, nullable=False)
    run_id = Column(String(80), index=True, nullable=False)
    event_id = Column(String(80), index=True, nullable=True)
    snapshot_id = Column(String(80), nullable=True)
    symbol = Column(String(50), index=True, nullable=False)
    side = Column(String(10), default="BUY", nullable=False)  # BUY or SELL
    requested_qty = Column(Integer, nullable=False)
    estimated_price = Column(Float, nullable=False)
    estimated_notional = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    risk_check_passed = Column(Boolean, default=False, nullable=False)
    risk_notes = Column(Text, nullable=True)
    status = Column(String(40), default="PENDING_CONFIRMATION", nullable=False)
    # PENDING_CONFIRMATION, CONFIRMED, REJECTED_BY_RISK, EXPIRED, EXECUTED, EXECUTION_FAILED
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    execution_order_id = Column(Integer, nullable=True)
    rejection_reason = Column(Text, nullable=True)
