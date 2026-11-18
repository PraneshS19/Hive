from datetime import datetime

from app.market.dhan_adapter import IST_OFFSET, DhanLiveFeedAdapter, is_market_session_active


def test_dhan_catalog_and_instruments():
    adapter = DhanLiveFeedAdapter()
    watchlist = adapter.get_watchlist()
    assert len(watchlist) >= 30

    symbols = [inst["symbol"] for inst in watchlist]
    assert "RELIANCE" in symbols
    assert "TCS" in symbols
    assert "INFY" in symbols
    assert "HDFCBANK" in symbols
    assert "NIFTY50" in symbols

    sec_id = adapter._symbol_to_sec.get("RELIANCE")
    assert sec_id == "2885"

def test_market_session_active_function():
    # Sunday at 11:00 AM IST
    sunday_dt = datetime(2026, 10, 18, 11, 0, 0, tzinfo=IST_OFFSET)
    is_open, msg = is_market_session_active(sunday_dt)
    assert is_open is False
    assert "Weekend" in msg

    # Monday at 08:30 AM IST (Overnight before 09:00 pre-open)
    mon_early = datetime(2026, 10, 19, 8, 30, 0, tzinfo=IST_OFFSET)
    is_open, msg = is_market_session_active(mon_early)
    assert is_open is False
    assert "Overnight: Market Closed" in msg

    # Monday at 09:05 AM IST (Pre-Open session: 09:00-09:15)
    mon_preopen = datetime(2026, 10, 19, 9, 5, 0, tzinfo=IST_OFFSET)
    is_open, msg = is_market_session_active(mon_preopen)
    assert is_open is False
    assert "Pre-Open Session Active" in msg

    # Monday at 11:30 AM IST (during regular trading session: 09:15-15:30)
    mon_open = datetime(2026, 10, 19, 11, 30, 0, tzinfo=IST_OFFSET)
    is_open, msg = is_market_session_active(mon_open)
    assert is_open is True
    assert "Regular Trading Session Active" in msg

    # Monday at 16:30 PM IST (after 16:00 close)
    mon_after = datetime(2026, 10, 19, 16, 30, 0, tzinfo=IST_OFFSET)
    is_open, msg = is_market_session_active(mon_after)
    assert is_open is False
    assert "Overnight: Market Closed" in msg

def test_feed_status_and_tick_normalization():
    adapter = DhanLiveFeedAdapter()

    # Status verification
    status = adapter.get_status()
    assert "status" in status
    assert status["active_subscriptions"] >= 30
    assert status["staleness_threshold_seconds"] == 15.0
    assert status["provider"] == "DhanHQ-py (v2.3.0)"

    # Ingest a mock packet for RELIANCE (sec_id: "2885")
    packet = {
        "type": "Quote Data",
        "security_id": "2885",
        "LTP": 1234.50,
        "volume": 2500000,
        "open": 1210.0,
        "high": 1240.0,
        "low": 1208.0,
        "close": 1211.70,
    }
    adapter.normalize_and_ingest_tick(packet)

    quote = adapter.get_quote("RELIANCE")
    assert quote is not None
    assert quote["symbol"] == "RELIANCE"
    assert quote["price"] == 1234.50
    assert quote["volume"] == 2500000
    assert "DhanHQ" in quote["provenance"]
    assert quote["source"] == "DHAN_MARKETFEED_V2"
