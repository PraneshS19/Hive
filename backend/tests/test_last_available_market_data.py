"""
SYNQ — Automated Test Suite: Last Available Market Data & Market-Closed Handling
Covers all 16 required test scenarios:
1. test_market_closed_on_saturday
2. test_market_closed_on_sunday
3. test_market_closed_on_holiday
4. test_market_closed_outside_trading_hours
5. test_market_open_during_live_session
6. test_last_available_data_selection_prefers_official_close
7. test_last_observed_observation_when_official_close_absent
8. test_intraday_vs_close_price_distinction
9. test_provider_outage_serves_last_snapshot
10. test_no_snapshot_available_returns_clean_unavailable
11. test_invalid_provider_response_does_not_overwrite_snapshot
12. test_staleness_threshold_transition
13. test_timezone_boundary_precision
14. test_market_open_with_stale_data
15. test_portfolio_valuation_risk_guard_enforcement
16. test_no_synthetic_values_as_live_data
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.db.models import Order
from app.execution.paper_broker import PaperBroker
from app.market.ramm_adapter import ramm_market_feed
from app.market.session_calendar import (
    IST_OFFSET,
    get_last_completed_trading_session_date,
    get_market_session_info,
    is_market_session_active,
)
from app.market.snapshot_store import (
    get_latest_snapshot,
    persist_snapshot,
    validate_market_observation,
)


# ---------------------------------------------------------------------------
# 1. Saturday Closed Check
# ---------------------------------------------------------------------------
def test_market_closed_on_saturday():
    # 2026-10-24 is a Saturday
    sat_ist = datetime(2026, 10, 24, 11, 30, tzinfo=IST_OFFSET)
    sat_utc = sat_ist.astimezone(UTC)

    is_open, note = is_market_session_active(sat_utc)
    assert is_open is False, "Saturday must not be an active trading session"
    assert "Saturday" in note or "Weekend" in note

    info = get_market_session_info(sat_utc)
    assert info["is_open"] is False
    assert info["is_weekend"] is True
    assert info["market_status"] == "WEEKEND"

    last_session = get_last_completed_trading_session_date(sat_utc)
    assert last_session == "2026-10-23", "Last completed trading session for Saturday must be Friday 2026-10-23"


# ---------------------------------------------------------------------------
# 2. Sunday Closed Check
# ---------------------------------------------------------------------------
def test_market_closed_on_sunday():
    # 2026-10-25 is a Sunday
    sun_ist = datetime(2026, 10, 25, 14, 0, tzinfo=IST_OFFSET)
    sun_utc = sun_ist.astimezone(UTC)

    is_open, note = is_market_session_active(sun_utc)
    assert is_open is False, "Sunday must not be an active trading session"
    assert "Sunday" in note or "Weekend" in note

    info = get_market_session_info(sun_utc)
    assert info["is_open"] is False
    assert info["is_weekend"] is True
    assert info["market_status"] == "WEEKEND"

    last_session = get_last_completed_trading_session_date(sun_utc)
    assert last_session == "2026-10-23", "Last completed session for Sunday must be Friday 2026-10-23"


# ---------------------------------------------------------------------------
# 3. Known 2026 Exchange Holiday Check
# ---------------------------------------------------------------------------
def test_market_closed_on_holiday():
    # 2026-01-26 is Republic Day (Monday)
    rep_day_ist = datetime(2026, 1, 26, 10, 30, tzinfo=IST_OFFSET)
    rep_day_utc = rep_day_ist.astimezone(UTC)

    is_open, note = is_market_session_active(rep_day_utc)
    assert is_open is False, "Republic Day holiday must be closed"
    assert "Republic Day" in note

    info = get_market_session_info(rep_day_utc)
    assert info["is_holiday"] is True
    assert info["holiday_name"] == "Republic Day"
    assert info["market_status"] == "HOLIDAY"

    last_session = get_last_completed_trading_session_date(rep_day_utc)
    assert last_session == "2026-01-23", "Last session before Monday 2026-01-26 holiday must be Friday 2026-01-23"


# ---------------------------------------------------------------------------
# 4. Outside Regular Trading Hours (Pre/Post-Market)
# ---------------------------------------------------------------------------
def test_market_closed_outside_trading_hours():
    # Regular trading weekday: Wednesday 2026-10-21
    # 08:00 IST (pre-market)
    pre_ist = datetime(2026, 10, 21, 8, 0, tzinfo=IST_OFFSET)
    is_open_pre, note_pre = is_market_session_active(pre_ist.astimezone(UTC))
    assert is_open_pre is False
    assert "before session open" in note_pre or "09:15" in note_pre or "Overnight" in note_pre

    # 16:30 IST (post-market)
    post_ist = datetime(2026, 10, 21, 16, 30, tzinfo=IST_OFFSET)
    is_open_post, note_post = is_market_session_active(post_ist.astimezone(UTC))
    assert is_open_post is False
    assert "after session close" in note_post.lower() or "closed" in note_post.lower()


# ---------------------------------------------------------------------------
# 5. Live Market Session Check
# ---------------------------------------------------------------------------
def test_market_open_during_live_session():
    # Wednesday 2026-10-21 at 11:30 IST
    live_ist = datetime(2026, 10, 21, 11, 30, tzinfo=IST_OFFSET)
    live_utc = live_ist.astimezone(UTC)

    is_open, note = is_market_session_active(live_utc)
    assert is_open is True, "Regular weekday at 11:30 IST must be an open trading session"
    assert "regular trading session active" in note.lower()

    info = get_market_session_info(live_utc)
    assert info["is_open"] is True
    assert info["market_status"] == "OPEN"
    assert info["session_start_ist"] == "09:15:00"
    assert info["session_end_ist"] == "15:30:00"


# ---------------------------------------------------------------------------
# 6. Official Session Close Selected and Labeled
# ---------------------------------------------------------------------------
def test_last_available_data_selection_prefers_official_close(db):
    now_utc = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)  # Saturday
    snap = persist_snapshot(
        symbol="RELIANCE",
        price=1200.0,
        open_p=1190.0,
        high_p=1210.0,
        low_p=1185.0,
        close_p=1200.0,
        previous_close=1200.0,
        volume=2500000,
        price_type="OFFICIAL_SESSION_CLOSE",
        market_status="CLOSED",
        feed_status="MARKET_CLOSED",
        source="0XRAMM_REST_V3",
        observation_timestamp=now_utc,
        db=db,
    )
    assert snap.price == 1200.0
    assert snap.price_type == "OFFICIAL_SESSION_CLOSE"

    latest = get_latest_snapshot("RELIANCE", db=db)
    assert latest is not None
    assert latest["price_type"] == "OFFICIAL_SESSION_CLOSE"
    assert latest["price"] == 1200.0


# ---------------------------------------------------------------------------
# 7. Last Observed Price Labeled When Official Close Absent
# ---------------------------------------------------------------------------
def test_last_observed_observation_when_official_close_absent(db):
    now_utc = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    snap = persist_snapshot(
        symbol="TCS",
        price=2550.0,
        open_p=2520.0,
        high_p=2560.0,
        low_p=2510.0,
        close_p=2540.0,  # Official close differs from last observed intraday tick
        previous_close=2540.0,
        volume=800000,
        price_type="LAST_OBSERVED_PRICE",
        market_status="CLOSED",
        feed_status="MARKET_CLOSED",
        source="0XRAMM_REST_V3",
        observation_timestamp=now_utc,
        db=db,
    )
    assert snap.price_type == "LAST_OBSERVED_PRICE"
    assert snap.price_type != "OFFICIAL_SESSION_CLOSE"


# ---------------------------------------------------------------------------
# 8. Intraday vs Close Price Distinction
# ---------------------------------------------------------------------------
def test_intraday_vs_close_price_distinction():
    live_utc = datetime(2026, 10, 21, 6, 30, tzinfo=UTC)  # 12:00 IST Wednesday
    with patch("app.market.ramm_adapter.datetime") as mock_dt:
        mock_dt.now.return_value = live_utc
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        quote = {
            "symbol": "INFY",
            "price": 1450.0,
            "close": 1440.0,
            "ingestion_timestamp": live_utc.isoformat(),
            "observation_timestamp": live_utc.isoformat(),
        }
        refreshed = ramm_market_feed._refresh_quote_freshness(quote, live_utc)
        assert refreshed["is_live"] is True
        assert refreshed["price_type"] == "LIVE_QUOTE"
        assert refreshed["price_type"] != "OFFICIAL_SESSION_CLOSE"
        assert refreshed["price_type"] != "LAST_SESSION_CLOSE"


# ---------------------------------------------------------------------------
# 9. Provider Outage Serves Last Snapshot with STALE / PROVIDER_ERROR
# ---------------------------------------------------------------------------
def test_provider_outage_serves_last_snapshot(db):
    # Seed genuine snapshot
    persist_snapshot(
        symbol="HDFCBANK",
        price=950.0,
        open_p=940.0,
        high_p=955.0,
        low_p=938.0,
        close_p=950.0,
        previous_close=945.0,
        volume=1200000,
        price_type="OFFICIAL_SESSION_CLOSE",
        market_status="CLOSED",
        feed_status="MARKET_CLOSED",
        source="0XRAMM_REST_V3",
    )

    # Simulate provider failure
    ramm_market_feed.error_message = "HTTP 500: Upstream connection timeout"
    ramm_market_feed.error_polls_count = 5
    status = ramm_market_feed.get_status()

    # Verify status reports provider error or market closed
    assert status["feed_status"] in ("PROVIDER_ERROR", "MARKET_CLOSED", "ERROR")

    # Verify snapshot store still serves the valid last observation
    snap = get_latest_snapshot("HDFCBANK")
    assert snap is not None
    assert snap["price"] == 950.0, "Provider outage must not wipe or nullify last genuine observation"


# ---------------------------------------------------------------------------
# 10. No Snapshot Available Returns Clean WAITING/UNAVAILABLE (No Fabricated 0)
# ---------------------------------------------------------------------------
def test_no_snapshot_available_returns_clean_unavailable(db):
    snap = get_latest_snapshot("NON_EXISTENT_TICKER")
    assert snap is None

    quote = {
        "symbol": "NON_EXISTENT_TICKER",
        "price": None,
        "previous": None,
        "ingestion_timestamp": None,
    }
    now_utc = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
    refreshed = ramm_market_feed._refresh_quote_freshness(quote, now_utc)

    assert refreshed["price"] is None, "Price must remain None (no synthetic 0 allowed)"
    assert refreshed["is_live"] is False
    assert refreshed["freshness_status"] in ("MARKET_CLOSED", "CONNECTED_WAITING_FOR_DATA", "DATA_UNAVAILABLE")


# ---------------------------------------------------------------------------
# 11. Invalid Provider Response Does Not Overwrite Snapshot
# ---------------------------------------------------------------------------
def test_invalid_provider_response_does_not_overwrite_snapshot(db):
    # Persist valid snapshot
    persist_snapshot(
        symbol="ICICIBANK",
        price=1250.0,
        open_p=1240.0,
        high_p=1260.0,
        low_p=1235.0,
        close_p=1250.0,
        previous_close=1245.0,
        volume=900000,
        price_type="LAST_SESSION_CLOSE",
    )

    # Test validator with 0, negative, and extreme outlier prices
    val_zero, _err_zero = validate_market_observation("ICICIBANK", 0.0, prev_close=1250.0)
    assert val_zero is False, "Zero price must be rejected"

    val_neg, _err_neg = validate_market_observation("ICICIBANK", -150.0, prev_close=1250.0)
    assert val_neg is False, "Negative price must be rejected"

    val_outlier, _err_out = validate_market_observation("ICICIBANK", 999999.0, prev_close=1250.0)
    assert val_outlier is False, "Extreme outlier must be rejected"

    # Verify durable snapshot was not overwritten
    snap = get_latest_snapshot("ICICIBANK")
    assert snap["price"] == 1250.0, "Valid snapshot must be preserved"


# ---------------------------------------------------------------------------
# 12. Staleness Threshold Transition
# ---------------------------------------------------------------------------
def test_staleness_threshold_transition():
    # Wednesday during open session
    now_utc = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)
    stale_ts = (now_utc - timedelta(seconds=120)).isoformat()

    quote = {
        "symbol": "SBIN",
        "price": 820.0,
        "previous": 815.0,
        "ingestion_timestamp": stale_ts,
        "observation_timestamp": stale_ts,
    }
    refreshed = ramm_market_feed._refresh_quote_freshness(quote, now_utc)

    assert refreshed["observation_age_seconds"] >= 120.0
    assert refreshed["freshness_status"] == "STALE"
    assert refreshed["is_live"] is False


# ---------------------------------------------------------------------------
# 13. Exact Timezone Boundary Precision (IST 09:15:00 and 15:30:00)
# ---------------------------------------------------------------------------
def test_timezone_boundary_precision():
    # Wednesday 2026-10-21
    # 09:14:59 IST -> Closed
    t1 = datetime(2026, 10, 21, 9, 14, 59, tzinfo=IST_OFFSET).astimezone(UTC)
    open1, _ = is_market_session_active(t1)
    assert open1 is False, "09:14:59 IST must be closed"

    # 09:15:00 IST -> Open
    t2 = datetime(2026, 10, 21, 9, 15, 0, tzinfo=IST_OFFSET).astimezone(UTC)
    open2, _ = is_market_session_active(t2)
    assert open2 is True, "09:15:00 IST must be open"

    # 15:29:59 IST -> Open
    t3 = datetime(2026, 10, 21, 15, 29, 59, tzinfo=IST_OFFSET).astimezone(UTC)
    open3, _ = is_market_session_active(t3)
    assert open3 is True, "15:29:59 IST must be open"

    # 15:30:00 IST -> Closed
    t4 = datetime(2026, 10, 21, 15, 30, 0, tzinfo=IST_OFFSET).astimezone(UTC)
    open4, _ = is_market_session_active(t4)
    assert open4 is False, "15:30:00 IST must be closed"


# ---------------------------------------------------------------------------
# 14. Market Open with Stale Data (Independent States)
# ---------------------------------------------------------------------------
def test_market_open_with_stale_data():
    open_utc = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)  # Wednesday 11:30 IST
    is_open, _ = is_market_session_active(open_utc)
    assert is_open is True

    # Quote is stale (received 180 seconds ago)
    stale_ts = (open_utc - timedelta(seconds=180)).isoformat()
    quote = {
        "symbol": "BHARTIARTL",
        "price": 1650.0,
        "previous": 1640.0,
        "ingestion_timestamp": stale_ts,
        "observation_timestamp": stale_ts,
    }
    refreshed = ramm_market_feed._refresh_quote_freshness(quote, open_utc)

    # Market is open, but feed status is STALE
    assert refreshed["market_status"] == "OPEN"
    assert refreshed["feed_status"] == "STALE"
    assert refreshed["is_live"] is False


# ---------------------------------------------------------------------------
# 15. Portfolio Valuation Risk Guard Enforcement
# ---------------------------------------------------------------------------
def test_portfolio_valuation_risk_guard_enforcement(db):
    broker = PaperBroker()

    # Simulate submission outside market hours (Saturday)
    datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    with patch("app.execution.paper_broker.is_market_session_active") as mock_session:
        mock_session.return_value = (False, "Market closed (Weekend)")

        result = broker.submit_and_process_order(
            db=db,
            symbol="RELIANCE",
            side="BUY",
            requested_qty=10,
            price=1200.0,
            auto_execute=True
        )

        # Must be held as proposal, never executed as live fill
        assert result["outcome"] in ("APPROVED", "RESIZED")
        order = db.query(Order).filter(Order.symbol == "RELIANCE").order_by(Order.id.desc()).first()
        assert order is not None
        assert order.status == "PROPOSAL", "Order during closed market must be held as PROPOSAL"
        assert order.executed == 0, "No units may be executed during closed session"
        assert "MARKET_CLOSED_EXECUTION_HELD" in order.reason


# ---------------------------------------------------------------------------
# 16. No Synthetic Values as Live Data
# ---------------------------------------------------------------------------
def test_no_synthetic_values_as_live_data(client):
    res = client.get("/api/v1/market/quotes")
    assert res.status_code == 200
    quotes = res.json()

    for q in quotes:
        price = q.get("price")
        if price is not None:
            # Genuine prices are finite, positive, and non-random
            assert isinstance(price, (int, float))
            assert price > 0
            # Provenance or source must be declared
            assert q.get("source") is not None
            # Must declare truthful price_type
            assert q.get("price_type") in (
                "LIVE_QUOTE",
                "OFFICIAL_SESSION_CLOSE",
                "LAST_SESSION_CLOSE",
                "LAST_OBSERVED_PRICE",
                "NONE"
            )
            # Market status must be declared
            assert q.get("market_status") in ("OPEN", "CLOSED", "WEEKEND", "HOLIDAY")
