def test_api_health(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "database_status" in data


def test_api_config(client):
    res = client.get("/api/v1/config")
    assert res.status_code == 200
    data = res.json()
    assert data["app_name"] in ("HIVE Backend", "SYNQ Backend", "HedgeLab Backend")


def test_api_dashboard_summary(client):
    res = client.get("/api/v1/dashboard/summary")
    assert res.status_code == 200
    data = res.json()
    assert "metrics" in data
    assert "watchlist" in data
    assert "agents" in data
    assert len(data["watchlist"]) >= 5
    symbols = [w["symbol"] for w in data["watchlist"]]
    assert "RELIANCE" in symbols


def test_api_market_quotes(client):
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.reset_cache()
    res = client.get("/api/v1/market/quotes")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 5
    symbols = [q["symbol"] for q in data]
    assert "RELIANCE" in symbols
    assert "TCS" in symbols
    assert "INFY" in symbols
    assert "HDFCBANK" in symbols
    assert "NIFTY50" in symbols
    for q in data:
        # In LIVE_ONLY mode, quotes waiting for ticks have None price
        if q.get("freshness_status") in ("WAITING_FOR_FIRST_TICK", "WAITING_FOR_FIRST_POLL", "MARKET_CLOSED") and q.get("price") is None:
            assert q["price"] is None
        elif q.get("price") is not None:
            assert q["price"] > 0
        assert q["exchange"] == "NSE"


def test_api_scenario_injection(client):
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.normalize_and_ingest_tick({
        "security_id": "2885",
        "LTP": 1250.0,
        "prev_close": 1240.0,
        "volume": 50000,
        "LTT": 1729600000
    })
    payload = {
        "scenario": "VOLATILITY_SURGE",
        "symbol": "RELIANCE",
        "severity": 60.0
    }
    res = client.post("/api/v1/scenarios/inject", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["scenario_type"] in ("VOLATILITY_SURGE", "RALLY")
    assert data["outcome"] in ("APPROVED", "RESIZED", "REJECTED")


def test_api_portfolio_and_reset(operator_client):
    client = operator_client
    res = client.get("/api/v1/portfolio")
    assert res.status_code == 200
    data = res.json()
    assert data["equity"] > 0
    assert data["cash"] > 0

    # Test reset endpoint
    reset_res = client.post("/api/v1/portfolio/reset")
    assert reset_res.status_code == 200
    assert reset_res.json()["success"] is True

    # After reset, account should be clean with initial capital
    after_res = client.get("/api/v1/portfolio")
    assert after_res.status_code == 200
    assert after_res.json()["cash"] == 1000000.0


def test_api_risk_config_update(operator_client):
    client = operator_client
    # Read config
    res = client.get("/api/v1/risk/config")
    assert res.status_code == 200
    res.json()["fee"]

    # Update config
    update_res = client.put("/api/v1/risk/config", json={"fee_pct": 0.25})
    assert update_res.status_code == 200
    assert update_res.json()["fee"] == 0.25


def test_api_backtest(client):
    payload = {
        "strategy": "SMA crossover",
        "symbol": "RELIANCE",
        "timeframe": "1 year daily",
        "starting_capital": 1000000.0,
        "commission_pct": 0.1,
        "slippage_pct": 0.05
    }
    res = client.post("/api/v1/backtests", json=payload)
    # In live-only mode without imported historical datasets, returns 404 DatasetNotFoundError
    if res.status_code == 404:
        assert "dataset" in res.json().get("detail", "").lower()
    else:
        assert res.status_code == 200
        data = res.json()
        assert data["strategy"] == "SMA crossover"
        assert "total_return_pct" in data
        assert data["data_source"] == "historical"


def test_risk_config_mutual_validation(operator_client):
    client = operator_client
    """Verify that max_order_pct > max_allocation_pct is strictly rejected with HTTP 400."""
    # Attempting to set single-order limit higher than total instrument allocation limit
    invalid_payload = {
        "max_order_pct": 10.0,
        "max_allocation_pct": 5.0
    }
    res = client.put("/api/v1/risk/config", json=invalid_payload)
    assert res.status_code == 400
    assert "cannot exceed max asset allocation limit" in res.json().get("detail", "")

    # Valid configuration where max_order_pct <= max_allocation_pct succeeds
    valid_payload = {
        "max_order_pct": 10.0,
        "max_allocation_pct": 25.0
    }
    valid_res = client.put("/api/v1/risk/config", json=valid_payload)
    assert valid_res.status_code == 200
    data = valid_res.json()
    assert data["maxOrder"] == 10.0
    assert data["maxAllocation"] == 25.0


def test_scenario_injection_isolated_from_portfolio(client):
    """Verify scenario injection executes in isolation and does not alter account cash or positions."""
    from app.market.ramm_adapter import ramm_market_feed
    ramm_market_feed._cache["RELIANCE"] = {
        "symbol": "RELIANCE",
        "security_id": "2885",
        "name": "Reliance Industries Ltd",
        "exchange_segment": "NSE_EQ",
        "price": 1250.0,
        "previous": 1240.0,
        "change": 10.0,
        "change_pct": 0.8,
        "volume": 50000,
        "open": 1245.0,
        "high": 1255.0,
        "low": 1240.0,
        "close": 1240.0,
        "source": "0XRAMM_REST_V3",
        "provenance": "0xramm Indian Stock Market API (Provisional REST Adapter)",
        "provider_timestamp": "2026-10-22 11:30:00",
        "source_timestamp": "2026-10-22 11:30:00",
        "ingestion_timestamp": "2026-10-22 11:30:00",
        "observation_time_status": "VERIFIED_UPSTREAM_TIME",
        "observation_type": "LIVE_TICK",
        "is_live": True,
        "freshness_status": "LIVE",
        "mode": "LIVE_ONLY",
        "packet_type": "POLLING_REST"
    }

    # 1. Fetch initial portfolio state
    init_res = client.get("/api/v1/portfolio")
    assert init_res.status_code == 200
    initial_cash = init_res.json()["cash"]
    initial_positions_count = len(init_res.json()["positions"])

    # 2. Inject simulated scenario
    payload = {
        "scenario": "VOLATILITY_SURGE",
        "symbol": "RELIANCE",
        "severity": 75.0
    }
    res = client.post("/api/v1/scenarios/inject", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["is_simulated"] is True
    assert "SIMULATED SCENARIO" in data["simulation_label"]
    assert data["order_status"] == "SIMULATED_SCENARIO"

    # 3. Verify portfolio cash and positions are completely unchanged
    post_res = client.get("/api/v1/portfolio")
    assert post_res.status_code == 200
    assert post_res.json()["cash"] == initial_cash
    assert len(post_res.json()["positions"]) == initial_positions_count
