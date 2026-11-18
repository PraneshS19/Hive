from typing import Any

from app.core.errors import InvalidScenarioError

HISTORICAL_REPLAY_SCENARIOS = {
    "VOLATILITY_SURGE": {
        "title": "Historical Volatility Surge Replay",
        "headline": "Historical market stress replay: elevated intraday volatility and widening spreads.",
        "description": "Replays an elevated volatility regime to test risk gate sizing and exposure limits.",
        "stress_factor": 0.25,
        "is_historical_replay": True,
    },
    "RISK_OFF_PULLBACK": {
        "title": "Historical Risk-Off Pullback Replay",
        "headline": "Historical macro replay: sovereign yield spikes trigger institutional risk-off rotation.",
        "description": "Simulates a broad market de-risking event based on historical macro tightening periods.",
        "stress_factor": -0.05,
        "is_historical_replay": True,
    },
    "UNVERIFIED_RUMOR": {
        "title": "Unverified Market Rumor Replay",
        "headline": "Historical sentiment test: unverified speculative rumor circulated on unvetted forums.",
        "description": "Tests the sentiment analyst's credibility gate and risk gate's source verification rules.",
        "stress_factor": 0.02,
        "is_historical_replay": True,
    },
    "LIQUIDITY_SQUEEZE": {
        "title": "Historical Liquidity Contraction Replay",
        "headline": "Historical liquidity replay: market depth contracts and execution slippage increases.",
        "description": "Tests order sizing constraints when market depth decreases during abnormal trading sessions.",
        "stress_factor": -0.03,
        "is_historical_replay": True,
    },
}

# Backward compatibility alias map
SCENARIO_ALIASES = {
    "CRASH": "RISK_OFF_PULLBACK",
    "RALLY": "VOLATILITY_SURGE",
    "MISLEADING_NEWS": "UNVERIFIED_RUMOR",
    "LIQUIDITY_SHOCK": "LIQUIDITY_SQUEEZE",
}


def resolve_scenario_type(raw_type: str) -> str:
    cleaned = raw_type.strip().upper()
    return SCENARIO_ALIASES.get(cleaned, cleaned)


def get_replay_scenario(scenario_type: str, severity: float = 60.0) -> dict[str, Any]:
    resolved = resolve_scenario_type(scenario_type)
    if resolved not in HISTORICAL_REPLAY_SCENARIOS:
        raise InvalidScenarioError(f"Unsupported replay scenario: '{scenario_type}'")

    meta = HISTORICAL_REPLAY_SCENARIOS[resolved]
    return {
        "scenario_type": resolved,
        "title": meta["title"],
        "headline": meta["headline"],
        "description": meta["description"],
        "severity": max(10.0, min(100.0, severity)),
        "is_historical_replay": True,
        "label": "HISTORICAL REPLAY · NOT A LIVE EVENT",
    }


def calculate_scenario_effect(scenario_type: str, severity: float, current_price: float) -> tuple[float, float, str]:
    """
    Returns the replay headline and metadata.
    Does NOT modify the real market price. Preserves current_price authentically.
    """
    scenario = get_replay_scenario(scenario_type, severity)
    return current_price, 0.0, scenario["headline"]
