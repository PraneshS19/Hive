"""
SYNQ — Market Snapshot Persistence & Retrieval Store
Durable SQLite storage for genuine verified market observations.
Ensures prices remain transparently available during market closures, weekends,
exchange holidays, and provider interruptions without fabricating data.
"""

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import logger
from app.db.models import MarketSnapshotRecord, Quote
from app.db.session import SessionLocal
from app.market.session_calendar import (
    get_market_session_info,
)


def validate_market_observation(
    arg1: Any = None,
    arg2: Any = None,
    prev_close: float | None = None,
    **kwargs
) -> tuple[bool, str]:
    """
    Strict validation for market prices.
    Rejects None, non-numeric, <= 0, infinite, NaN, or extreme outlier values.
    Supports flexible argument order: (symbol, price) or (price, symbol).
    """
    if isinstance(arg1, str) and not isinstance(arg2, str):
        symbol = arg1
        price = arg2
    elif isinstance(arg2, str) and not isinstance(arg1, str):
        symbol = arg2
        price = arg1
    else:
        symbol = str(kwargs.get("symbol", arg1 or ""))
        price = kwargs.get("price", arg2 if arg2 is not None else arg1)

    if price is None:
        return False, f"Price for {symbol} is None."
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return False, f"Price for {symbol} is not numeric ({type(price).__name__})."
    if math.isnan(price) or math.isinf(price):
        return False, f"Price for {symbol} is NaN or Inf."
    if price <= 0:
        return False, f"Price for {symbol} must be strictly positive (got {price})."

    # Sanity outlier filter
    p_float = float(price)
    if prev_close is not None and prev_close > 0 and (p_float > prev_close * 5.0 or p_float < prev_close * 0.1):
        return False, f"Price {price} is an extreme outlier compared to previous close {prev_close}."

    return True, "Valid positive market price."


class MarketSnapshotStore:
    """
    Manages durable persistence and retrieval of validated market snapshots.
    """

    @staticmethod
    def persist_snapshot(
        symbol: str,
        price: float,
        observation_timestamp: datetime | None = None,
        source: str = "0XRAMM_REST_V3",
        provenance: str = "Verified market observation",
        price_type: str = "LAST_OBSERVED_PRICE",
        previous_close: float | None = None,
        change: float | None = None,
        change_pct: float | None = None,
        volume: float | None = None,
        open_price: float | None = None,
        high_price: float | None = None,
        low_price: float | None = None,
        close_price: float | None = None,
        exchange: str = "NSE",
        exchange_segment: str = "NSE_EQ",
        market_status: str | None = None,
        feed_status: str | None = None,
        db: Session | None = None,
        **kwargs
    ) -> MarketSnapshotRecord | None:
        """
        Persists a verified market snapshot to SQLite.
        Strictly rejects invalid or corrupt prices to protect historical integrity.
        """
        is_valid, reason = validate_market_observation(price, symbol, prev_close=previous_close)
        if not is_valid:
            logger.warning(f"Rejected invalid market snapshot for {symbol}: {reason}")
            return None

        now_utc = datetime.now(UTC)
        obs_time = observation_timestamp or now_utc
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=UTC)

        session_info = get_market_session_info(obs_time)
        resolved_mkt_status = market_status or session_info["market_status"]
        is_open = session_info["is_open"]
        resolved_feed_status = feed_status or ("LIVE" if is_open else "MARKET_CLOSED")

        open_val = open_price if open_price is not None else kwargs.get("open_p")
        high_val = high_price if high_price is not None else kwargs.get("high_p")
        low_val = low_price if low_price is not None else kwargs.get("low_p")
        close_val = close_price if close_price is not None else kwargs.get("close_p")

        # Refine price_type if not explicitly set
        if price_type == "LAST_OBSERVED_PRICE":
            if is_open:
                price_type = "LIVE_QUOTE"
            elif close_val is not None and close_val > 0 and price == close_val:
                price_type = "OFFICIAL_SESSION_CLOSE"

        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            snapshot = MarketSnapshotRecord(
                symbol=symbol.upper(),
                exchange=exchange,
                exchange_segment=exchange_segment,
                price=float(price),
                previous_close=float(previous_close) if previous_close is not None else None,
                change=float(change) if change is not None else None,
                change_pct=float(change_pct) if change_pct is not None else None,
                volume=float(volume) if volume is not None else None,
                open_price=float(open_val) if open_val is not None else None,
                high_price=float(high_val) if high_val is not None else None,
                low_price=float(low_val) if low_val is not None else None,
                close_price=float(close_val) if close_val is not None else None,
                observation_timestamp=obs_time,
                receipt_timestamp=now_utc,
                source=source,
                provenance=provenance,
                price_type=price_type,
                market_status=resolved_mkt_status,
                feed_status=resolved_feed_status,
                is_valid=True,
                validation_notes=reason,
                created_at=now_utc,
            )
            db.add(snapshot)

            # Synchronize quotes table
            q_rec = db.query(Quote).filter(Quote.symbol == symbol.upper()).first()
            prev_val = previous_close
            if prev_val is None and change is not None:
                prev_val = round(float(price - change), 2)

            if q_rec:
                q_rec.price = float(price)
                if volume is not None and volume > 0:
                    q_rec.volume = float(volume)
                if change is not None:
                    q_rec.change = float(change)
                if change_pct is not None:
                    q_rec.change_pct = float(change_pct)
                if prev_val is not None:
                    q_rec.previous = float(prev_val)
                q_rec.timestamp = obs_time
                if hasattr(q_rec, "price_type"):
                    q_rec.price_type = price_type
                if hasattr(q_rec, "observation_timestamp"):
                    q_rec.observation_timestamp = obs_time
                if hasattr(q_rec, "source"):
                    q_rec.source = source
                if hasattr(q_rec, "freshness_status"):
                    q_rec.freshness_status = feed_status
                if hasattr(q_rec, "market_status"):
                    q_rec.market_status = market_status
            else:
                new_q = Quote(
                    symbol=symbol.upper(),
                    price=float(price),
                    previous=float(prev_val) if prev_val is not None else 0.0,
                    change=float(change) if change is not None else 0.0,
                    change_pct=float(change_pct) if change_pct is not None else 0.0,
                    volume=float(volume) if volume is not None else 0.0,
                    timestamp=obs_time,
                )
                if hasattr(new_q, "price_type"):
                    new_q.price_type = price_type
                if hasattr(new_q, "observation_timestamp"):
                    new_q.observation_timestamp = obs_time
                if hasattr(new_q, "source"):
                    new_q.source = source
                if hasattr(new_q, "freshness_status"):
                    new_q.freshness_status = feed_status
                if hasattr(new_q, "market_status"):
                    new_q.market_status = market_status
                db.add(new_q)

            db.commit()
            return snapshot
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Failed to persist market snapshot for {symbol}: {e}")
            return None
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_latest_snapshot(symbol: str, db: Session | None = None) -> dict[str, Any] | None:
        """
        Retrieves the latest verified snapshot for a symbol.
        Falls back to quotes table if no market_snapshots row exists.
        Safely returns None if tables do not exist (e.g. in test setup).
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            try:
                sym = symbol.upper()
                rec = (
                    db.query(MarketSnapshotRecord)
                    .filter(MarketSnapshotRecord.symbol == sym, MarketSnapshotRecord.is_valid == True)
                    .order_by(desc(MarketSnapshotRecord.observation_timestamp))
                    .first()
                )
                if rec:
                    return {
                        "symbol": rec.symbol,
                        "price": rec.price,
                        "previous": rec.previous_close,
                        "change": rec.change,
                        "change_pct": rec.change_pct,
                        "volume": rec.volume,
                        "open": rec.open_price,
                        "high": rec.high_price,
                        "low": rec.low_price,
                        "close": rec.close_price,
                        "observation_timestamp": rec.observation_timestamp.isoformat() if rec.observation_timestamp else None,
                        "receipt_timestamp": rec.receipt_timestamp.isoformat() if rec.receipt_timestamp else None,
                        "source": rec.source,
                        "provenance": rec.provenance,
                        "price_type": rec.price_type,
                        "market_status": rec.market_status,
                        "feed_status": rec.feed_status,
                        "exchange": rec.exchange,
                        "exchange_segment": rec.exchange_segment,
                    }

                # Fallback to Quote table
                q = db.query(Quote).filter(Quote.symbol == sym).first()
                if q and q.price is not None and q.price > 0:
                    obs_ts = getattr(q, "observation_timestamp", None) or q.timestamp
                    return {
                        "symbol": q.symbol,
                        "price": q.price,
                        "previous": q.previous,
                        "change": q.change,
                        "change_pct": q.change_pct,
                        "volume": q.volume,
                        "open": None,
                        "high": None,
                        "low": None,
                        "close": q.previous,
                        "observation_timestamp": obs_ts.isoformat() if obs_ts else None,
                        "receipt_timestamp": q.timestamp.isoformat() if q.timestamp else None,
                        "source": getattr(q, "source", "SQLITE_QUOTES_STORE"),
                        "provenance": "Persisted quote record from previous verified session",
                        "price_type": getattr(q, "price_type", "LAST_OBSERVED_PRICE"),
                        "market_status": getattr(q, "market_status", "CLOSED"),
                        "feed_status": getattr(q, "freshness_status", "MARKET_CLOSED"),
                        "exchange": "NSE",
                        "exchange_segment": "NSE_EQ",
                    }
                return None
            except (SQLAlchemyError, TypeError, ValueError) as e:
                logger.debug(f"Could not load snapshot for {symbol}: {e}")
                return None
        finally:
            if close_db:
                db.close()

    @staticmethod
    def get_all_latest_snapshots(db: Session | None = None) -> dict[str, dict[str, Any]]:
        """
        Retrieves the latest verified snapshot for all known instruments.
        Safely returns empty dict if tables do not exist.
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            results: dict[str, dict[str, Any]] = {}
            try:
                # First, load from quotes table as baseline
                quotes = db.query(Quote).all()
                for q in quotes:
                    if q.price is not None and q.price > 0:
                        obs_ts = getattr(q, "observation_timestamp", None) or q.timestamp
                        results[q.symbol] = {
                            "symbol": q.symbol,
                            "price": q.price,
                            "previous": q.previous,
                            "change": q.change,
                            "change_pct": q.change_pct,
                            "volume": q.volume,
                            "open": None,
                            "high": None,
                            "low": None,
                            "close": q.previous,
                            "observation_timestamp": obs_ts.isoformat() if obs_ts else None,
                            "receipt_timestamp": q.timestamp.isoformat() if q.timestamp else None,
                            "source": getattr(q, "source", "SQLITE_QUOTES_STORE"),
                            "provenance": "Persisted quote record from previous verified session",
                            "price_type": getattr(q, "price_type", "LAST_OBSERVED_PRICE"),
                            "market_status": getattr(q, "market_status", "CLOSED"),
                            "feed_status": getattr(q, "freshness_status", "MARKET_CLOSED"),
                            "exchange": "NSE",
                            "exchange_segment": "NSE_EQ",
                        }

                # Then overlay with any strictly newer records from market_snapshots
                snapshots = (
                    db.query(MarketSnapshotRecord)
                    .filter(MarketSnapshotRecord.is_valid == True)
                    .order_by(desc(MarketSnapshotRecord.observation_timestamp))
                    .all()
                )
                seen_symbols = set()
                for s in snapshots:
                    if s.symbol not in seen_symbols:
                        seen_symbols.add(s.symbol)
                        results[s.symbol] = {
                            "symbol": s.symbol,
                            "price": s.price,
                            "previous": s.previous_close,
                            "change": s.change,
                            "change_pct": s.change_pct,
                            "volume": s.volume,
                            "open": s.open_price,
                            "high": s.high_price,
                            "low": s.low_price,
                            "close": s.close_price,
                            "observation_timestamp": s.observation_timestamp.isoformat() if s.observation_timestamp else None,
                            "receipt_timestamp": s.receipt_timestamp.isoformat() if s.receipt_timestamp else None,
                            "source": s.source,
                            "provenance": s.provenance,
                            "price_type": s.price_type,
                            "market_status": s.market_status,
                            "feed_status": s.feed_status,
                            "exchange": s.exchange,
                            "exchange_segment": s.exchange_segment,
                        }
                return results
            except (SQLAlchemyError, TypeError, ValueError) as e:
                logger.debug(f"Could not load all snapshots: {e}")
                return results
        finally:
            if close_db:
                db.close()


snapshot_store = MarketSnapshotStore()


def persist_snapshot(*args, **kwargs):
    return snapshot_store.persist_snapshot(*args, **kwargs)


def get_latest_snapshot(symbol: str, db: Session | None = None):
    return snapshot_store.get_latest_snapshot(symbol, db)


def get_all_latest_snapshots(db: Session | None = None):
    return snapshot_store.get_all_latest_snapshots(db)
