import json
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
FRONTEND_PROXY_URL = "http://localhost:5173"

def http_req(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data else None
    try:
        with urllib.request.urlopen(req, data=body, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except (ValueError, UnicodeError):
            return e.code, str(e)
    except (OSError, ValueError) as e:
        return 0, str(e)

def run_audit():
    results = {}
    print("======================================================================")
    print("--- STARTING COMPREHENSIVE REAL-DATA-ONLY SYSTEM AUDIT ---")
    print("======================================================================")

    # 0. Clean simulation baseline
    http_req(f"{BASE_URL}/api/v1/portfolio/reset", method="POST")

    # 1. Health
    status, body = http_req(f"{BASE_URL}/api/v1/health")
    assert status == 200, f"Health failed: {body}"
    assert body["status"] == "ok"
    assert "database_status" in body
    results["health"] = {"status": "PASS", "data": body}
    print("[PASS] 1. Health check (/api/v1/health)")

    # 2. Config & Market Provider
    status, body = http_req(f"{BASE_URL}/api/v1/config")
    assert status == 200, f"Config failed: {body}"
    assert body["market_provider"] in ("historical_sqlite", "0xramm_yahoo_rest", "ramm_stock_api", "dhanhq_live"), f"Unexpected market provider: {body.get('market_provider')}"
    results["config"] = {"status": "PASS", "data": body}
    print(f"[PASS] 2. Config check (Provider: {body['market_provider']}, Ollama: {body.get('ollama_enabled')})")

    # 3. Dashboard Summary
    status, body = http_req(f"{BASE_URL}/api/v1/dashboard/summary")
    assert status == 200, f"Dashboard summary failed: {body}"
    assert "metrics" in body and "watchlist" in body and "agents" in body
    assert len(body["watchlist"]) >= 5
    watchlist_syms = [w["symbol"] for w in body["watchlist"]]
    assert "RELIANCE" in watchlist_syms
    assert "NOVA" not in watchlist_syms
    results["dashboard_summary"] = {"status": "PASS", "equity": body["metrics"]["equity"], "watchlist": watchlist_syms}
    print(f"[PASS] 3. Dashboard summary check (Watchlist: {watchlist_syms})")

    # 4. Market Assets & Quotes
    status, assets = http_req(f"{BASE_URL}/api/v1/market/assets")
    assert status == 200 and len(assets) >= 5, f"Assets failed: {assets}"
    asset_syms = [a["symbol"] for a in assets]
    assert "NOVA" not in asset_syms, "Fictional asset NOVA found in active assets!"

    status, quotes = http_req(f"{BASE_URL}/api/v1/market/quotes")
    assert status == 200 and len(quotes) >= 5, f"Quotes failed: {quotes}"
    for q in quotes:
        if q.get("freshness_status") in ("WAITING_FOR_FIRST_TICK", "WAITING_FOR_FIRST_POLL", "MARKET_CLOSED") and q.get("price") is None:
            pass
        elif q.get("price") is not None:
            assert q["price"] > 0, f"Non-positive price for {q['symbol']}"
        assert q["exchange"] == "NSE"
    results["market_data"] = {"status": "PASS", "assets_count": len(assets), "quotes_count": len(quotes)}
    print(f"[PASS] 4. Market assets & quotes check ({len(quotes)} verified NSE quotes)")

    # 5. Market Candles & Indicators on RELIANCE
    status, candles = http_req(f"{BASE_URL}/api/v1/market/candles?symbol=RELIANCE&bars=60")
    assert status == 200, f"Candles failed: {candles}"
    if isinstance(candles, list) and len(candles) > 0:
        for c in candles:
            assert c["is_synthetic"] is False, "Candle marked as synthetic!"
            assert c["high"] >= c["low"]
            assert c["volume"] >= 0

    status, indicators = http_req(f"{BASE_URL}/api/v1/market/indicators?symbol=RELIANCE")
    assert status == 200
    trend = indicators.get("trend", indicators.get("status", "WARMING_UP"))
    rsi = indicators.get("rsi_14", indicators.get("rsi"))
    results["indicators"] = {"status": "PASS", "rsi": rsi, "trend": trend}
    print(f"[PASS] 5. Market candles & indicators check (RELIANCE RSI: {rsi}, Status/Trend: {trend})")

    # 6. Replay Scenarios (All 4 Replay Scenarios)
    replay_scenarios = ["VOLATILITY_SURGE", "RISK_OFF_PULLBACK", "UNVERIFIED_RUMOR", "LIQUIDITY_SQUEEZE"]
    for sc_type in replay_scenarios:
        status, sc_res = http_req(f"{BASE_URL}/api/v1/scenarios/inject", method="POST", data={
            "scenario": sc_type,
            "symbol": "RELIANCE",
            "severity": 60.0
        })
        assert status == 200, f"Scenario {sc_type} failed: {sc_res}"
        if sc_type == "UNVERIFIED_RUMOR":
            assert sc_res["outcome"] == "REJECTED", f"Unverified rumor was not rejected: {sc_res}"
        results[f"scenario_{sc_type}"] = {"status": "PASS", "outcome": sc_res["outcome"], "reason": sc_res["reason"]}
        print(f"[PASS] 6. Historical Replay: {sc_type} (Outcome: {sc_res['outcome']})")

    # 7. Multi-Agent Analysis
    status, agent_res = http_req(f"{BASE_URL}/api/v1/agents/analyze", method="POST", data={
        "symbol": "RELIANCE",
        "scenario_type": "VOLATILITY_SURGE"
    })
    assert status == 200 and "market_analyst" in agent_res and "portfolio_manager" in agent_res
    exec_mode = agent_res["market_analyst"]["execution_mode"]
    assert exec_mode in ("deterministic_fallback", "local_llm")
    results["agent_analysis"] = {"status": "PASS", "mode": exec_mode, "cards": len(agent_res.get("cards", []))}
    print(f"[PASS] 7. Multi-agent analysis check (Mode: {exec_mode}, Cards: {len(agent_res.get('cards', []))})")

    # 8. Five-Stage Decision Pipeline
    status, pipe_res = http_req(f"{BASE_URL}/api/v1/decisions/run", method="POST", data={
        "symbol": "RELIANCE",
        "scenario_type": "VOLATILITY_SURGE",
        "severity": 50.0,
        "auto_execute": True
    })
    assert status == 200, f"Pipeline run failed: {pipe_res}"
    assert len(pipe_res["stages"]) == 5, f"Expected 5 stages, got: {len(pipe_res['stages'])}"
    stage_names = [s["name"] for s in pipe_res["stages"]]
    expected_stages = ["Market Data", "Specialist Analysis", "Portfolio Proposal", "Risk Gate", "Simulated Execution"]
    assert stage_names == expected_stages, f"Stages mismatch: {stage_names} vs {expected_stages}"
    results["decision_pipeline"] = {"status": "PASS", "stages": stage_names, "pipeline_status": pipe_res["status"]}
    print(f"[PASS] 8. Five-stage decision pipeline check (Status: {pipe_res['status']})")

    # 9. Portfolio Accounting & Valuation
    status, port = http_req(f"{BASE_URL}/api/v1/portfolio")
    assert status == 200 and "equity" in port and "positions" in port
    invested = sum(p["market_value"] for p in port["positions"])
    assert abs(port["equity"] - (port["cash"] + invested)) < 1.0, "Portfolio accounting equation broken!"
    results["portfolio"] = {"status": "PASS", "equity": port["equity"], "cash": port["cash"], "invested": invested}
    print(f"[PASS] 9. Portfolio accounting check (Equity: INR {port['equity']:,.2f}, Cash: INR {port['cash']:,.2f}, Positions: {len(port['positions'])})")

    # 10. Risk Gate Configuration & Audit
    status, risk_cfg = http_req(f"{BASE_URL}/api/v1/risk/config")
    assert status == 200 and "maxOrder" in risk_cfg and "maxAllocation" in risk_cfg
    # Update config
    status, updated_cfg = http_req(f"{BASE_URL}/api/v1/risk/config", method="PUT", data={"max_order_pct": 12.0})
    assert status == 200 and updated_cfg["maxOrder"] == 12.0
    # Restore config
    http_req(f"{BASE_URL}/api/v1/risk/config", method="PUT", data={"max_order_pct": 10.0})
    # Fetch risk decisions
    status, risk_decs = http_req(f"{BASE_URL}/api/v1/risk/decisions")
    assert status == 200 and len(risk_decs) > 0
    results["risk_engine"] = {"status": "PASS", "decisions_count": len(risk_decs)}
    print(f"[PASS] 10. Risk gate config & audit check ({len(risk_decs)} logged decisions)")

    # 11. Paper Broker & Order Ledger
    # First submit an approved order to verify execution flow
    status, new_ord = http_req(f"{BASE_URL}/api/v1/orders", method="POST", data={
        "symbol": "RELIANCE",
        "side": "BUY",
        "requested": 10,
        "price": 1211.70,
        "auto_execute": True,
        "reason": "Audit simulated investment order"
    })
    assert status == 200, f"Order submission failed: {new_ord}"

    status, orders = http_req(f"{BASE_URL}/api/v1/orders")
    assert status == 200 and len(orders) > 0
    status, executions = http_req(f"{BASE_URL}/api/v1/executions")
    assert status == 200 and isinstance(executions, list)
    status, ledger = http_req(f"{BASE_URL}/api/v1/ledger")
    assert status == 200 and isinstance(ledger, list)
    results["orders_and_ledger"] = {"status": "PASS", "orders": len(orders), "executions": len(executions), "ledger": len(ledger)}
    print(f"[PASS] 11. Orders, executions, and ledger check ({len(orders)} orders, {len(executions)} executions, {len(ledger)} ledger entries)")

    # 12. All 4 Backtesting Strategies on RELIANCE
    strategies = ["Buy and hold", "SMA crossover", "RSI-based strategy", "MACD-based strategy"]
    bt_results = {}
    for strat in strategies:
        status, bt_res = http_req(f"{BASE_URL}/api/v1/backtests", method="POST", data={
            "strategy": strat,
            "symbol": "RELIANCE",
            "timeframe": "1 year daily",
            "starting_capital": 1000000.0,
            "commission_pct": 0.1,
            "slippage_pct": 0.05
        })
        assert status == 200, f"Backtest for {strat} failed: {bt_res}"
        assert "total_return_pct" in bt_res and "max_drawdown_pct" in bt_res and "equity_curve" in bt_res
        assert bt_res["data_source"] == "historical"
        assert bt_res["is_synthetic"] is False
        bt_results[strat] = {
            "total_return_pct": bt_res["total_return_pct"],
            "max_drawdown_pct": bt_res["max_drawdown_pct"],
            "win_rate_pct": bt_res["win_rate_pct"],
            "trade_count": bt_res["trade_count"],
            "equity_points": len(bt_res["equity_curve"])
        }
        print(f"[PASS] 12. Backtest: '{strat}' on RELIANCE (Return: {bt_res['total_return_pct']}%, Drawdown: {bt_res['max_drawdown_pct']}%, Trades: {bt_res['trade_count']})")
    results["backtests"] = bt_results

    # 13. Historical Datasets Registry Endpoints
    status, datasets = http_req(f"{BASE_URL}/api/v1/datasets")
    assert status == 200 and len(datasets) >= 5, f"Datasets API failed: {datasets}"
    first_ds_id = datasets[0]["id"]
    status, ds_candles = http_req(f"{BASE_URL}/api/v1/datasets/{first_ds_id}/candles?limit=10")
    assert status == 200 and len(ds_candles["candles"]) == 10
    results["datasets"] = {"status": "PASS", "datasets_count": len(datasets)}
    print(f"[PASS] 13. Historical datasets registry check ({len(datasets)} datasets registered)")

    # 14. Frontend Proxy Connection Check
    status, f_health = http_req(f"{FRONTEND_PROXY_URL}/api/v1/health")
    assert status == 200, f"Frontend proxy to /api/v1/health failed: {status} {f_health}"
    assert f_health["status"] == "ok"
    results["frontend_proxy"] = {"status": "PASS", "proxy_response": f_health}
    print("[PASS] 14. Frontend proxy to /api/v1/health check")

    # 15. Reset Endpoint Verification
    status, reset_res = http_req(f"{BASE_URL}/api/v1/portfolio/reset", method="POST")
    assert status == 200 and reset_res["success"] is True
    print("[PASS] 15. Simulation reset endpoint check")

    print("======================================================================")
    print("--- ALL 15 AUDIT SUITES PASSED COMPLETELY ON REAL DATA ---")
    print("======================================================================")
    return results

if __name__ == "__main__":
    run_audit()
