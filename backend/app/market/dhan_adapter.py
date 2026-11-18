"""
SYNQ — DhanHQ-py Live Market Data Ingestion Adapter
Exclusively responsible for live market-data feed ingestion via DhanHQ-py.
Zero brokerage or order-execution operations are permitted in this module.
"""

import threading
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import logger
from app.db.models import MarketTickRecord, Quote
from app.db.session import SessionLocal

# Indian Standard Time (IST) Offset & Official Exchange Calendar Service
from app.market.session_calendar import (
    IST_OFFSET,
    NSE_HOLIDAYS_2026,
    NSE_WEEKEND_HOLIDAYS_2026,
    SPECIAL_TRADING_SESSIONS_2026,
    get_last_completed_trading_session_date,
    get_market_session_info,
    is_market_session_active,
)
from app.market.snapshot_store import (
    get_all_latest_snapshots,
    get_latest_snapshot,
    persist_snapshot,
    validate_market_observation,
)

__all__ = [
    "INITIAL_INSTRUMENT_CATALOG", "IST_OFFSET", "NSE_HOLIDAYS_2026", "NSE_WEEKEND_HOLIDAYS_2026",
    "SPECIAL_TRADING_SESSIONS_2026",
    "DhanLiveFeedAdapter", "dhan_live_feed", "get_last_completed_trading_session_date",
    "get_market_session_info", "is_market_session_active", "raw_dhan_live_feed",
]

# Authoritative Initial Broad Watchlist: 30 Major NSE Listed Equities & Benchmark Index
INITIAL_INSTRUMENT_CATALOG = [
    {"security_id": "2885", "symbol": "RELIANCE", "name": "Reliance Industries Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "11536", "symbol": "TCS", "name": "Tata Consultancy Services Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "1594", "symbol": "INFY", "name": "Infosys Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "1333", "symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "4963", "symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "3045", "symbol": "SBIN", "name": "State Bank of India", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "10604", "symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "1660", "symbol": "ITC", "name": "ITC Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "11483", "symbol": "LT", "name": "Larsen & Toubro Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "1922", "symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "5900", "symbol": "AXISBANK", "name": "Axis Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "1394", "symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "317", "symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "10999", "symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "3456", "symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "3351", "symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "3506", "symbol": "TITAN", "name": "Titan Company Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "11532", "symbol": "ULTRACEMCO", "name": "UltraTech Cement Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "3787", "symbol": "WIPRO", "name": "Wipro Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "11630", "symbol": "NTPC", "name": "NTPC Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "14977", "symbol": "POWERGRID", "name": "Power Grid Corporation of India Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "2475", "symbol": "ONGC", "name": "Oil & Natural Gas Corporation Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "3499", "symbol": "TATASTEEL", "name": "Tata Steel Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "2031", "symbol": "M&M", "name": "Mahindra & Mahindra Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "236", "symbol": "ASIANPAINT", "name": "Asian Paints Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "7229", "symbol": "HCLTECH", "name": "HCL Technologies Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "25", "symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "16675", "symbol": "BAJAJFINSV", "name": "Bajaj Finserv Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "20374", "symbol": "COALINDIA", "name": "Coal India Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY"},
    {"security_id": "13", "symbol": "NIFTY50", "name": "NIFTY 50 Benchmark Index", "exchange_segment": "IDX", "segment_code": 0, "type": "INDEX"}
]


class DhanLiveFeedAdapter:
    """
    High-performance, non-blocking adapter managing the DhanHQ-py MarketFeed connection.
    Decouples raw WebSocket ingestion from downstream deterministic event detection and AI analysis.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._batch_thread: threading.Thread | None = None
        self._market_feed_instance = None
        self._tick_buffer: list[dict[str, Any]] = []

        # In-memory quote cache: symbol -> quote dict
        self._cache: dict[str, dict[str, Any]] = {}
        # Security ID lookup maps
        self._sec_to_symbol: dict[str, str] = {}
        self._symbol_to_sec: dict[str, str] = {}
        self._catalog_map: dict[str, dict[str, Any]] = {}

        # Connection Telemetry
        self.connection_status = "DISCONNECTED"  # LIVE, STALE, DISCONNECTED, MARKET_CLOSED, UNAVAILABLE
        self.last_connected_at: datetime | None = None
        self.last_source_timestamp: datetime | None = None
        self.last_ingestion_timestamp: datetime | None = None
        self.valid_ticks_count = 0
        self.invalid_ticks_count = 0
        self.dropped_ticks_count = 0
        self.error_message: str | None = None
        self.reconnect_attempts = 0

        # Event detector callback
        self._event_callback = None
        self._live_ticks: dict[str, list[float]] = {}

        self._initialize_catalog()

    def reset_cache(self):
        """Reset live quote cache and live ticks for testing and controlled reset."""
        with self.lock:
            self._live_ticks.clear()
            self._initialize_catalog()

    def _initialize_catalog(self):
        """Build in-memory fast lookups and hydrate from persistent snapshots."""
        is_open, _session_msg = is_market_session_active()
        initial_freshness = "WAITING_FOR_FIRST_TICK" if is_open else "MARKET_CLOSED"

        try:
            snapshots = get_all_latest_snapshots()
        except SQLAlchemyError as e:
            logger.debug(f"Could not load snapshots during Dhan catalog init: {e}")
            snapshots = {}

        for item in INITIAL_INSTRUMENT_CATALOG:
            sec_id = item["security_id"]
            sym = item["symbol"]
            self._sec_to_symbol[sec_id] = sym
            self._symbol_to_sec[sym] = sec_id
            self._catalog_map[sym] = item
            self._live_ticks[sym] = []

            snap = snapshots.get(sym)
            if snap and snap.get("price") is not None and snap["price"] > 0:
                p = float(snap["price"])
                prev = float(snap["previous_close"]) if snap.get("previous_close") is not None else None
                close_p = float(snap["close"]) if snap.get("close") is not None else prev
                change = round(p - prev, 2) if prev and prev > 0 else 0.0
                change_pct = round((change / prev) * 100.0, 2) if prev and prev > 0 else 0.0

                self._cache[sym] = {
                    "symbol": sym,
                    "security_id": sec_id,
                    "name": item["name"],
                    "exchange_segment": item["exchange_segment"],
                    "price": p,
                    "previous": prev,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": snap.get("volume"),
                    "open": snap.get("open"),
                    "high": snap.get("high"),
                    "low": snap.get("low"),
                    "close": close_p,
                    "source": snap.get("source") or "DHAN_SNAPSHOT",
                    "provenance": snap.get("provenance") or "Verified persistent snapshot from previous session",
                    "source_timestamp": snap.get("observation_timestamp"),
                    "ingestion_timestamp": snap.get("observation_timestamp"),
                    "observation_timestamp": snap.get("observation_timestamp"),
                    "is_live": False,
                    "price_type": snap.get("price_type") or ("LAST_SESSION_CLOSE" if not is_open else "LIVE_QUOTE"),
                    "market_status": "OPEN" if is_open else "CLOSED",
                    "feed_status": "MARKET_CLOSED" if not is_open else "CONNECTED_WAITING_FOR_DATA",
                    "freshness_status": initial_freshness,
                    "mode": "LIVE_ONLY",
                    "packet_type": None
                }
            else:
                self._cache[sym] = {
                    "symbol": sym,
                    "security_id": sec_id,
                    "name": item["name"],
                    "exchange_segment": item["exchange_segment"],
                    "price": None,
                    "previous": None,
                    "change": None,
                    "change_pct": None,
                    "volume": None,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "source": "DHAN_CATALOG_PENDING",
                    "provenance": f"DhanHQ-py registered ({item['exchange_segment']}) — awaiting verified live tick",
                    "source_timestamp": None,
                    "ingestion_timestamp": None,
                    "observation_timestamp": None,
                    "is_live": False,
                    "price_type": "NONE",
                    "market_status": "OPEN" if is_open else "CLOSED",
                    "feed_status": initial_freshness,
                    "freshness_status": initial_freshness,
                    "mode": "LIVE_ONLY",
                    "packet_type": None
                }

    def register_event_listener(self, callback):
        """Attach deterministic event detector to incoming normalized ticks."""
        self._event_callback = callback

    def get_status(self) -> dict[str, Any]:
        """
        Truthful, unembellished feed status reporting.
        """
        with self.lock:
            now_utc = datetime.now(UTC)
            is_open, session_msg = is_market_session_active(now_utc)
            session_info = get_market_session_info(now_utc)
            market_state = "OPEN" if is_open else ("WEEKEND" if session_info.get("is_weekend") else ("HOLIDAY" if session_info.get("is_holiday") else "CLOSED"))

            effective_status = self.connection_status

            if not getattr(settings, "DHAN_FEED_ENABLED", False):
                effective_status = "UNAVAILABLE"
                status_desc = "Dhan live feed disabled in configuration (LIVE_ONLY mode: awaiting DHAN_FEED_ENABLED=True)."
            elif not getattr(settings, "DHAN_CLIENT_ID", "") or not getattr(settings, "DHAN_ACCESS_TOKEN", ""):
                effective_status = "UNCONFIGURED"
                status_desc = "Dhan credentials not configured. Configure DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in backend."
            elif not is_open:
                effective_status = "MARKET_CLOSED"
                status_desc = session_msg
            elif self.last_ingestion_timestamp:
                age = (now_utc - self.last_ingestion_timestamp).total_seconds()
                if age > getattr(settings, "DHAN_STALENESS_THRESHOLD_SECONDS", 15.0):
                    effective_status = "STALE"
                    status_desc = f"Feed connected but updates stale ({age:.1f}s since last tick)."
                else:
                    effective_status = "LIVE"
                    status_desc = "Live WebSocket feed connected and streaming ticks."
            else:
                effective_status = "CONNECTING"
                status_desc = "Connecting to DhanHQ MarketFeed WebSocket..."

            return {
                "provider": "DhanHQ-py (v2.3.0)",
                "status": effective_status,
                "feed_status": effective_status,
                "market_status": market_state,
                "trading_day_status": session_info.get("trading_day_status", market_state),
                "description": status_desc,
                "is_market_session": is_open,
                "market_session_note": session_msg,
                "session_start_ist": session_info.get("session_start_ist", "09:15:00"),
                "session_end_ist": session_info.get("session_end_ist", "15:30:00"),
                "last_completed_session_date": get_last_completed_trading_session_date(now_utc),
                "feed_enabled": getattr(settings, "DHAN_FEED_ENABLED", False),
                "credentials_configured": bool(getattr(settings, "DHAN_CLIENT_ID", "") and getattr(settings, "DHAN_ACCESS_TOKEN", "")),
                "active_subscriptions": len(self._sec_to_symbol),
                "valid_ticks_count": self.valid_ticks_count,
                "invalid_ticks_count": self.invalid_ticks_count,
                "dropped_ticks_count": self.dropped_ticks_count,
                "last_connected_at": self.last_connected_at.isoformat() if self.last_connected_at else None,
                "last_source_timestamp": self.last_source_timestamp.isoformat() if self.last_source_timestamp else None,
                "last_ingestion_timestamp": self.last_ingestion_timestamp.isoformat() if self.last_ingestion_timestamp else None,
                "staleness_threshold_seconds": getattr(settings, "DHAN_STALENESS_THRESHOLD_SECONDS", 15.0),
                "timezone": "Asia/Kolkata",
                "error_message": self.error_message
            }

    def _refresh_quote_freshness(self, q: dict[str, Any], now_utc: datetime) -> dict[str, Any]:
        """Calculates exact truthful freshness status and observation age."""
        is_open, session_msg = is_market_session_active(now_utc)
        session_info = get_market_session_info(now_utc)
        staleness_limit = getattr(settings, "DHAN_STALENESS_THRESHOLD_SECONDS", 15.0)

        q["last_completed_session_date"] = get_last_completed_trading_session_date(now_utc)
        q["session_note"] = session_msg
        q["market_session"] = is_open
        q["timezone"] = "Asia/Kolkata"

        if is_open:
            market_status = "OPEN"
        elif session_info.get("is_weekend"):
            market_status = "WEEKEND"
        elif session_info.get("is_holiday"):
            market_status = "HOLIDAY"
        else:
            market_status = "CLOSED"
        q["market_status"] = market_status

        if q.get("price") is None:
            snap = get_latest_snapshot(q["symbol"])
            if snap and snap.get("price") is not None and snap["price"] > 0:
                q["price"] = snap["price"]
                q["previous"] = snap.get("previous_close")
                q["close"] = snap.get("close")
                q["open"] = snap.get("open")
                q["high"] = snap.get("high")
                q["low"] = snap.get("low")
                q["volume"] = snap.get("volume")
                q["price_type"] = snap.get("price_type") or ("LAST_SESSION_CLOSE" if not is_open else "LIVE_QUOTE")
                q["observation_timestamp"] = snap.get("observation_timestamp")
                if snap.get("observation_timestamp"):
                    q["ingestion_timestamp"] = snap["observation_timestamp"]

        if q.get("price") is None:
            q["is_live"] = False
            q["price_type"] = "NONE"
            q["feed_status"] = "WAITING_FOR_FIRST_TICK" if is_open else "MARKET_CLOSED"
            q["freshness_status"] = "WAITING_FOR_FIRST_TICK" if is_open else "MARKET_CLOSED"
            q["observation_age_seconds"] = None
            return q

        # Calculate observation age
        obs_time_str = q.get("observation_timestamp") or q.get("ingestion_timestamp") or q.get("source_timestamp")
        age = None
        if obs_time_str:
            try:
                obs_dt = datetime.fromisoformat(str(obs_time_str))
                if obs_dt.tzinfo is None:
                    obs_dt = obs_dt.replace(tzinfo=UTC)
                age = max(0.0, round((now_utc - obs_dt).total_seconds(), 1))
            except (TypeError, ValueError):
                age = None
        q["observation_age_seconds"] = age

        if not is_open:
            q["is_live"] = False
            q["feed_status"] = "MARKET_CLOSED"
            q["freshness_status"] = "MARKET_CLOSED"
            if not q.get("price_type") or q.get("price_type") == "LIVE_QUOTE":
                if q.get("close") is not None and abs(q["price"] - q["close"]) < 1e-4:
                    q["price_type"] = "OFFICIAL_SESSION_CLOSE"
                else:
                    q["price_type"] = "LAST_SESSION_CLOSE"
        else:
            if age is not None and age > staleness_limit:
                q["is_live"] = False
                q["feed_status"] = "STALE"
                q["freshness_status"] = "STALE"
            else:
                q["is_live"] = True
                q["feed_status"] = "LIVE"
                q["freshness_status"] = "LIVE"
                q["price_type"] = "LIVE_QUOTE"

        return q

    def get_watchlist(self) -> list[dict[str, Any]]:
        """Return the current quotes for all registered watchlist instruments."""
        now_utc = datetime.now(UTC)
        with self.lock:
            result = []
            for item in INITIAL_INSTRUMENT_CATALOG:
                sym = item["symbol"]
                cached = self._cache.get(sym)
                if cached:
                    updated = self._refresh_quote_freshness(cached, now_utc)
                    result.append(updated)
            return result

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        """Retrieve single instrument quote from low-latency cache with live-only freshness verification."""
        now_utc = datetime.now(UTC)
        with self.lock:
            sym = symbol.upper()
            q = self._cache.get(sym)
            if q:
                return self._refresh_quote_freshness(q, now_utc)
            return None

    def get_live_ticks(self, symbol: str) -> list[float]:
        """Retrieve actual observed live tick prices received during this session."""
        with self.lock:
            return list(self._live_ticks.get(symbol.upper(), []))

    def normalize_and_ingest_tick(self, raw_data: dict[str, Any]):
        """
        Normalizes a DhanHQ MarketFeed packet into standard SYNQ tick format.
        Preserves source timestamps and ingestion timestamps without blocking.
        Enforces live-only policy: distinguishes live ticks from reference close data.
        """
        now_utc = datetime.now(UTC)
        sec_id = str(raw_data.get("security_id", "")).strip()
        symbol = self._sec_to_symbol.get(sec_id)

        if not symbol:
            self.invalid_ticks_count += 1
            return

        try:
            ltp_raw = raw_data.get("LTP")
            if ltp_raw is None:
                return

            close_p = float(raw_data["close"]) if "close" in raw_data and raw_data["close"] is not None else None
            val_ok, val_err = validate_market_observation(symbol, ltp_raw, prev_close=close_p)
            if not val_ok:
                self.invalid_ticks_count += 1
                logger.warning(f"Rejected invalid Dhan tick for {symbol}: {val_err}")
                return

            ltp = float(ltp_raw)
            volume = int(raw_data.get("volume", 0))
            open_p = float(raw_data["open"]) if "open" in raw_data and raw_data["open"] is not None else None
            high_p = float(raw_data["high"]) if "high" in raw_data and raw_data["high"] is not None else None
            low_p = float(raw_data["low"]) if "low" in raw_data and raw_data["low"] is not None else None

            # Parse source timestamp (LTT from packet, e.g. "HH:MM:SS" or datetime)
            source_ts = None
            ltt_raw = raw_data.get("LTT")
            if isinstance(ltt_raw, datetime):
                source_ts = ltt_raw
            elif isinstance(ltt_raw, str) and ltt_raw:
                try:
                    if "T" in ltt_raw:
                        source_ts = datetime.fromisoformat(ltt_raw)
                    else:
                        today_ist = now_utc.astimezone(IST_OFFSET).date()
                        parts = ltt_raw.split(":")
                        source_ts = datetime(
                            today_ist.year, today_ist.month, today_ist.day,
                            int(parts[0]), int(parts[1]), int(float(parts[2])),
                            tzinfo=IST_OFFSET
                        ).astimezone(UTC)
                except (TypeError, ValueError, OverflowError, OSError):
                    source_ts = now_utc
            else:
                source_ts = now_utc

            is_open, session_msg = is_market_session_active(now_utc)

            with self.lock:
                prev_quote = self._cache.get(symbol, {})
                prev_price = prev_quote.get("price")
                ref_close = close_p

                if prev_price is not None and prev_price > 0:
                    change = round(ltp - prev_price, 2)
                    change_pct = round((change / prev_price) * 100.0, 2)
                elif ref_close is not None and ref_close > 0:
                    change = round(ltp - ref_close, 2)
                    change_pct = round((change / ref_close) * 100.0, 2)
                else:
                    change = None
                    change_pct = None

                if is_open:
                    price_type = "LIVE_QUOTE"
                    freshness = "LIVE"
                    is_live = True
                else:
                    if close_p and abs(ltp - close_p) < 1e-4:
                        price_type = "OFFICIAL_SESSION_CLOSE"
                    else:
                        price_type = "LAST_SESSION_CLOSE"
                    freshness = "MARKET_CLOSED"
                    is_live = False

                provenance = (
                    f"DhanHQ-py live tick (Security ID: {sec_id})"
                    if is_open
                    else f"DhanHQ packet received outside regular trading hours ({session_msg})"
                )

                normalized_quote = {
                    "symbol": symbol,
                    "security_id": sec_id,
                    "name": self._catalog_map.get(symbol, {}).get("name", symbol),
                    "exchange_segment": self._catalog_map.get(symbol, {}).get("exchange_segment", "NSE_EQ"),
                    "price": ltp,
                    "previous": ref_close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": volume,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": close_p,
                    "source": "DHAN_MARKETFEED_V2",
                    "provenance": provenance,
                    "source_timestamp": source_ts.isoformat() if source_ts else now_utc.isoformat(),
                    "ingestion_timestamp": now_utc.isoformat(),
                    "observation_timestamp": now_utc.isoformat(),
                    "is_live": is_live,
                    "price_type": price_type,
                    "market_status": "OPEN" if is_open else "CLOSED",
                    "feed_status": freshness,
                    "freshness_status": freshness,
                    "last_completed_session_date": get_last_completed_trading_session_date(now_utc),
                    "timezone": "Asia/Kolkata",
                    "mode": "LIVE_ONLY"
                }

                # Update in-memory state cache
                self._cache[symbol] = normalized_quote

                # Persist snapshot for market-closed handling
                try:
                    persist_snapshot(
                        symbol=symbol,
                        price=ltp,
                        open_p=open_p,
                        high_p=high_p,
                        low_p=low_p,
                        close_p=close_p if close_p else ltp,
                        previous_close=ref_close,
                        volume=volume,
                        price_type=price_type,
                        market_status="OPEN" if is_open else "CLOSED",
                        feed_status=freshness,
                        source="DHAN_MARKETFEED_V2",
                        observation_timestamp=now_utc,
                        provider_timestamp=source_ts.isoformat() if source_ts else None,
                    )
                except SQLAlchemyError as snap_err:
                    logger.debug(f"Snapshot persistence error in Dhan adapter: {snap_err}")
                if is_open:
                    if symbol not in self._live_ticks:
                        self._live_ticks[symbol] = []
                    self._live_ticks[symbol].append(ltp)
                    if len(self._live_ticks[symbol]) > 200:
                        self._live_ticks[symbol].pop(0)

                self.last_source_timestamp = source_ts
                self.last_ingestion_timestamp = now_utc
                self.valid_ticks_count += 1
                self.connection_status = "LIVE" if is_open else "MARKET_CLOSED"

                # Enqueue for batched persistence
                if len(self._tick_buffer) < getattr(settings, "DHAN_QUEUE_MAXSIZE", 1000):
                    self._tick_buffer.append({
                        "security_id": sec_id,
                        "symbol": symbol,
                        "exchange_segment": self._catalog_map.get(symbol, {}).get("exchange_segment", "NSE_EQ"),
                        "ltp": ltp,
                        "volume": volume,
                        "open_price": open_p,
                        "high_price": high_p,
                        "low_price": low_p,
                        "close_price": close_p,
                        "source_timestamp": source_ts,
                        "ingested_at": now_utc
                    })
                else:
                    self.dropped_ticks_count += 1

            # Dispatch tick asynchronously to event detector if registered
            if self._event_callback:
                try:
                    self._event_callback(normalized_quote)
                except Exception as cb_err:
                    logger.exception("Unexpected failure at the service boundary")
                    logger.error(f"Event detector callback error on tick {symbol}: {cb_err}")

        except (TypeError, ValueError, KeyError, AttributeError, OverflowError) as e:
            self.invalid_ticks_count += 1
            logger.debug(f"Failed to normalize raw Dhan tick: {e}")

    def _batch_persistence_worker(self):
        """
        Background worker that flushes tick buffer in batches every 5 seconds.
        Prevents SQLite locking and isolates live WebSocket from database I/O.
        """
        while self._running:
            time.sleep(getattr(settings, "DHAN_BATCH_WRITE_SECONDS", 5.0))
            ticks_to_write = []
            with self.lock:
                if self._tick_buffer:
                    ticks_to_write = list(self._tick_buffer)
                    self._tick_buffer.clear()

            if not ticks_to_write:
                continue

            try:
                with SessionLocal() as db:
                    records = [
                        MarketTickRecord(
                            security_id=t["security_id"],
                            symbol=t["symbol"],
                            exchange_segment=t["exchange_segment"],
                            ltp=t["ltp"],
                            volume=t["volume"],
                            open_price=t["open_price"],
                            high_price=t["high_price"],
                            low_price=t["low_price"],
                            close_price=t["close_price"],
                            source_timestamp=t["source_timestamp"],
                            ingested_at=t["ingested_at"]
                        )
                        for t in ticks_to_write
                    ]
                    db.bulk_save_objects(records)

                    # Also update latest Quote record in db
                    for t in ticks_to_write:
                        q_rec = db.query(Quote).filter(Quote.symbol == t["symbol"]).first()
                        if q_rec:
                            q_rec.price = t["ltp"]
                            if t["volume"] > 0:
                                q_rec.volume = t["volume"]
                            q_rec.timestamp = t["ingested_at"]
                    db.commit()
            except SQLAlchemyError as e:
                logger.error(f"Error persisting batch ticks to database: {e}")

    def start(self):
        """
        Starts the DhanHQ MarketFeed background thread only when explicitly configured and enabled.
        """
        client_id = getattr(settings, "DHAN_CLIENT_ID", "").strip()
        access_token = getattr(settings, "DHAN_ACCESS_TOKEN", "").strip()
        feed_enabled = getattr(settings, "DHAN_FEED_ENABLED", False)

        if not feed_enabled or not client_id or not access_token:
            logger.info("DhanHQ live feed not started: DHAN_FEED_ENABLED is False or credentials missing. LIVE_ONLY mode active (no historical fallback).")
            self.connection_status = "UNAVAILABLE"
            return

        with self.lock:
            if self._running:
                return
            self._running = True

        # Start batch persistence worker
        self._batch_thread = threading.Thread(target=self._batch_persistence_worker, daemon=True, name="DhanBatchPersistence")
        self._batch_thread.start()

        # Start WebSocket receiver thread
        self._thread = threading.Thread(target=self._run_feed_loop, daemon=True, name="DhanMarketFeedLoop")
        self._thread.start()
        logger.info("DhanHQ live market feed background workers started successfully.")

    def _run_feed_loop(self):
        """
        Executes MarketFeed connection with bounded exponential backoff.
        """
        from dhanhq import DhanContext, MarketFeed

        client_id = getattr(settings, "DHAN_CLIENT_ID", "")
        access_token = getattr(settings, "DHAN_ACCESS_TOKEN", "")

        while self._running:
            try:
                logger.info(f"Connecting to DhanHQ MarketFeed (Client ID: {client_id[:4]}***)...")
                dhan_context = DhanContext(client_id, access_token)

                # Format instruments subscription list: (segment_code, security_id, MarketFeed.Quote)
                instruments = [
                    (item["segment_code"], item["security_id"], MarketFeed.Quote)
                    for item in INITIAL_INSTRUMENT_CATALOG
                ]

                def on_connect_cb():
                    logger.info("DhanHQ MarketFeed WebSocket connected successfully.")
                    with self.lock:
                        self.connection_status = "LIVE"
                        self.last_connected_at = datetime.now(UTC)
                        self.reconnect_attempts = 0
                        self.error_message = None

                def on_message_cb(instance, message):
                    if isinstance(message, dict):
                        self.normalize_and_ingest_tick(message)

                def on_close_cb(instance, code, reason):
                    logger.warning(f"DhanHQ MarketFeed closed: code={code}, reason={reason}")
                    with self.lock:
                        self.connection_status = "DISCONNECTED"

                def on_error_cb(instance, error):
                    logger.error(f"DhanHQ MarketFeed error: {error}")
                    with self.lock:
                        self.error_message = str(error)

                self._market_feed_instance = MarketFeed(
                    dhan_context=dhan_context,
                    instruments=instruments,
                    version="v2",
                    on_connect=on_connect_cb,
                    on_message=on_message_cb,
                    on_close=on_close_cb,
                    on_error=on_error_cb
                )

                self._market_feed_instance.run()

            except Exception as e:
                logger.exception("Unexpected failure at the service boundary")
                with self.lock:
                    self.connection_status = "DISCONNECTED"
                    self.error_message = str(e)
                    self.reconnect_attempts += 1
                logger.error(f"DhanHQ feed loop error: {e} (Attempt {self.reconnect_attempts})")

            if not self._running:
                break

            # Exponential backoff up to max attempts
            max_attempts = getattr(settings, "DHAN_RECONNECT_MAX_ATTEMPTS", 5)
            if self.reconnect_attempts >= max_attempts:
                logger.warning(f"DhanHQ feed reached maximum reconnect attempts ({max_attempts}). Suspending automatic reconnect.")
                time.sleep(60.0)
                self.reconnect_attempts = 0
            else:
                backoff = getattr(settings, "DHAN_RECONNECT_BASE_DELAY_SECONDS", 2.0) * (2 ** min(self.reconnect_attempts, 4))
                time.sleep(backoff)

    def stop(self):
        """Gracefully shuts down MarketFeed, closes WebSocket, and flushes tick buffer."""
        with self.lock:
            self._running = False
            self.connection_status = "DISCONNECTED"

        if self._market_feed_instance:
            try:
                self._market_feed_instance.close_connection()
            except (OSError, RuntimeError) as e:
                logger.debug(f"Error closing MarketFeed connection: {e}")

        logger.info("DhanLiveFeedAdapter stopped gracefully.")


# Global thread-safe singleton instance of DhanLiveFeedAdapter
raw_dhan_live_feed = DhanLiveFeedAdapter()


class ActiveMarketFeedProxy:
    """
    Transparent proxy that delegates dynamically to the configured active market-data adapter
    ('ramm_stock_api' or 'dhanhq_live').
    Preserves 100% backward compatibility for all existing callers importing dhan_live_feed.
    """

    def __init__(self, fallback_dhan: DhanLiveFeedAdapter):
        self._fallback_dhan = fallback_dhan

    @property
    def active_feed(self):
        provider = getattr(settings, "MARKET_DATA_PROVIDER", "0xramm_yahoo_rest")
        if provider in ("0xramm_yahoo_rest", "ramm_stock_api"):
            from app.market.ramm_adapter import ramm_market_feed
            return ramm_market_feed
        return self._fallback_dhan

    def get_status(self) -> dict[str, Any]:
        return self.active_feed.get_status()

    def get_watchlist(self) -> list[dict[str, Any]]:
        return self.active_feed.get_watchlist()

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        return self.active_feed.get_quote(symbol)

    def get_live_ticks(self, symbol: str) -> list[float]:
        return self.active_feed.get_live_ticks(symbol)

    def reset_cache(self):
        return self.active_feed.reset_cache()

    def register_event_listener(self, callback):
        return self.active_feed.register_event_listener(callback)

    def start(self):
        return self.active_feed.start()

    def stop(self):
        return self.active_feed.stop()

    def poll_now(self) -> dict[str, Any]:
        if hasattr(self.active_feed, "poll_now"):
            return self.active_feed.poll_now()
        return {"status": "not_supported"}

    def get_aggregated_candles(self, symbol: str, interval_minutes: int = 5, limit: int = 30) -> list[dict[str, Any]]:
        if hasattr(self.active_feed, "get_aggregated_candles"):
            return self.active_feed.get_aggregated_candles(symbol, interval_minutes, limit)
        return []

    def __getattr__(self, name: str):
        return getattr(self.active_feed, name)


dhan_live_feed = ActiveMarketFeedProxy(raw_dhan_live_feed)

# Attach deterministic event detector callback
try:
    from app.market.event_detector import event_detector
    dhan_live_feed.register_event_listener(event_detector.evaluate_tick)
except (ImportError, AttributeError) as e:
    logger.debug(f"Event detector registration deferred: {e}")
