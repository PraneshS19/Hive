"""
Comprehensive Unit & Integration Test Suite for 0xramm Indian Stock Market API Provisional Adapter.
Tests:
1. Catalog initialization and symbol mappings (NIFTY50 -> ^NSEI, equities -> .NS)
2. Valid REST response ingestion & normalization
3. Malformed responses, negative prices, missing fields handling
4. Rate limiting, bounded retries, and exponential backoff
5. Stale data detection (identical quotes across consecutive polls)
6. Polling-derived candle aggregation (OHLC, non-cumulative volume delta, volume unavailability)
7. Single-flight lock preventing duplicate concurrent polling
8. Feed health status transitions (CONNECTING, LIVE, STALE, MARKET_CLOSED, DISCONNECTED, ERROR)
9. Truthful source and provenance labeling
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import requests
from app.core.config import settings
from app.market.ramm_adapter import PollingCandleAggregator, RammStockAdapter


def test_catalog_and_symbol_mappings():
    """Verify 30 instruments are cataloged and symbol mappings match Yahoo/0xramm tickers."""
    adapter = RammStockAdapter()
    assert len(adapter._catalog_map) >= 30

    # Verify NIFTY50 maps to ^NSEI
    assert adapter._symbol_to_ticker["NIFTY50"] == "^NSEI"
    assert adapter._ticker_to_symbol["^NSEI"] == "NIFTY50"

    # Verify major equities
    assert adapter._symbol_to_ticker["RELIANCE"] == "RELIANCE.NS"
    assert adapter._symbol_to_ticker["TCS"] == "TCS.NS"
    assert adapter._symbol_to_ticker["INFY"] == "INFY.NS"


def test_initial_catalog_freshness_truthful():
    """Verify that unpolled instruments have price=None and truthful initial freshness status."""
    adapter = RammStockAdapter()
    q = adapter.get_quote("RELIANCE")
    assert q is not None
    assert q["price"] is None
    assert q["volume"] is None
    assert q["is_live"] is False
    assert q["provenance"] == "0xramm Indian Stock Market API (Provisional REST Adapter) — Yahoo Finance backed"
    assert q["observation_time_status"] == "WAITING_FOR_FIRST_POLL"


def test_single_flight_polling_lock():
    """Verify that concurrent calls to poll_now do not execute simultaneous duplicate requests."""
    adapter = RammStockAdapter()

    # Acquire lock artificially to simulate a poll in flight
    acquired = adapter._polling_flight_lock.acquire(blocking=False)
    assert acquired is True

    # Secondary poll should detect in-flight lock and skip safely
    res = adapter.poll_now()
    assert res["status"] == "skipped"
    assert res["reason"] == "in_flight"

    adapter._polling_flight_lock.release()


def test_valid_response_normalization(monkeypatch):
    """Verify normalization of a valid 0xramm /stock/list payload."""
    import app.market.dhan_adapter as da
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (True, "Simulated market session active"))

    adapter = RammStockAdapter()
    market_time = datetime.now(UTC) - timedelta(seconds=1)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "response_format": "numeric_only",
        "count": 2,
        "stocks": [
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "ticker": "RELIANCE.NS",
                "company_name": "Reliance Industries Limited",
                "last_price": 1250.50,
                "regular_market_time": market_time.timestamp(),
                "change": 15.5,
                "percent_change": 1.25,
                "volume": 5500000,
                "open": 1235.0,
                "day_high": 1260.0,
                "day_low": 1230.0,
                "previous_close": 1235.0
            },
            {
                "symbol": "^NSEI",
                "exchange": "IDX",
                "ticker": "^NSEI",
                "company_name": "NIFTY 50",
                "last_price": 22600.0,
                "change": -50.0,
                "percent_change": -0.22,
                "volume": 0,
                "open": 22650.0,
                "day_high": 22700.0,
                "day_low": 22580.0,
                "previous_close": 22650.0
            }
        ],
        "timestamp": "2026-10-22 11:30:00"
    }

    with patch("requests.get", return_value=mock_response):
        result = adapter.poll_now()

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["provider_timestamp"] == "2026-10-22 11:30:00"

    # Verify RELIANCE quote
    rel = adapter.get_quote("RELIANCE")
    assert rel["price"] == 1250.50
    assert rel["change"] == 15.5
    assert rel["volume"] == 5500000
    assert rel["is_live"] is True
    assert rel["freshness_status"] in ("DATA_FRESH", "LIVE")
    assert rel["source"] == "0XRAMM_REST_V3"
    assert rel["market_timestamp"] == market_time.isoformat()
    assert rel["observation_time_status"] == "VERIFIED_UPSTREAM_TIME"

    # Verify NIFTY50 index mapping from ^NSEI
    nifty = adapter.get_quote("NIFTY50")
    assert nifty["price"] == 22600.0
    assert nifty["change"] == -50.0
    assert nifty["symbol"] == "NIFTY50"


def test_malformed_and_negative_prices_rejected(monkeypatch):
    """Verify that missing, negative, or malformed prices are rejected."""
    import app.market.dhan_adapter as da
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (True, "Simulated market session active"))

    adapter = RammStockAdapter()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "stocks": [
            {"symbol": "RELIANCE", "last_price": -500.0},      # Negative: rejected
            {"symbol": "TCS", "last_price": 0.0},              # Zero: rejected
            {"symbol": "INFY", "last_price": "invalid_num"},   # Non-numeric: rejected
            {"symbol": "HDFCBANK", "last_price": None},        # None: rejected
            {"symbol": "SBIN", "last_price": 820.0}            # Valid
        ]
    }

    with patch("requests.get", return_value=mock_response):
        result = adapter.poll_now()

    assert result["status"] == "success"
    assert result["count"] == 1  # Only SBIN accepted

    assert adapter.get_quote("RELIANCE")["price"] is None
    assert adapter.get_quote("TCS")["price"] is None
    assert adapter.get_quote("SBIN")["price"] == 820.0


def test_staleness_detection_on_unchanged_polls(monkeypatch):
    """Verify that unchanged quotes across 3 consecutive polls trigger STALE status during market hours."""
    import app.market.dhan_adapter as da
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (True, "Simulated market session active"))

    adapter = RammStockAdapter()

    identical_payload = {
        "status": "success",
        "stocks": [
            {"symbol": "RELIANCE", "last_price": 1200.0, "volume": 100000}
        ],
        "timestamp": "2026-10-22 11:00:00"
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = identical_payload

    with patch("requests.get", return_value=mock_resp):
        # Poll 1
        adapter.poll_now()
        assert adapter.consecutive_unchanged_count == 0
        assert adapter.get_status()["status"] in ("DATA_FRESH", "LIVE")

        # Poll 2 (unchanged)
        adapter.poll_now()
        assert adapter.consecutive_unchanged_count == 1

        # Poll 3 (unchanged)
        adapter.poll_now()
        assert adapter.consecutive_unchanged_count == 2

        # Poll 4 (unchanged >= 3 threshold)
        adapter.poll_now()
        assert adapter.consecutive_unchanged_count >= 3

        # Feed status transitions to STALE
        status = adapter.get_status()
        assert status["status"] == "STALE"
        assert "stale" in status["description"].lower()


def test_candle_aggregator_ohlc_and_volume_delta():
    """
    Verify candle aggregation logic:
    1. First sample = open, Max sample = high, Min sample = low, Last sample = close.
    2. Interval volume = end_cum_vol - start_cum_vol (NOT sum of volumes!).
    3. Labelled POLLING_DERIVED_APPROXIMATION.
    """
    aggregator = PollingCandleAggregator()
    base_time = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # 4 polling observations within the same 5-minute bucket [10:00 - 10:05]
    aggregator.add_observation("RELIANCE", 100.0, 1000, base_time + timedelta(seconds=10))   # Open: 100.0
    aggregator.add_observation("RELIANCE", 108.0, 1500, base_time + timedelta(seconds=60))   # High: 108.0
    aggregator.add_observation("RELIANCE", 96.0,  1800, base_time + timedelta(seconds=120))  # Low: 96.0
    aggregator.add_observation("RELIANCE", 104.0, 2200, base_time + timedelta(seconds=240))  # Close: 104.0

    candles = aggregator.get_aggregated_candles("RELIANCE", interval_minutes=5)
    assert len(candles) == 1
    c = candles[0]

    assert c["open"] == 100.0
    assert c["high"] == 108.0
    assert c["low"] == 96.0
    assert c["close"] == 104.0

    # Volume delta: 2200 - 1000 = 1200. (NOT 1000 + 1500 + 1800 + 2200 = 6500!)
    assert c["volume"] == 1200
    assert c["candle_type"] == "POLLING_DERIVED_APPROXIMATION"
    assert c["is_synthetic"] is False
    assert c["sample_count"] == 4


def test_candle_volume_marked_unavailable_when_unverified():
    """Verify interval volume is marked None when volume delta cannot be verified."""
    aggregator = PollingCandleAggregator()
    base_time = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Observation with missing volume
    aggregator.add_observation("RELIANCE", 100.0, None, base_time + timedelta(seconds=10))
    aggregator.add_observation("RELIANCE", 105.0, 2000, base_time + timedelta(seconds=60))

    candles = aggregator.get_aggregated_candles("RELIANCE", interval_minutes=5)
    assert len(candles) == 1
    assert candles[0]["volume"] is None


def test_feed_health_transitions(monkeypatch):
    """Verify transitions between feed states: CONNECTING/DISCONNECTED -> LIVE -> MARKET_CLOSED -> ERROR."""
    import app.market.dhan_adapter as da
    adapter = RammStockAdapter()

    # Initial state
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (True, "Open"))
    assert adapter.get_status()["status"] in ("DISCONNECTED", "CONNECTING")

    # Successful poll -> LIVE
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "stocks": [{"symbol": "RELIANCE", "last_price": 1200.0, "volume": 1000}]
    }
    with patch("requests.get", return_value=mock_resp):
        adapter.poll_now()
    assert adapter.get_status()["status"] in ("DATA_FRESH", "LIVE")

    # Session closed -> MARKET_CLOSED
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (False, "Closed at 15:30 IST"))
    assert adapter.get_status()["status"] == "MARKET_CLOSED"

    # Repeated poll failures exceeding max retries -> ERROR
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (True, "Open"))
    mock_err_resp = MagicMock()
    mock_err_resp.status_code = 500
    mock_err_resp.text = "Internal Server Error"
    with (
        patch("requests.get", return_value=mock_err_resp),
        patch.object(settings, "RAM_EMBEDDED_FALLBACK", False),
        patch("time.sleep", return_value=None),
    ):
        for _ in range(5):
            adapter.poll_now()

    assert adapter.get_status()["status"] in ("ERROR", "PROVIDER_ERROR")


def test_bounded_retry_and_backoff():
    """Verify bounded retry with exponential backoff on network failures."""
    adapter = RammStockAdapter()

    call_count = 0
    def mock_failing_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.ConnectionError("Connection refused")

    with (
        patch("requests.get", side_effect=mock_failing_get),
        patch.object(settings, "RAM_MAX_RETRIES", 3),
        patch.object(settings, "RAM_EMBEDDED_FALLBACK", False),
        patch("time.sleep", return_value=None) as mock_sleep,
    ):
        res = adapter.poll_now()
        assert res["status"] == "error"
        assert call_count == 3
        assert mock_sleep.call_count == 2


def test_embedded_quote_needs_a_fresh_upstream_timestamp(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.market import ramm_adapter

    adapter = ramm_adapter.RammStockAdapter()
    monkeypatch.setattr(ramm_adapter, "is_market_session_active", lambda dt=None: (True, "TEST_FIXTURE"))
    now = datetime.now(UTC)
    quote = {
        "symbol": "RELIANCE", "price": 100.0, "source": "YAHOO_FINANCE_EMBEDDED",
        "observation_timestamp": now.isoformat(),
    }
    assert adapter._refresh_quote_freshness(quote, now)["freshness_status"] == "STALE"
    quote["market_timestamp"] = (now - timedelta(days=1)).isoformat()
    assert adapter._refresh_quote_freshness(quote, now)["freshness_status"] == "STALE"
    quote["market_timestamp"] = (now - timedelta(seconds=1)).isoformat()
    assert adapter._refresh_quote_freshness(quote, now)["freshness_status"] == "LIVE"
