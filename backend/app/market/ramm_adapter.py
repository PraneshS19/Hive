"""
HIVE — 0xramm Indian Stock Market API Provisional REST Market-Data Adapter
Provides isolated REST-based market-data polling backed by the reviewed 0xramm/Indian-Stock-Market-API.

Educational research & paper trading only.
Does NOT claim exchange-grade real-time data or verified streaming OHLCV.
Strictly adheres to HIVE's LIVE_ONLY data integrity invariants.
"""

import math
import threading
import time
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import logger
from app.db.models import Quote
from app.db.session import SessionLocal

# Indian Standard Time (IST) Offset & Official Exchange Calendar Service
from app.market.session_calendar import (
    IST_OFFSET,
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

# Authoritative Broad Watchlist: 30 Major NSE Listed Equities & Benchmark Index
INITIAL_INSTRUMENT_CATALOG = [
    {"security_id": "2885", "symbol": "RELIANCE", "name": "Reliance Industries Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "RELIANCE.NS"},
    {"security_id": "11536", "symbol": "TCS", "name": "Tata Consultancy Services Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "TCS.NS"},
    {"security_id": "1594", "symbol": "INFY", "name": "Infosys Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "INFY.NS"},
    {"security_id": "1333", "symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "HDFCBANK.NS"},
    {"security_id": "4963", "symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "ICICIBANK.NS"},
    {"security_id": "3045", "symbol": "SBIN", "name": "State Bank of India", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "SBIN.NS"},
    {"security_id": "10604", "symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "BHARTIARTL.NS"},
    {"security_id": "1660", "symbol": "ITC", "name": "ITC Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "ITC.NS"},
    {"security_id": "11483", "symbol": "LT", "name": "Larsen & Toubro Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "LT.NS"},
    {"security_id": "1922", "symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "KOTAKBANK.NS"},
    {"security_id": "5900", "symbol": "AXISBANK", "name": "Axis Bank Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "AXISBANK.NS"},
    {"security_id": "1394", "symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "HINDUNILVR.NS"},
    {"security_id": "317", "symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "BAJFINANCE.NS"},
    {"security_id": "10999", "symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "MARUTI.NS"},
    {"security_id": "3456", "symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "TATAMOTORS.NS"},
    {"security_id": "3351", "symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "SUNPHARMA.NS"},
    {"security_id": "3506", "symbol": "TITAN", "name": "Titan Company Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "TITAN.NS"},
    {"security_id": "11532", "symbol": "ULTRACEMCO", "name": "UltraTech Cement Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "ULTRACEMCO.NS"},
    {"security_id": "3787", "symbol": "WIPRO", "name": "Wipro Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "WIPRO.NS"},
    {"security_id": "11630", "symbol": "NTPC", "name": "NTPC Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "NTPC.NS"},
    {"security_id": "14977", "symbol": "POWERGRID", "name": "Power Grid Corporation of India Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "POWERGRID.NS"},
    {"security_id": "2475", "symbol": "ONGC", "name": "Oil & Natural Gas Corporation Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "ONGC.NS"},
    {"security_id": "3499", "symbol": "TATASTEEL", "name": "Tata Steel Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "TATASTEEL.NS"},
    {"security_id": "2031", "symbol": "M&M", "name": "Mahindra & Mahindra Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "M&M.NS"},
    {"security_id": "236", "symbol": "ASIANPAINT", "name": "Asian Paints Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "ASIANPAINT.NS"},
    {"security_id": "7229", "symbol": "HCLTECH", "name": "HCL Technologies Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "HCLTECH.NS"},
    {"security_id": "25", "symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "ADANIENT.NS"},
    {"security_id": "16675", "symbol": "BAJAJFINSV", "name": "Bajaj Finserv Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "BAJAJFINSV.NS"},
    {"security_id": "20374", "symbol": "COALINDIA", "name": "Coal India Ltd", "exchange_segment": "NSE_EQ", "segment_code": 1, "type": "EQUITY", "yahoo_ticker": "COALINDIA.NS"},
    {"security_id": "13", "symbol": "NIFTY50", "name": "NIFTY 50 Benchmark Index", "exchange_segment": "IDX", "segment_code": 0, "type": "INDEX", "yahoo_ticker": "^NSEI"}
]


class PollingCandleAggregator:
    """
    Aggregates discrete polling observations into interval candles.
    Guarantees:
    1. Labelled as POLLING_DERIVED_APPROXIMATION (not exchange-grade streaming bars).
    2. Never sums cumulative volume snapshots.
    3. Calculates interval volume using the last valid observation at or before the interval
       boundary and a valid later observation within the interval, subject to timestamp and session rules.
    4. Detects daily counter resets, counter decreases, missing baselines, and session boundaries.
    5. Preserves source timestamps and ingestion timestamps separately.
    6. Rejects or flags stale, negative, or corrupt observations.
    """

    def __init__(self, max_samples_per_symbol: int = 500):
        self._samples: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._max_samples = max_samples_per_symbol

    def add_observation(
        self,
        symbol: str,
        price: float,
        cumulative_volume: int | None,
        timestamp: datetime,
        source_timestamp: datetime | None = None
    ):
        """
        Record a discrete observation with validation.
        - price must be positive and finite.
        - cumulative_volume must be non-negative integer or None.
        - Deduplicates consecutive identical samples.
        """
        if price is None or price <= 0:
            return
        if isinstance(price, (int, float)) and (math.isnan(price) or math.isinf(price)):
            return

        cum_vol = None
        if cumulative_volume is not None:
            try:
                v = int(cumulative_volume)
                if v >= 0:
                    cum_vol = v
            except (ValueError, TypeError):
                cum_vol = None

        sym = symbol.upper().strip()
        ingest_ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
        src_ts = source_timestamp if (source_timestamp and source_timestamp.tzinfo) else (
            source_timestamp.replace(tzinfo=UTC) if source_timestamp else ingest_ts
        )

        with self._lock:
            if sym not in self._samples:
                self._samples[sym] = []

            samples = self._samples[sym]
            # Deduplicate consecutive identical observations (same ts and price and volume)
            if samples:
                last_sample = samples[-1]
                if (
                    last_sample["ts"] == ingest_ts
                    and last_sample["price"] == price
                    and last_sample["cum_vol"] == cum_vol
                ):
                    return

            samples.append({
                "price": float(price),
                "cum_vol": cum_vol,
                "ts": ingest_ts,
                "source_ts": src_ts
            })
            if len(samples) > self._max_samples:
                samples.pop(0)

    def get_aggregated_candles(
        self,
        symbol: str,
        interval_minutes: int = 1,
        limit: int = 30,
        require_prior_baseline: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            sym = symbol.upper().strip()
            raw_obs = self._samples.get(sym, [])
            if not raw_obs:
                return []

            # Sort all observations chronologically by effective timestamp
            all_obs = sorted(raw_obs, key=lambda x: x["ts"])
            interval_sec = interval_minutes * 60

            # Group into interval buckets based on timestamp
            buckets: dict[int, list[dict[str, Any]]] = {}
            for item in all_obs:
                ts = item["ts"]
                bucket_key = int(ts.timestamp() // interval_sec) * interval_sec
                if bucket_key not in buckets:
                    buckets[bucket_key] = []
                buckets[bucket_key].append(item)

            sorted_keys = sorted(buckets.keys())
            candles = []
            now_utc = datetime.now(UTC)

            for b_key in sorted_keys[-limit:]:
                bucket_dt = datetime.fromtimestamp(b_key, tz=UTC)
                b_obs = sorted(buckets[b_key], key=lambda x: x["ts"])
                if not b_obs:
                    continue

                first_obs = b_obs[0]
                last_obs = b_obs[-1]
                high_p = max(o["price"] for o in b_obs)
                low_p = min(o["price"] for o in b_obs)
                is_closed = (now_utc - bucket_dt).total_seconds() >= interval_sec

                # Locate the last valid baseline observation at or before interval boundary (b_key)
                prior_candidates = [o for o in all_obs if o["ts"] <= bucket_dt]
                baseline_obs = prior_candidates[-1] if prior_candidates else None

                # Check session boundary for baseline observation:
                # Cumulative volume on exchange resets to 0 at daily market open (09:15 IST).
                # A baseline from a prior calendar day / session cannot be subtracted from today's volume.
                bucket_ist_date = bucket_dt.astimezone(IST_OFFSET).date()
                session_reset = False
                if baseline_obs is not None:
                    base_ist_date = baseline_obs["ts"].astimezone(IST_OFFSET).date()
                    if base_ist_date != bucket_ist_date:
                        # Baseline is from a previous trading session!
                        baseline_obs = None
                        session_reset = True

                interval_vol = None
                vol_semantics = "UNAVAILABLE"
                vol_diag = None

                # Case 1: Valid baseline at or before interval boundary exists
                if baseline_obs is not None:
                    base_v = baseline_obs["cum_vol"]
                    last_v = last_obs["cum_vol"]
                    if base_v is not None and last_v is not None:
                        if last_v >= base_v:
                            # Note: if the only observation inside or at the interval is identical to baseline_obs
                            # at T_start with no subsequent poll in the interval, volume delta cannot be established.
                            if last_obs["ts"] == baseline_obs["ts"] and last_obs["ts"] == bucket_dt:
                                interval_vol = None
                                vol_semantics = "UNAVAILABLE"
                                vol_diag = "insufficient_baseline: single observation at start boundary without subsequent intra-interval poll"
                            else:
                                interval_vol = last_v - base_v
                                vol_semantics = "BASELINE_DELTA_APPROXIMATION"
                                vol_diag = None
                        else:
                            interval_vol = None
                            vol_semantics = "UNAVAILABLE"
                            vol_diag = "Cumulative volume counter decrease or reset detected"
                    else:
                        interval_vol = None
                        vol_semantics = "UNAVAILABLE"
                        vol_diag = "Missing cumulative volume value in baseline or latest observation"

                # Case 2: No baseline at or before interval boundary exists (e.g. first candle after startup)
                else:
                    if session_reset:
                        interval_vol = None
                        vol_semantics = "UNAVAILABLE"
                        vol_diag = "Session boundary: baseline from previous trading session cannot be used after market open reset (insufficient_baseline)"
                    elif require_prior_baseline:
                        interval_vol = None
                        vol_semantics = "UNAVAILABLE"
                        vol_diag = "Missing prior baseline observation at or before interval boundary (insufficient_baseline)"
                    else:
                        # Fallback for initial sample burst within first candle
                        first_v = first_obs["cum_vol"]
                        last_v = last_obs["cum_vol"]
                        if first_v is not None and last_v is not None and last_v >= first_v:
                            # If only 1 observation exists inside the candle (len(b_obs) < 2),
                            # delta CANNOT be established (last_v - first_v would be 0, falsely implying 0 trades!).
                            if len(b_obs) < 2 or first_obs["ts"] == last_obs["ts"]:
                                interval_vol = None
                                vol_semantics = "UNAVAILABLE"
                                vol_diag = "insufficient_baseline: single observation inside interval without prior baseline cannot establish volume delta"
                            elif last_v == first_v and first_obs["ts"] > bucket_dt:
                                # When volume didn't change between polls inside candle, but we missed [bucket_dt, first_obs.ts),
                                # we cannot establish whether trades occurred before first_obs
                                interval_vol = None
                                vol_semantics = "UNAVAILABLE"
                                vol_diag = "insufficient_baseline: volume unchanged between intra-candle polls with missing boundary baseline"
                            else:
                                interval_vol = last_v - first_v
                                vol_semantics = "PARTIAL_INTERVAL_APPROXIMATION"
                                vol_diag = "Missing prior baseline at boundary; volume estimated from first poll inside interval"
                        else:
                            interval_vol = None
                            vol_semantics = "UNAVAILABLE"
                            vol_diag = "insufficient_baseline: non-monotonic volume or missing snapshot"

                candles.append({
                    "symbol": sym,
                    "timestamp": bucket_dt.isoformat(),
                    "open": first_obs["price"],
                    "high": high_p,
                    "low": low_p,
                    "close": last_obs["price"],
                    "volume": interval_vol,
                    "volume_semantics": vol_semantics,
                    "volume_diagnostic": vol_diag,
                    "volume_is_approximate": True,
                    "candle_type": "POLLING_DERIVED_APPROXIMATION",
                    "is_synthetic": False,
                    "is_closed": is_closed,
                    "sample_count": len(b_obs)
                })

            return candles

    def clear(self):
        with self._lock:
            self._samples.clear()


class RammStockAdapter:
    """
    Isolated, resilient market-data adapter for 0xramm/Indian-Stock-Market-API.
    Supports:
    - Bounded retries with exponential backoff
    - Single-flight lock preventing duplicate concurrent polling
    - Truthful feed states: CONNECTING, LIVE, STALE, MARKET_CLOSED, DISCONNECTED, ERROR
    - Strict validation: rejects malformed/negative prices
    - Distinguishes provider timestamp from local ingestion timestamp
    - Polling-derived candle aggregation without cumulative volume distortion
    """

    def __init__(self):
        self.lock = threading.RLock()
        self._polling_flight_lock = threading.Lock()
        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._batch_thread: threading.Thread | None = None

        # Quote cache: symbol -> quote dict
        self._cache: dict[str, dict[str, Any]] = {}
        self._symbol_to_ticker: dict[str, str] = {}
        self._ticker_to_symbol: dict[str, str] = {}
        self._catalog_map: dict[str, dict[str, Any]] = {}
        self._live_ticks: dict[str, list[float]] = {}

        # Connection telemetry & health tracking
        self.connection_status = "CONNECTING"
        self.last_poll_at: datetime | None = None
        self.last_provider_timestamp: str | None = None
        self.last_ingestion_timestamp: datetime | None = None
        self.valid_polls_count = 0
        self.error_polls_count = 0
        self.consecutive_unchanged_count = 0
        self._last_quotes_hash: str | None = None
        self.error_message: str | None = None
        self.active_provider_url: str = ""

        # Event detector callback
        self._event_callback = None

        # Candle Aggregator
        self.candle_aggregator = PollingCandleAggregator()

        # Embedded Direct Yahoo Session (for fallback resilience)
        self._yahoo_session = requests.Session()
        self._yahoo_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        self._cached_crumb: str | None = None
        self._crumb_expires_at: float = 0.0

        self._initialize_catalog()

    def reset_cache(self):
        """Reset live quote cache, ticks, and aggregator for testing or data reset."""
        with self.lock:
            self._live_ticks.clear()
            self.candle_aggregator.clear()
            self.consecutive_unchanged_count = 0
            self._last_quotes_hash = None
            self._initialize_catalog()

    def _initialize_catalog(self):
        """Initialize in-memory lookup maps and hydrate from persistent snapshots."""
        is_open, _session_msg = is_market_session_active()
        initial_freshness = "WAITING_FOR_FIRST_POLL" if is_open else "MARKET_CLOSED"

        try:
            snapshots = get_all_latest_snapshots()
        except SQLAlchemyError as e:
            logger.debug(f"Could not load snapshots during catalog initialization: {e}")
            snapshots = {}

        for item in INITIAL_INSTRUMENT_CATALOG:
            sym = item["symbol"]
            ticker = item["yahoo_ticker"]
            self._symbol_to_ticker[sym] = ticker
            self._ticker_to_symbol[ticker] = sym
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
                    "security_id": item["security_id"],
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
                    "source": snap.get("source") or "0XRAMM_REST_V3",
                    "provenance": snap.get("provenance") or "Verified persistent snapshot from previous session",
                    "provider_timestamp": snap.get("observation_timestamp"),
                    "source_timestamp": snap.get("observation_timestamp"),
                    "ingestion_timestamp": snap.get("observation_timestamp"),
                    "observation_timestamp": snap.get("observation_timestamp"),
                    "observation_time_status": "PERSISTED_SNAPSHOT",
                    "is_live": False,
                    "price_type": snap.get("price_type") or ("LAST_SESSION_CLOSE" if not is_open else "LIVE_QUOTE"),
                    "market_status": "OPEN" if is_open else "CLOSED",
                    "feed_status": "MARKET_CLOSED" if not is_open else "CONNECTED_WAITING_FOR_DATA",
                    "freshness_status": initial_freshness,
                    "mode": "LIVE_ONLY",
                    "packet_type": "POLLING_REST"
                }
            else:
                self._cache[sym] = {
                    "symbol": sym,
                    "security_id": item["security_id"],
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
                    "source": "0XRAMM_REST_V3",
                    "provenance": "0xramm Indian Stock Market API (Provisional REST Adapter) — Yahoo Finance backed",
                    "provider_timestamp": None,
                    "source_timestamp": None,
                    "ingestion_timestamp": None,
                    "observation_timestamp": None,
                    "observation_time_status": "WAITING_FOR_FIRST_POLL",
                    "is_live": False,
                    "price_type": "NONE",
                    "market_status": "OPEN" if is_open else "CLOSED",
                    "feed_status": initial_freshness,
                    "freshness_status": initial_freshness,
                    "mode": "LIVE_ONLY",
                    "packet_type": "POLLING_REST"
                }

    def register_event_listener(self, callback):
        """Attach deterministic event detector to incoming normalized quotes."""
        self._event_callback = callback

    def get_status(self) -> dict[str, Any]:
        """Truthful, unembellished feed status reporting."""
        with self.lock:
            now_utc = datetime.now(UTC)
            is_open, session_msg = is_market_session_active(now_utc)
            session_info = get_market_session_info(now_utc)
            feed_enabled = getattr(settings, "RAM_FEED_ENABLED", True)
            staleness_limit = getattr(settings, "MARKET_DATA_STALE_AFTER_SECONDS", getattr(settings, "RAM_STALENESS_THRESHOLD_SECONDS", 60.0))
            poll_interval = getattr(settings, "MARKET_DATA_POLL_INTERVAL_SECONDS", getattr(settings, "RAM_POLL_INTERVAL_SECONDS", 15.0))
            base_url = getattr(settings, "MARKET_DATA_BASE_URL", getattr(settings, "RAM_STOCK_API_BASE_URL", "http://127.0.0.1:8787"))
            max_retries = getattr(settings, "MARKET_DATA_MAX_RETRIES", getattr(settings, "RAM_MAX_RETRIES", 2))

            # Distinguish market session status from feed provider health
            market_state = "OPEN" if is_open else ("WEEKEND" if session_info.get("is_weekend") else ("HOLIDAY" if session_info.get("is_holiday") else "CLOSED"))

            if not feed_enabled:
                feed_status = "DISCONNECTED"
                status_desc = "0xramm market-data adapter disabled in configuration (RAM_FEED_ENABLED=False)."
            elif self.error_message and self.error_polls_count > max_retries:
                feed_status = "PROVIDER_ERROR"
                status_desc = f"Provider error: {self.error_message}"
            elif not is_open:
                feed_status = "MARKET_CLOSED"
                status_desc = f"{session_msg} (Provisional REST adapter paused; serving verified last available market data)"
            elif self.last_ingestion_timestamp:
                age = (now_utc - self.last_ingestion_timestamp).total_seconds()
                if age > staleness_limit or self.consecutive_unchanged_count >= 3:
                    feed_status = "STALE"
                    status_desc = f"Feed connected but updates stale ({age:.1f}s since last fresh poll)."
                else:
                    feed_status = "LIVE"
                    status_desc = "Provisional REST market-data adapter active and polling."
            elif not self._running:
                feed_status = "DISCONNECTED"
                status_desc = "Feed poller stopped."
            else:
                feed_status = "CONNECTED_WAITING_FOR_DATA"
                status_desc = "Connected to 0xramm provider; waiting for first valid response packet."

            return {
                "provider": "0xramm Indian Stock Market API (Provisional REST Adapter)",
                "status": feed_status,
                "feed_state": feed_status,
                "feed_status": feed_status,
                "status_alias": feed_status,
                "is_live": feed_status == "LIVE",
                "description": status_desc,
                "market_status": market_state,
                "trading_day_status": session_info.get("trading_day_status", market_state),
                "is_market_session": is_open,
                "market_session_note": session_msg,
                "session_start_ist": session_info.get("session_start_ist", "09:15:00"),
                "session_end_ist": session_info.get("session_end_ist", "15:30:00"),
                "last_completed_session_date": get_last_completed_trading_session_date(now_utc),
                "feed_enabled": feed_enabled,
                "credentials_configured": True,  # No API key required
                "base_url": base_url,
                "response_mode": getattr(settings, "MARKET_DATA_RESPONSE_MODE", "num"),
                "poll_interval_seconds": poll_interval,
                "staleness_threshold_seconds": staleness_limit,
                "timezone": getattr(settings, "MARKET_DATA_TIMEZONE", "Asia/Kolkata"),
                "active_subscriptions": len(self._catalog_map),
                "valid_polls_count": self.valid_polls_count,
                "error_polls_count": self.error_polls_count,
                "consecutive_failures": self.error_polls_count,
                "consecutive_unchanged_count": self.consecutive_unchanged_count,
                "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
                "last_successful_request_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
                "last_provider_timestamp": self.last_provider_timestamp,
                "last_ingestion_timestamp": self.last_ingestion_timestamp.isoformat() if self.last_ingestion_timestamp else None,
                "last_valid_observation_at": self.last_ingestion_timestamp.isoformat() if self.last_ingestion_timestamp else None,
                "polling_request_latency_ms": getattr(self, "last_poll_latency_ms", None),
                "source_timestamp_age_seconds": getattr(self, "last_source_ts_age_sec", None),
                "source_value_cadence_seconds": poll_interval,
                "feed_cadence_type": "DISCRETE_POLLING_15S",
                "streaming_guarantee": "NONE (Discrete REST Polling via 0xramm; not exchange streaming)",
                "observation_type": "LIVE_TICK" if is_open else "PREVIOUS_SETTLEMENT_CLOSE",
                "last_error": self.error_message,
                "error_message": self.error_message,
                "disclaimer": "Educational research & paper trading provisional adapter. Not exchange-grade real-time streaming."
            }

    def _refresh_quote_freshness(self, q: dict[str, Any], now_utc: datetime) -> dict[str, Any]:
        """Calculates exact truthful freshness status and observation age for a single quote."""
        is_open, session_msg = is_market_session_active(now_utc)
        session_info = get_market_session_info(now_utc)
        staleness_limit = getattr(settings, "MARKET_DATA_STALE_AFTER_SECONDS", getattr(settings, "RAM_STALENESS_THRESHOLD_SECONDS", 60.0))
        last_session_date = get_last_completed_trading_session_date(now_utc)

        q["last_completed_session_date"] = last_session_date
        q["session_note"] = session_msg
        q["market_session"] = is_open
        q["timezone"] = "Asia/Kolkata"

        # Determine market_status
        if is_open:
            market_status = "OPEN"
        elif session_info.get("is_weekend"):
            market_status = "WEEKEND"
        elif session_info.get("is_holiday"):
            market_status = "HOLIDAY"
        else:
            market_status = "CLOSED"
        q["market_status"] = market_status

        # If price is missing from cache, attempt hydration from durable snapshot store
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
                q["source"] = snap.get("source") or q.get("source")
                q["provider_timestamp"] = snap.get("provider_timestamp")
                if snap.get("observation_timestamp"):
                    q["ingestion_timestamp"] = snap["observation_timestamp"]

        if q.get("price") is None:
            q["is_live"] = False
            q["price_type"] = "NONE"
            q["feed_status"] = "CONNECTED_WAITING_FOR_DATA" if is_open else "MARKET_CLOSED"
            q["freshness_status"] = "CONNECTED_WAITING_FOR_DATA" if is_open else "MARKET_CLOSED"
            q["observation_age_seconds"] = None
            return q

        # Calculate observation age
        direct_yahoo = q.get("source") == "YAHOO_FINANCE_EMBEDDED"
        obs_time_str = (
            q.get("market_timestamp") if direct_yahoo or q.get("market_timestamp")
            else q.get("observation_timestamp") or q.get("ingestion_timestamp") or q.get("provider_timestamp")
        )
        age = None
        if obs_time_str:
            try:
                obs_dt = datetime.fromisoformat(str(obs_time_str))
                if obs_dt.tzinfo is None:
                    obs_dt = obs_dt.replace(tzinfo=UTC)
                age = round((now_utc - obs_dt).total_seconds(), 1)
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
            if (direct_yahoo and age is None) or (age is not None and (age < 0 or age > staleness_limit)) or self.consecutive_unchanged_count >= 3:
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
        """Retrieve single instrument quote from cache with freshness verification."""
        now_utc = datetime.now(UTC)
        with self.lock:
            sym = symbol.upper()
            q = self._cache.get(sym)
            if q:
                return self._refresh_quote_freshness(q, now_utc)
            return None

    def get_live_ticks(self, symbol: str) -> list[float]:
        """Retrieve observed tick prices captured during this session."""
        with self.lock:
            return list(self._live_ticks.get(symbol.upper(), []))

    def get_aggregated_candles(self, symbol: str, interval_minutes: int = 5, limit: int = 30) -> list[dict[str, Any]]:
        """Retrieve polling-derived interval candles."""
        return self.candle_aggregator.get_aggregated_candles(symbol, interval_minutes, limit)

    def normalize_and_ingest_tick(self, raw_data: dict[str, Any]):
        """
        Ingests a normalized tick/quote packet directly into the in-memory cache and aggregator.
        Provides full programmatic testing and deterministic scenario replay compatibility.
        """
        now_utc = datetime.now(UTC)
        sec_id = str(raw_data.get("security_id", "")).strip()
        symbol = None

        with self.lock:
            if sec_id:
                for s, cat in self._catalog_map.items():
                    if cat.get("security_id") == sec_id:
                        symbol = s
                        break
            if not symbol and "symbol" in raw_data:
                sym_cand = str(raw_data["symbol"]).upper().strip()
                if sym_cand in self._catalog_map:
                    symbol = sym_cand

            if not symbol:
                return

            ltp_raw = raw_data.get("LTP") if "LTP" in raw_data else raw_data.get("last_price", raw_data.get("price"))
            if ltp_raw is None:
                return

            close_p = float(raw_data.get("close", raw_data.get("prev_close", raw_data.get("previous_close")) or 0.0))
            val_ok, val_err = validate_market_observation(symbol, ltp_raw, prev_close=close_p if close_p > 0 else None)
            if not val_ok:
                logger.warning(f"Rejected invalid tick observation for {symbol}: {val_err}")
                return

            ltp = float(ltp_raw)
            volume = int(raw_data.get("volume", 0))
            open_p = float(raw_data["open"]) if "open" in raw_data and raw_data["open"] is not None else None
            high_p = float(raw_data["high"]) if "high" in raw_data and raw_data["high"] is not None else None
            low_p = float(raw_data["low"]) if "low" in raw_data and raw_data["low"] is not None else None

            is_open, _session_msg = is_market_session_active(now_utc)
            get_market_session_info(now_utc)
            prev_quote = self._cache.get(symbol, {})
            prev_price = prev_quote.get("price")
            ref_close = close_p if close_p > 0 else prev_price

            change = round(ltp - ref_close, 2) if ref_close and ref_close > 0 else 0.0
            change_pct = round((change / ref_close) * 100.0, 2) if ref_close and ref_close > 0 else 0.0

            # Determine price_type
            if is_open:
                price_type = "LIVE_QUOTE"
                freshness = "LIVE"
            elif close_p and abs(ltp - close_p) < 1e-4:
                price_type = "OFFICIAL_SESSION_CLOSE"
                freshness = "MARKET_CLOSED"
            else:
                price_type = "LAST_SESSION_CLOSE"
                freshness = "MARKET_CLOSED"

            normalized = {
                "symbol": symbol,
                "security_id": self._catalog_map.get(symbol, {}).get("security_id", sec_id),
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
                "source": "0XRAMM_REST_V3",
                "provenance": f"0xramm Indian Stock Market API (Provisional REST Adapter) — tick for {symbol}",
                "provider_timestamp": now_utc.isoformat(),
                "source_timestamp": now_utc.isoformat(),
                "ingestion_timestamp": now_utc.isoformat(),
                "observation_timestamp": now_utc.isoformat(),
                "observation_time_status": "OBSERVED",
                "is_live": is_open,
                "price_type": price_type,
                "market_status": "OPEN" if is_open else "CLOSED",
                "feed_status": freshness,
                "freshness_status": freshness,
                "last_completed_session_date": get_last_completed_trading_session_date(now_utc),
                "timezone": "Asia/Kolkata",
                "mode": "LIVE_ONLY",
                "packet_type": "POLLING_REST"
            }

            self._cache[symbol] = normalized

            # Persist genuine observation snapshot
            try:
                persist_snapshot(
                    symbol=symbol,
                    price=ltp,
                    open_p=open_p,
                    high_p=high_p,
                    low_p=low_p,
                    close_p=close_p if close_p > 0 else ltp,
                    previous_close=ref_close,
                    volume=volume,
                    price_type=price_type,
                    market_status="OPEN" if is_open else "CLOSED",
                    feed_status=freshness,
                    source="0XRAMM_REST_V3",
                    observation_timestamp=now_utc,
                    provider_timestamp=now_utc.isoformat(),
                )
            except SQLAlchemyError as e:
                logger.debug(f"Snapshot persistence error in normalize_and_ingest_tick: {e}")
            if is_open:
                if symbol not in self._live_ticks:
                    self._live_ticks[symbol] = []
                self._live_ticks[symbol].append(ltp)
                if len(self._live_ticks[symbol]) > 200:
                    self._live_ticks[symbol].pop(0)

            self.candle_aggregator.add_observation(symbol, ltp, volume, now_utc)
            self.last_ingestion_timestamp = now_utc
            self.connection_status = "LIVE" if is_open else "MARKET_CLOSED"

        if self._event_callback:
            try:
                self._event_callback(normalized)
            except Exception as e:
                logger.exception("Unexpected failure at the service boundary")
                logger.debug(f"Event detector callback error: {e}")

    def _get_yahoo_crumb(self, force_refresh: bool = False) -> str:
        """Obtain Yahoo cookie + crumb handshake for embedded direct query fallback."""
        now = time.time()
        if not force_refresh and self._cached_crumb and now < self._crumb_expires_at:
            return self._cached_crumb

        # Step 1: visit fc.yahoo.com to set cookie
        self._yahoo_session.get("https://fc.yahoo.com", timeout=getattr(settings, "RAM_REQUEST_TIMEOUT_SECONDS", 6.0))
        # Step 2: query getcrumb endpoint
        crumb_res = self._yahoo_session.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            timeout=getattr(settings, "RAM_REQUEST_TIMEOUT_SECONDS", 6.0)
        )
        if crumb_res.status_code != 200:
            raise RuntimeError(f"Failed to obtain Yahoo crumb: HTTP {crumb_res.status_code}")
        crumb = crumb_res.text.strip()
        if not crumb or "<html" in crumb:
            raise RuntimeError(f"Invalid Yahoo crumb received: {crumb[:30]}")

        self._cached_crumb = crumb
        self._crumb_expires_at = now + 1800  # 30 min cache
        return crumb

    def _fetch_from_embedded_yahoo(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Direct Yahoo Finance fetch fallback using the exact reviewed logic."""
        crumb = self._get_yahoo_crumb()
        symbols_str = ",".join(tickers)
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols_str}&crumb={crumb}"
        res = self._yahoo_session.get(url, timeout=getattr(settings, "RAM_REQUEST_TIMEOUT_SECONDS", 6.0))
        if res.status_code == 401:
            crumb = self._get_yahoo_crumb(force_refresh=True)
            url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbols_str}&crumb={crumb}"
            res = self._yahoo_session.get(url, timeout=getattr(settings, "RAM_REQUEST_TIMEOUT_SECONDS", 6.0))

        if res.status_code != 200:
            raise RuntimeError(f"Embedded Yahoo batch quote failed: HTTP {res.status_code}")

        data = res.json()
        stocks = []
        for q in data.get("quoteResponse", {}).get("result", []):
            raw_sym = q.get("symbol", "")
            clean_sym = raw_sym.replace(".NS", "").replace(".BO", "")
            stocks.append({
                "symbol": clean_sym,
                "ticker": raw_sym,
                "company_name": q.get("longName") or q.get("shortName") or clean_sym,
                "last_price": q.get("regularMarketPrice"),
                "change": q.get("regularMarketChange"),
                "percent_change": q.get("regularMarketChangePercent"),
                "volume": q.get("regularMarketVolume"),
                "open": q.get("regularMarketOpen"),
                "day_high": q.get("regularMarketDayHigh"),
                "day_low": q.get("regularMarketDayLow"),
                "regular_market_time": q.get("regularMarketTime"),
                "previous_close": q.get("regularMarketPreviousClose")
            })
        return stocks

    def _attach_event_listener_lazy(self):
        """Lazily attaches event detector callback without circular module imports."""
        if self._event_callback is None:
            try:
                from app.market.event_detector import event_detector
                self.register_event_listener(event_detector.evaluate_tick)
            except (ImportError, AttributeError) as e:
                logger.debug(f"Event detector lazy registration: {e}")

    def poll_now(self) -> dict[str, Any]:
        """
        Executes an isolated, single-flight polling request for all 30 instruments.
        Guarantees:
        - Never launches concurrent duplicate polling requests.
        - Bounded retries with exponential backoff.
        - Validates response schemas strictly.
        """
        self._attach_event_listener_lazy()
        # Single-flight lock: if another thread is currently polling, do not launch a second poll
        if not self._polling_flight_lock.acquire(blocking=False):
            logger.debug("Polling request skipped: single-flight poll already in progress.")
            return {"status": "skipped", "reason": "in_flight"}

        try:
            return self._execute_poll()
        finally:
            self._polling_flight_lock.release()

    def _execute_poll(self) -> dict[str, Any]:
        now_utc = datetime.now(UTC)
        base_url = getattr(settings, "RAM_STOCK_API_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
        timeout = getattr(settings, "RAM_REQUEST_TIMEOUT_SECONDS", 6.0)
        max_retries = getattr(settings, "RAM_MAX_RETRIES", 3)
        backoff_factor = getattr(settings, "RAM_BACKOFF_FACTOR", 1.5)

        # Build symbol query string
        # Map NIFTY50 -> ^NSEI, others to clean symbol
        query_symbols = []
        for item in INITIAL_INSTRUMENT_CATALOG:
            sym = item["symbol"]
            if sym == "NIFTY50":
                query_symbols.append("^NSEI")
            else:
                query_symbols.append(sym)

        symbols_param = ",".join(query_symbols)
        target_url = f"{base_url}/stock/list?symbols={symbols_param}&res=num"

        stocks_data = None
        provider_ts_raw = None
        last_err = None
        poll_latency_ms = None

        # Try local/configured REST provider endpoint with bounded retries
        for attempt in range(max_retries):
            try:
                t_req_start = time.perf_counter()
                resp = requests.get(target_url, timeout=timeout)
                t_req_end = time.perf_counter()
                poll_latency_ms = round((t_req_end - t_req_start) * 1000, 2)
                if resp.status_code == 200:
                    body = resp.json()
                    if body.get("status") == "success" and isinstance(body.get("stocks"), list):
                        stocks_data = body["stocks"]
                        provider_ts_raw = body.get("timestamp")
                        break
                    else:
                        raise ValueError(f"Malformed 0xramm response: {body.get('message', 'missing stocks')}")
                elif resp.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {resp.status_code} from {base_url}")
                else:
                    raise RuntimeError(f"Unexpected HTTP {resp.status_code}: {resp.text[:100]}")
            except (requests.RequestException, TypeError, ValueError, RuntimeError, AttributeError) as e:
                last_err = e
                logger.warning(f"0xramm REST poll attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(backoff_factor ** attempt)

        source = "0XRAMM_REST_V3"
        provenance = "0xramm Indian Stock Market API (Provisional REST Adapter) — Yahoo Finance backed"
        # Fallback to embedded direct Yahoo fetch if configured and local provider was unreachable
        if not stocks_data and getattr(settings, "RAM_EMBEDDED_FALLBACK", True):
            try:
                logger.info("Attempting embedded direct Yahoo fallback for 0xramm adapter...")
                yahoo_tickers = [item["yahoo_ticker"] for item in INITIAL_INSTRUMENT_CATALOG]
                stocks_data = self._fetch_from_embedded_yahoo(yahoo_tickers)
                source = "YAHOO_FINANCE_EMBEDDED"
                provenance = "Yahoo Finance direct quote fallback"
                provider_ts_raw = None
                last_err = None
            except (requests.RequestException, TypeError, ValueError, RuntimeError, AttributeError) as fb_err:
                logger.error(f"Embedded Yahoo fallback also failed: {fb_err}")
                last_err = fb_err

        if not stocks_data:
            with self.lock:
                self.error_polls_count += 1
                self.error_message = str(last_err)
                if self.error_polls_count > max_retries:
                    self.connection_status = "ERROR"
            return {"status": "error", "error": str(last_err)}

        # Process and normalize quotes
        is_open, _session_msg = is_market_session_active(now_utc)
        fresh_quotes_count = 0
        current_quotes_snapshot = []
        ticks_to_buffer = []

        with self.lock:
            for item in stocks_data:
                raw_sym = str(item.get("symbol", "")).upper()
                ticker = str(item.get("ticker", "")).upper()

                # Map ^NSEI back to internal symbol NIFTY50
                if raw_sym == "^NSEI" or ticker == "^NSEI":
                    sym = "NIFTY50"
                else:
                    sym = raw_sym

                if sym not in self._catalog_map:
                    continue

                catalog_info = self._catalog_map[sym]
                raw_price = item.get("last_price")
                prev_close = float(item["previous_close"]) if item.get("previous_close") is not None and isinstance(item.get("previous_close"), (int, float)) else None

                # Validate numeric, positive, and finite price with outlier boundary check
                val_ok, val_err = validate_market_observation(sym, raw_price, prev_close=prev_close)
                if not val_ok:
                    logger.warning(f"Rejected invalid observation for {sym}: {val_err}")
                    continue

                price = float(raw_price)
                volume = int(item["volume"]) if item.get("volume") is not None and isinstance(item.get("volume"), (int, float)) else None
                change = float(item["change"]) if item.get("change") is not None and isinstance(item.get("change"), (int, float)) else None
                change_pct = float(item["percent_change"]) if item.get("percent_change") is not None and isinstance(item.get("percent_change"), (int, float)) else None
                open_p = float(item["open"]) if item.get("open") is not None and isinstance(item.get("open"), (int, float)) else None
                day_high = float(item["day_high"]) if item.get("day_high") is not None and isinstance(item.get("day_high"), (int, float)) else None
                day_low = float(item["day_low"]) if item.get("day_low") is not None and isinstance(item.get("day_low"), (int, float)) else None

                current_quotes_snapshot.append((sym, price, volume))

                # Freshness and price-type evaluation
                if is_open:
                    price_type = "LIVE_QUOTE"
                    freshness = "LIVE"
                    is_live = True
                else:
                    if prev_close and abs(price - prev_close) < 1e-4:
                        price_type = "OFFICIAL_SESSION_CLOSE"
                    else:
                        price_type = "LAST_SESSION_CLOSE"
                    freshness = "MARKET_CLOSED"
                    is_live = False

                source_ts_age_sec = None
                item_source_timestamp = provider_ts_raw
                observation_time = now_utc
                market_timestamp = None
                source_epoch = item.get("regular_market_time")
                if isinstance(source_epoch, (int, float)) and not isinstance(source_epoch, bool):
                    try:
                        observation_time = datetime.fromtimestamp(source_epoch, tz=UTC)
                        market_timestamp = observation_time.isoformat()
                        item_source_timestamp = market_timestamp
                    except (ValueError, OverflowError, OSError):
                        logger.debug("Ignoring out-of-range upstream quote timestamp for %s", sym)
                if item_source_timestamp:
                    try:
                        pts = datetime.fromisoformat(item_source_timestamp.replace(" ", "T"))
                        if pts.tzinfo is None:
                            pts = pts.replace(tzinfo=UTC)
                        source_ts_age_sec = round((now_utc - pts).total_seconds(), 1)
                    except (TypeError, ValueError):
                        source_ts_age_sec = None
                if (source == "YAHOO_FINANCE_EMBEDDED" or market_timestamp) and is_open and (
                    source_ts_age_sec is None or not 0 <= source_ts_age_sec <= settings.RAM_STALENESS_THRESHOLD_SECONDS
                ):
                    price_type, freshness, is_live = "LAST_OBSERVED_PRICE", "STALE", False

                normalized_quote = {
                    "symbol": sym,
                    "security_id": catalog_info["security_id"],
                    "name": catalog_info["name"],
                    "exchange_segment": catalog_info["exchange_segment"],
                    "price": price,
                    "previous": prev_close,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": volume,
                    "open": open_p,
                    "high": day_high,
                    "low": day_low,
                    "close": prev_close,
                    "source": source,
                    "provenance": provenance,
                    "provider_timestamp": item_source_timestamp,
                    "market_timestamp": market_timestamp,
                    "source_timestamp": item_source_timestamp,
                    "source_timestamp_age_seconds": source_ts_age_sec,
                    "ingestion_timestamp": now_utc.isoformat(),
                    "observation_timestamp": (observation_time.isoformat() if item_source_timestamp or source != "YAHOO_FINANCE_EMBEDDED" else None),
                    "polling_request_latency_ms": poll_latency_ms,
                    "source_value_cadence_seconds": getattr(settings, "RAM_POLL_INTERVAL_SECONDS", 15.0),
                    "feed_cadence_type": "DISCRETE_POLLING_15S",
                    "streaming_guarantee": "NONE (Discrete REST Polling via 0xramm; not exchange streaming)",
                    "observation_time_status": "VERIFIED_UPSTREAM_TIME" if market_timestamp else "UNVERIFIED_PROVIDER_TIME",
                    "observation_type": "LIVE_TICK" if is_live else "LAST_OBSERVED_PRICE",
                    "price_type": price_type,
                    "market_status": "OPEN" if is_open else "CLOSED",
                    "feed_status": freshness,
                    "last_completed_session_date": get_last_completed_trading_session_date(now_utc),
                    "timezone": "Asia/Kolkata",
                    "is_live": is_live,
                    "freshness_status": freshness,
                    "mode": "LIVE_ONLY",
                    "packet_type": "POLLING_REST"
                }

                self.last_poll_latency_ms = poll_latency_ms
                self.last_source_ts_age_sec = source_ts_age_sec

                self._cache[sym] = normalized_quote
                fresh_quotes_count += 1

                # Persist snapshot for market-closed resilience
                try:
                    persist_snapshot(
                        symbol=sym,
                        price=price,
                        open_p=open_p,
                        high_p=day_high,
                        low_p=day_low,
                        close_p=prev_close if prev_close else price,
                        previous_close=prev_close,
                        volume=volume,
                        price_type=price_type,
                        market_status="OPEN" if is_open else "CLOSED",
                        feed_status=freshness,
                        source=source,
                        observation_timestamp=observation_time,
                        provider_timestamp=item_source_timestamp,
                        extra_data={"ticker": item.get("ticker")}
                    )
                except SQLAlchemyError as snap_err:
                    logger.debug(f"Snapshot persistence error for {sym}: {snap_err}")

                # Update live ticks window for indicators
                if is_live:
                    if sym not in self._live_ticks:
                        self._live_ticks[sym] = []
                    self._live_ticks[sym].append(price)
                    if len(self._live_ticks[sym]) > 200:
                        self._live_ticks[sym].pop(0)

                # Add observation to candle aggregator
                src_dt = None
                if provider_ts_raw:
                    try:
                        src_dt = datetime.fromisoformat(provider_ts_raw.replace(" ", "T")).replace(tzinfo=IST_OFFSET)
                    except (TypeError, ValueError):
                        src_dt = None
                self.candle_aggregator.add_observation(sym, price, volume, now_utc, source_timestamp=src_dt)

                ticks_to_buffer.append(normalized_quote)

            # Check if quote values are identical across polls to detect provider staleness
            current_hash = str(hash(tuple(sorted(current_quotes_snapshot))))
            if self._last_quotes_hash and self._last_quotes_hash == current_hash and is_open:
                self.consecutive_unchanged_count += 1
            else:
                self.consecutive_unchanged_count = 0
            self._last_quotes_hash = current_hash

            self.valid_polls_count += 1
            self.last_poll_at = now_utc
            self.last_provider_timestamp = provider_ts_raw
            self.last_ingestion_timestamp = now_utc
            self.error_message = None
            self.connection_status = "LIVE" if is_open else "MARKET_CLOSED"

        # Dispatch event detector notifications asynchronously strictly during open market sessions
        if self._event_callback and ticks_to_buffer and is_open:
            for q in ticks_to_buffer:
                try:
                    self._event_callback(q)
                except Exception as cb_err:
                    logger.exception("Unexpected failure at the service boundary")
                    logger.debug(f"Event detector callback error on {q['symbol']}: {cb_err}")

        # Batch persistence of quotes to SQLite Quote table
        self._persist_quotes_batch(ticks_to_buffer, now_utc)

        return {
            "status": "success",
            "count": fresh_quotes_count,
            "provider_timestamp": provider_ts_raw,
            "ingested_at": now_utc.isoformat(),
            "feed_status": self.connection_status
        }

    def _persist_quotes_batch(self, quotes: list[dict[str, Any]], now_utc: datetime):
        """Safely updates latest Quote table in SQLite without locking."""
        try:
            with SessionLocal() as db:
                for q in quotes:
                    q_rec = db.query(Quote).filter(Quote.symbol == q["symbol"]).first()
                    prev_val = q.get("previous")
                    if prev_val is None:
                        change_val = q.get("change") or 0.0
                        prev_val = round(float(q["price"] - change_val), 2)

                    if q_rec:
                        q_rec.price = q["price"]
                        if q.get("volume") is not None and q["volume"] > 0:
                            q_rec.volume = q["volume"]
                        if q.get("change") is not None:
                            q_rec.change = q["change"]
                        if q.get("change_pct") is not None:
                            q_rec.change_pct = q["change_pct"]
                        if prev_val is not None:
                            q_rec.previous = prev_val
                        q_rec.price_type = q.get("price_type", "LIVE_QUOTE")
                        q_rec.observation_timestamp = now_utc
                        q_rec.source = q.get("source", "0XRAMM_REST_V3")
                        q_rec.freshness_status = q.get("freshness_status", "LIVE")
                        q_rec.market_status = q.get("market_status", "OPEN")
                        q_rec.timestamp = now_utc
                    else:
                        db.add(Quote(
                            symbol=q["symbol"],
                            price=q["price"],
                            previous=prev_val,
                            change=q.get("change") or 0.0,
                            change_pct=q.get("change_pct") or 0.0,
                            volume=q.get("volume") or 0,
                            price_type=q.get("price_type", "LIVE_QUOTE"),
                            observation_timestamp=now_utc,
                            source=q.get("source", "0XRAMM_REST_V3"),
                            freshness_status=q.get("freshness_status", "LIVE"),
                            market_status=q.get("market_status", "OPEN"),
                            timestamp=now_utc
                        ))
                db.commit()
        except SQLAlchemyError as e:
            logger.debug(f"Error persisting quotes to SQLite: {e}")

    def _polling_loop(self):
        """Background polling loop thread."""
        logger.info("0xramm Indian Stock Market API polling worker started.")
        while self._running:
            try:
                feed_enabled = getattr(settings, "RAM_FEED_ENABLED", True)
                if feed_enabled:
                    self.poll_now()
            except Exception as e:
                logger.exception("Unexpected failure at the service boundary")
                logger.error(f"Error in 0xramm polling loop: {e}")

            interval = getattr(settings, "RAM_POLL_INTERVAL_SECONDS", 20.0)
            time.sleep(interval)

    def start(self):
        """Starts background polling worker thread."""
        feed_enabled = getattr(settings, "RAM_FEED_ENABLED", True)
        if not feed_enabled:
            logger.info("0xramm adapter not started: RAM_FEED_ENABLED is False.")
            self.connection_status = "UNAVAILABLE"
            return

        with self.lock:
            if self._running:
                return
            self._running = True

        self._poll_thread = threading.Thread(target=self._polling_loop, daemon=True, name="RammMarketPoller")
        self._poll_thread.start()
        logger.info("0xramm provisional market-data adapter started successfully.")

    def stop(self):
        """Gracefully stops background polling worker."""
        with self.lock:
            self._running = False
            self.connection_status = "DISCONNECTED"
        logger.info("0xramm provisional market-data adapter stopped gracefully.")


# Global thread-safe singleton
ramm_market_feed = RammStockAdapter()
