from datetime import UTC, datetime

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models import Asset, Candle
from app.market.dhan_adapter import dhan_live_feed
from app.market.session_calendar import (
    get_last_completed_trading_session_date,
    get_market_session_info,
    is_market_session_active,
)
from app.schemas.market import (
    AssetResponse,
    CandleResponse,
    MarketStatusResponse,
    QuoteResponse,
    TechnicalIndicators,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/market/assets", response_model=list[AssetResponse])
def get_assets(db: Session = Depends(get_db)):
    """Return registered reference metadata for the 30-instrument NSE catalog."""
    return db.query(Asset).filter(Asset.is_active == True).all()


@router.get("/market/status", response_model=MarketStatusResponse)
def get_market_status():
    """
    Authoritative exchange session and feed health status.
    Clearly distinguishes exchange session status from feed provider health.
    """
    now_utc = datetime.now(UTC)
    is_open, session_msg = is_market_session_active(now_utc)
    session_info = get_market_session_info(now_utc)
    feed_stat = dhan_live_feed.get_status()

    market_state = "OPEN" if is_open else ("WEEKEND" if session_info.get("is_weekend") else ("HOLIDAY" if session_info.get("is_holiday") else "CLOSED"))
    feed_health = feed_stat.get("feed_status", feed_stat.get("status", "UNKNOWN"))

    return MarketStatusResponse(
        is_market_session=is_open,
        market_status=market_state,
        trading_day_status=session_info.get("trading_day_status", market_state),
        session_start_ist=session_info.get("session_start_ist", "09:15:00"),
        session_end_ist=session_info.get("session_end_ist", "15:30:00"),
        timezone="Asia/Kolkata",
        feed_health=feed_health,
        feed_status=feed_health,
        last_completed_session_date=get_last_completed_trading_session_date(now_utc),
        active_data_source=feed_stat.get("provider", "0xramm_yahoo_rest"),
        session_note=session_msg,
        description=feed_stat.get("description", session_msg)
    )


@router.get("/market/quotes", response_model=list[QuoteResponse])
def get_quotes():
    """
    Authoritative market quotes.
    When exchange is open: returns live quotes.
    When exchange is closed: returns verified last available market observations with clear timestamps.
    """
    return dhan_live_feed.get_watchlist()


@router.get("/market/quotes/{symbol}", response_model=QuoteResponse)
def get_quote_by_symbol(symbol: str):
    """
    Authoritative single-instrument quote with complete provenance and observation metadata.
    """
    q = dhan_live_feed.get_quote(symbol)
    if not q:
        raise HTTPException(
            status_code=404,
            detail=f"Asset '{symbol}' not found in registered 30-instrument catalog."
        )
    return q


@router.get("/market/candles", response_model=list[CandleResponse])
def get_candles(
    response: Response,
    symbol: str = Query(default="RELIANCE"),
    bars: int = Query(default=60, ge=1, le=500),
    interval_minutes: int = Query(default=5, ge=1, le=60),
    db: Session = Depends(get_db)
):
    """
    Market candles endpoint.
    When live session bars are available, returns POLLING_DERIVED_APPROXIMATION candles.
    Historical daily bars are available as an explicitly enabled, separate fallback.
    """
    sym = symbol.upper()
    is_open, _ = is_market_session_active()

    # 1. Live session: only return live-aggregated session candles if market is actively open AND has at least 3 bars
    if is_open and hasattr(dhan_live_feed, "get_aggregated_candles"):
        candles = dhan_live_feed.get_aggregated_candles(sym, interval_minutes=interval_minutes, limit=bars)
        if candles and len(candles) >= 3:
            response.headers["X-Candle-Type"] = "POLLING_DERIVED_APPROXIMATION"
            response.headers["X-Data-Status"] = "Polling-derived sampled candles (not exchange-grade streaming bars)."
            response.headers["X-Market-Mode"] = "LIVE_ONLY"
            return [
                CandleResponse(
                    symbol=c["symbol"],
                    timestamp=datetime.fromisoformat(c["timestamp"]) if isinstance(c["timestamp"], str) else c["timestamp"],
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c.get("volume"),
                    volume_semantics=c.get("volume_semantics"),
                    volume_diagnostic=c.get("volume_diagnostic"),
                    is_synthetic=False,
                    candle_type="POLLING_DERIVED_APPROXIMATION",
                    exchange="NSE"
                )
                for c in candles
            ]

    # 2. Market closed or live session bars unavailable: serve verified historical daily bars from database
    db_candles = []
    if settings.MARKET_DATA_ALLOW_HISTORICAL_FALLBACK:
        db_candles = db.query(Candle).filter(
            Candle.symbol == sym, Candle.is_synthetic.is_(False),
        ).order_by(Candle.timestamp.desc()).limit(bars).all()
    if db_candles:
        response.headers["X-Candle-Type"] = "HISTORICAL_DAILY_BAR"
        response.headers["X-Data-Status"] = "Displaying historical daily bars."
        response.headers["X-Market-Mode"] = "HISTORICAL_FALLBACK"
        ordered = list(reversed(db_candles))
        return [
            CandleResponse(
                symbol=c.symbol,
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                volume_semantics="DAILY_SESSION_VOLUME",
                volume_diagnostic="VERIFIED_NSE_DAILY_BAR",
                is_synthetic=False,
                candle_type="HISTORICAL_DAILY_BAR",
                exchange="NSE",
                dataset_id=c.dataset_id or "NSE_HISTORICAL_DAILY"
            )
            for c in ordered
        ]

    response.headers["X-Market-Mode"] = "LIVE_ONLY"
    response.headers["X-Data-Status"] = "No market data or historical bars available for symbol."
    return []


@router.get("/market/indicators", response_model=TechnicalIndicators)
def get_indicators(symbol: str = Query(default="RELIANCE")):
    """
    Technical indicators endpoint.
    In LIVE_ONLY mode: calculated strictly from live-observed ticks during the current session.
    Returns WARMING_UP if fewer than 20 live observations have been captured.
    """
    sym = symbol.upper()
    live_ticks = dhan_live_feed.get_live_ticks(sym)

    if len(live_ticks) >= 20:
        import numpy as np
        return TechnicalIndicators(
            symbol=sym,
            status="CALCULATED_FROM_LIVE_SESSION",
            observations_count=len(live_ticks),
            required_observations=20,
            sma_20=round(float(np.mean(live_ticks[-20:])), 2),
            sma_50=round(float(np.mean(live_ticks[-50:])), 2) if len(live_ticks) >= 50 else None,
        )
    else:
        return TechnicalIndicators(
            symbol=sym,
            status="WARMING_UP",
            observations_count=len(live_ticks),
            required_observations=20,
        )
