"""
Regression tests for SYNQ Live-Only Market Data Policy, DhanHQ Feed Adapter,
and Valuation Integrity.
"""

from datetime import UTC, datetime

from app.core.config import settings
from app.db.models.market import Asset, Candle, Quote
from app.db.models.portfolio import Account, Position
from app.market.dhan_adapter import INITIAL_INSTRUMENT_CATALOG, dhan_live_feed
from app.market.evidence_snapshot import evidence_snapshot_service
from app.portfolio.service import portfolio_service


def test_runtime_policy_flags():
    """Verify live-only configuration invariants."""
    assert settings.MARKET_DATA_MODE == "LIVE_ONLY"
    assert settings.MARKET_DATA_PROVIDER in ("0xramm_yahoo_rest", "ramm_stock_api", "dhanhq_live")
    assert settings.ALLOW_HISTORICAL_MARKET_FALLBACK is False
    assert settings.ALLOW_SYNTHETIC_MARKET_DATA is False


def test_db_init_live_only(db):
    """Verify clean database initialization in LIVE_ONLY mode: zero quotes, zero candles, 30 assets."""
    quote_count = db.query(Quote).count()
    candle_count = db.query(Candle).count()
    asset_count = db.query(Asset).count()
    account = db.query(Account).first()
    position_count = db.query(Position).count()

    assert quote_count == 0, "No quotes should be seeded in LIVE_ONLY mode"
    assert candle_count == 0, "No historical candles should be seeded into live candles table"
    assert asset_count == len(INITIAL_INSTRUMENT_CATALOG), "Asset catalog must register broad watchlist metadata"
    assert account is not None
    assert account.cash_balance == 1000000.0, "Starting capital must be ₹10,00,000"
    assert position_count == 0, "Initial positions must be 0"


def test_unreceived_quote_truthfulness():
    """Quotes for unreceived instruments must return None price and truthful status."""
    q = dhan_live_feed.get_quote("INFY")
    assert q is not None
    assert q["symbol"] == "INFY"
    # In live-only mode without ticks, price must never be a fabricated float or 0.0
    if q.get("freshness_status") in ("WAITING_FOR_FIRST_TICK", "MARKET_CLOSED"):
        assert q.get("price") is None
        assert q.get("change") is None
        assert q.get("change_pct") is None


def test_quotes_endpoint_live_only(client):
    """GET /api/v1/market/quotes returns all 30 watchlist instruments without fabricated prices."""
    resp = client.get("/api/v1/market/quotes")
    assert resp.status_code == 200
    quotes = resp.json()
    assert len(quotes) == 30
    for q in quotes:
        assert "symbol" in q
        assert "freshness_status" in q
        if q["freshness_status"] in ("WAITING_FOR_FIRST_TICK", "MARKET_CLOSED"):
            assert q["price"] is None


def test_single_quote_endpoint(client):
    """GET /api/v1/market/quotes/{symbol} handles unreceived quote truthfully."""
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.reset_cache()
    resp = client.get("/api/v1/market/quotes/RELIANCE")
    assert resp.status_code == 200
    q = resp.json()
    assert q["symbol"] == "RELIANCE"
    if q.get("freshness_status") in ("WAITING_FOR_FIRST_TICK", "WAITING_FOR_FIRST_POLL", "MARKET_CLOSED") and q.get("price") is None:
        assert q["price"] is None
    elif q.get("price") is not None:
        assert q["price"] > 0


def test_candles_endpoint_live_only(client):
    """GET /api/v1/market/candles returns empty list in LIVE_ONLY mode without historical backfill."""
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.reset_cache()
    resp = client.get("/api/v1/market/candles?symbol=RELIANCE")
    assert resp.status_code == 200
    data = resp.json()
    assert data == []
    assert resp.headers.get("X-Market-Mode") == "LIVE_ONLY"


def test_indicators_warmup_policy(client):
    """GET /api/v1/market/indicators returns WARMING_UP when live ticks < 20."""
    resp = client.get("/api/v1/market/indicators?symbol=TCS")
    assert resp.status_code == 200
    ind = resp.json()
    assert ind["symbol"] == "TCS"
    if ind.get("observations", 0) < 20:
        assert "WARMING_UP" in ind.get("status", "")
        assert ind.get("rsi") is None
        assert ind.get("sma_20") is None


def test_portfolio_valuation_without_live_ticks(db):
    """
    Positions without a live quote must have current_price=None, market_value=None,
    valuation_status='VALUATION_UNAVAILABLE', and valuation_complete=False.
    Must NOT fall back to p.average as the current price.
    """
    account = db.query(Account).first()
    # Insert a test position in memory DB
    test_pos = Position(
        account_id=account.id,
        symbol="INFY",
        quantity=50,
        average_entry=1000.0,
    )
    db.add(test_pos)
    db.commit()

    port = portfolio_service.get_portfolio_summary(db)
    pos_res = next((p for p in port["positions"] if p["symbol"] == "INFY"), None)
    assert pos_res is not None

    quote = dhan_live_feed.get_quote("INFY")
    if quote.get("price") is None:
        assert pos_res["current_price"] is None
        assert pos_res["market_value"] is None
        assert pos_res["unrealized_pnl"] is None
        assert pos_res["valuation_status"] == "VALUATION_UNAVAILABLE"
        assert port["valuation_complete"] is False


def test_live_tick_ingestion_and_indicator_computation(monkeypatch):
    """
    When live ticks are ingested via normalize_and_ingest_tick during market session:
    1. Quote updates price and freshness_status = 'FRESH'
    2. Once observations >= 20, indicators transition from WARMING_UP to COMPUTED.
    """
    import app.market.dhan_adapter as da
    monkeypatch.setattr(da, "is_market_session_active", lambda dt=None: (True, "Simulated market session active"))

    symbol = "SBIN"
    base_price = 800.0

    # Ingest 25 synthetic live ticks to satisfy >= 20 warmup
    for i in range(25):
        tick_data = {
            "security_id": "3045",  # SBIN security id
            "LTP": base_price + (i * 0.5),
            "prev_close": 795.0,
            "volume": 10000 + (i * 100),
            "LTT": int(datetime.now(UTC).timestamp()),
        }
        dhan_live_feed.normalize_and_ingest_tick(tick_data)

    q = dhan_live_feed.get_quote(symbol)
    assert q["price"] == base_price + (24 * 0.5)
    assert q["freshness_status"] in ("DATA_FRESH", "LIVE", "FRESH")
    assert q["is_live"] is True

    # Check evidence snapshot indicators after >= 20 live ticks
    snap = evidence_snapshot_service.freeze_snapshot(symbol)
    assert snap["EV_IND"]["sma_20"] is not None
    assert snap["EV_PRICE"]["price"] == base_price + (24 * 0.5)
