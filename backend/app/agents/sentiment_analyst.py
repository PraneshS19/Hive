from typing import Any

from app.agents.llm_provider import local_llm_provider
from app.market.scenarios import resolve_scenario_type

# Asset-specific verified corporate disclosures
ASSET_HEADLINES = {
    "RELIANCE": "Reliance Industries announces new energy expansion and quarterly refining margin resilience.",
    "TCS": "Tata Consultancy Services reports robust multi-year cloud transformation deal pipeline.",
    "INFY": "Infosys raises full-year revenue growth guidance amidst steady enterprise digital spend.",
    "HDFCBANK": "HDFC Bank demonstrates healthy net interest margin recovery and solid deposit franchise growth.",
    "NIFTY50": "NIFTY 50 trades in steady range as institutional inflows counterbalance global macro cues.",
}


class SentimentAnalyst:
    """
    Role: Sentiment & News Intelligence Analyst
    Evaluates corporate disclosures and historical scenario headlines,
    assigns sentiment scores, and verifies source credibility.
    """

    async def analyze(
        self,
        symbol: str,
        headline: str | None = None,
        scenario_type: str | None = None
    ) -> dict[str, Any]:
        symbol = symbol.upper()
        default_headline = ASSET_HEADLINES.get(symbol, f"Continuous market operations and verified trading volume on {symbol}.")
        active_headline = headline or default_headline
        resolved_scenario = resolve_scenario_type(scenario_type) if scenario_type else None

        if not headline and not resolved_scenario:
            sentiment_score = 42
            sentiment = "Constructive"
            verification = "Verified"
            confidence = 0.88
            source = "Official NSE Corporate Disclosures & Regulatory Filings"
            summary = f"Verified official disclosures show measured optimism for {symbol}."
            value = f"+{sentiment_score} score"

        elif resolved_scenario == "UNVERIFIED_RUMOR":
            sentiment_score = 85
            sentiment = "Unverified / Speculative"
            verification = "Unverified"
            confidence = 0.25
            source = "Anonymous Social Forum / Unvetted Blog"
            active_headline = headline or f"Speculative unverified rumor claims transformative buyout for {symbol}."
            summary = "High speculative sentiment detected, but flagged as UNVERIFIED source by verification gate."
            value = "Unverified Signal"

        elif resolved_scenario == "RISK_OFF_PULLBACK":
            sentiment_score = -75
            sentiment = "Bearish / Risk-Off"
            verification = "Verified"
            confidence = 0.92
            source = "Macro Wire & Sovereign Yield Alert"
            active_headline = headline or f"Historical risk-off rotation accelerates across {symbol} and broad market."
            summary = "Broad institutional risk-off sentiment observed across sovereign and equity desks."
            value = f"{sentiment_score} score"

        elif resolved_scenario == "VOLATILITY_SURGE":
            sentiment_score = 80
            sentiment = "Bullish / Surge"
            verification = "Verified"
            confidence = 0.90
            source = "Institutional Order Flow & Earnings Wire"
            active_headline = headline or f"Historical demand surge and institutional accumulation lift {symbol}."
            summary = "Strong verified demand surge and institutional accumulation signals."
            value = f"+{sentiment_score} score"

        elif resolved_scenario == "LIQUIDITY_SQUEEZE":
            sentiment_score = -45
            sentiment = "Defensive / Illiquid"
            verification = "Verified"
            confidence = 0.82
            source = "Market Depth & Clearinghouse Spread Monitor"
            active_headline = headline or f"Historical liquidity contraction and execution spreads widen on {symbol}."
            summary = "Elevated spread risk and liquidity withdrawal signals."
            value = f"{sentiment_score} score"

        else:
            sentiment_score = 42
            sentiment = "Constructive"
            verification = "Verified"
            confidence = 0.88
            source = "Official NSE Corporate Disclosures & Regulatory Filings"
            summary = f"Verified official disclosures show measured optimism for {symbol}."
            value = f"+{sentiment_score} score"

        output: dict[str, Any] = {
            "sentiment": sentiment,
            "sentiment_score": sentiment_score,
            "headline_analyzed": active_headline,
            "source_verification": verification,
            "source_name": source,
            "confidence": confidence,
            "summary": summary,
            "value": value,
            "execution_mode": "deterministic_fallback",
            "provider": "deterministic_fallback",
            "model": None,
            "latency_ms": 0.0,
        }

        # Attempt local Ollama generation
        prompt = (
            f"Sentiment Analyst evaluating headline for Indian equity {symbol}: \"{active_headline}\". "
            f"Source: {source} (Status: {verification}). "
            f"Scenario regime: {resolved_scenario or 'Normal'}. "
            "Analyze the sentiment polarity and provide a concise summary."
        )
        system_prompt = (
            'Respond with JSON containing keys: '
            '"sentiment" (string), '
            '"sentiment_score" (integer between -100 and +100), '
            '"summary" (string evaluating source credibility and market sentiment)'
        )
        llm_res, meta = await local_llm_provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_keys=["sentiment", "summary"],
            temperature=0.1,
            num_predict=150,
        )

        if llm_res and "sentiment" in llm_res:
            try:
                score = int(llm_res.get("sentiment_score", sentiment_score))
                score = max(-100, min(100, score))
            except (TypeError, ValueError, OverflowError):
                score = sentiment_score

            output.update({
                "sentiment": llm_res.get("sentiment", sentiment),
                "sentiment_score": score,
                "summary": llm_res.get("summary", summary),
                "value": f"{score:+d} score ({llm_res.get('sentiment', sentiment)})",
                "execution_mode": meta["execution_mode"],
                "provider": meta["provider"],
                "model": meta["model"],
                "latency_ms": meta["latency_ms"],
            })
        else:
            output["fallback_reason"] = meta.get("error")

        return output


sentiment_analyst = SentimentAnalyst()
