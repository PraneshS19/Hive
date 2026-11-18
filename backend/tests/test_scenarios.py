import pytest
from app.core.errors import InvalidScenarioError
from app.market.scenarios import (
    calculate_scenario_effect,
    get_replay_scenario,
)


def test_historical_replay_price_preservation():
    """Verify that historical replay stress testing does NOT alter authentic market prices."""
    initial_p = 1211.70  # Real RELIANCE close
    for scenario_name in ["VOLATILITY_SURGE", "RISK_OFF_PULLBACK", "UNVERIFIED_RUMOR", "LIQUIDITY_SQUEEZE"]:
        new_p, change_pct, headline = calculate_scenario_effect(scenario_name, 60.0, initial_p)
        assert new_p == initial_p, "Real price must NOT be mutated by stress replay"
        assert change_pct == 0.0, "Real price change must remain unmanipulated"
        assert len(headline) > 0


def test_scenario_resolution_and_metadata():
    """Verify all 4 replay scenarios and their aliases resolve to verified historical replay metadata."""
    cases = [
        ("VOLATILITY_SURGE", "Historical Volatility Surge Replay"),
        ("RISK_OFF_PULLBACK", "Historical Risk-Off Pullback Replay"),
        ("UNVERIFIED_RUMOR", "Unverified Market Rumor Replay"),
        ("LIQUIDITY_SQUEEZE", "Historical Liquidity Contraction Replay"),
        ("CRASH", "Historical Risk-Off Pullback Replay"),
        ("RALLY", "Historical Volatility Surge Replay"),
        ("MISLEADING_NEWS", "Unverified Market Rumor Replay"),
        ("LIQUIDITY_SHOCK", "Historical Liquidity Contraction Replay"),
    ]

    for raw, expected_title in cases:
        replay = get_replay_scenario(raw, 50.0)
        assert replay["title"] == expected_title
        assert replay["is_historical_replay"] is True
        assert "HISTORICAL REPLAY" in replay["label"]
        assert 10.0 <= replay["severity"] <= 100.0


def test_invalid_scenario_raises():
    with pytest.raises(InvalidScenarioError):
        calculate_scenario_effect("NON_EXISTENT_SCENARIO", 50.0, 100.0)
