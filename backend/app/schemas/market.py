from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    sector: str
    currency: str
    is_active: bool


class QuoteHistoryPoint(BaseModel):
    time: str
    price: float
    equity: float


class QuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    price: float | None = None
    previous: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    history: list[QuoteHistoryPoint] = []
    timestamp: datetime | None = None
    exchange: str = "NSE"
    exchange_segment: str | None = "NSE_EQ"
    security_id: str | None = None
    freshness_status: str = "WAITING_FOR_FIRST_TICK"
    is_live: bool = False
    source: str = "DHAN_CATALOG_PENDING"
    provenance: str = "Registered instrument awaiting live DhanHQ tick"
    price_type: str | None = "LIVE_QUOTE"
    market_status: str | None = "OPEN"
    feed_status: str | None = "LIVE"
    observation_timestamp: str | None = None
    observation_age_seconds: float | None = None
    last_completed_session_date: str | None = None
    session_note: str | None = None
    timezone: str | None = "Asia/Kolkata"


class MarketStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_market_session: bool
    market_status: str
    trading_day_status: str
    session_start_ist: str = "09:15:00"
    session_end_ist: str = "15:30:00"
    timezone: str = "Asia/Kolkata"
    feed_health: str
    feed_status: str
    last_completed_session_date: str | None = None
    active_data_source: str
    session_note: str
    description: str | None = None


class CandleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    volume_semantics: str | None = None
    volume_diagnostic: str | None = None
    is_synthetic: bool = False
    candle_type: str | None = "REGULAR"
    exchange: str = "NSE"
    dataset_id: str | None = None


class TechnicalIndicators(BaseModel):
    symbol: str
    status: str = "WARMING_UP"
    observations_count: int = 0
    required_observations: int = 20
    sma_20: float | None = None
    ema_20: float | None = None
    rsi_14: float | None = None
    volatility: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
