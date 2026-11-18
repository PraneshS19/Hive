import asyncio

import pytest
from app.agents.orchestrator import agent_orchestrator
from app.decisions.pipeline import decision_pipeline


@pytest.fixture(autouse=True)
def seed_live_reliance_quote():
    from app.market.dhan_adapter import dhan_live_feed
    dhan_live_feed.normalize_and_ingest_tick({
        "security_id": "2885",
        "symbol": "RELIANCE",
        "LTP": 1209.0,
        "price": 1209.0,
        "prev_close": 1200.0,
        "volume": 500000,
        "LTT": 1729600000
    })


def test_agent_orchestrator_execution(db):
    res = asyncio.run(agent_orchestrator.run_multi_agent_analysis(
        db=db,
        symbol="RELIANCE",
        scenario_type="VOLATILITY_SURGE"
    ))

    assert "market_analyst" in res
    assert "sentiment_analyst" in res
    assert "quant_analyst" in res
    assert "macro_analyst" in res
    assert "risk_officer" in res
    assert "portfolio_manager" in res
    assert len(res["cards"]) >= 3

    # Must transparently identify execution mode
    for card in res["cards"]:
        assert card["execution_mode"] in ("deterministic_fallback", "local_llm")


def test_decision_pipeline_full_run(db):
    res = asyncio.run(decision_pipeline.execute_pipeline(
        db=db,
        symbol="RELIANCE",
        scenario_type="VOLATILITY_SURGE",
        severity=50.0,
        auto_execute=True
    ))

    assert res["status"] in ("completed", "rejected")
    assert len(res["stages"]) == 5
    assert res["stages"][0]["name"] == "Market Data"
    assert res["stages"][1]["name"] == "Specialist Analysis"
    assert res["stages"][2]["name"] == "Portfolio Proposal"
    assert res["stages"][3]["name"] == "Risk Gate"
    assert res["stages"][4]["name"] == "Simulated Execution"


def test_decision_pipeline_stops_on_risk_rejection(db):
    res = asyncio.run(decision_pipeline.execute_pipeline(
        db=db,
        symbol="RELIANCE",
        scenario_type="UNVERIFIED_RUMOR",
        severity=60.0,
        auto_execute=True
    ))

    assert res["status"] == "rejected"
    assert res["stages"][3]["state"] == "bad"  # Risk Gate bad
    assert res["stages"][4]["state"] == "bad"  # Execution bad/blocked
