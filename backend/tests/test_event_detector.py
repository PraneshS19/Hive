from app.market.event_detector import DeterministicEventDetector


def test_price_surge_detection(db):
    detector = DeterministicEventDetector()

    # Baseline tick
    detector.evaluate_tick({
        "symbol": "RELIANCE",
        "price": 1200.0,
        "previous": 1200.0,
        "change_pct": 0.0,
        "volume": 10000,
        "security_id": "2885"
    })

    # +4.17% surge over live baseline
    tick = {
        "symbol": "RELIANCE",
        "price": 1250.0,
        "previous": 1200.0,
        "change_pct": 4.17,
        "volume": 50000,
        "security_id": "2885"
    }

    event = detector.evaluate_tick(tick)
    assert event is not None
    assert event["event_type"] == "PRICE_SURGE"
    assert event["symbol"] == "RELIANCE"
    assert event["severity"] >= 50
    assert "Intraday Price Surge" in event["headline"]
    assert "snapshot_id" in event

def test_event_cooldown_deduplication(db):
    detector = DeterministicEventDetector()

    # Baseline tick
    detector.evaluate_tick({
        "symbol": "INFY",
        "price": 1200.0,
        "previous": 1200.0,
        "change_pct": 0.0,
        "volume": 10000,
        "security_id": "1594"
    })

    tick = {
        "symbol": "INFY",
        "price": 1250.0,
        "previous": 1200.0,
        "change_pct": 4.17,
        "volume": 50000,
        "security_id": "1594"
    }

    # First trigger should succeed
    e1 = detector.evaluate_tick(tick)
    assert e1 is not None

    # Immediate second evaluation on same symbol should be throttled by 60s cooldown
    e2 = detector.evaluate_tick(tick)
    assert e2 is None

def test_user_triggered_event(db):
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.normalize_and_ingest_tick({
        "security_id": "11536",
        "LTP": 2500.0,
        "prev_close": 2490.0,
        "volume": 50000,
        "LTT": 1729600000
    })
    detector = DeterministicEventDetector()
    event = detector.trigger_user_analysis_event(
        symbol="TCS",
        reason="Quarterly earnings surprise"
    )

    assert event is not None
    assert event["symbol"] == "TCS"
    assert event["event_type"] == "USER_TRIGGER"
    assert event["severity"] == 40
    assert "Quarterly earnings surprise" in event["headline"]
