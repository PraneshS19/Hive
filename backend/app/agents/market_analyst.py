from typing import Any

from app.agents.llm_provider import local_llm_provider


class MarketAnalyst:
    """
    Role: Technical / Market Analyst
    Analyzes price action, moving averages, RSI, and momentum against authentic historical data.
    """

    async def analyze(self, symbol: str, indicators: dict[str, Any], current_price: float) -> dict[str, Any]:
        trend = indicators.get("trend", "Neutral")
        momentum = indicators.get("momentum", "Neutral")
        rsi = indicators.get("rsi_14") or indicators.get("rsi") or 50.0
        sma = indicators.get("sma_20") or current_price
        vol = indicators.get("volatility")
        vol_str = f"{vol * 100:.1f}%" if vol is not None else "UNAVAILABLE"
        vol_assessment = (
            f"Annualized volatility estimated at {vol_str}."
            if vol is not None
            else "Annualized volatility unavailable (insufficient return history)."
        )

        # Baseline deterministic analysis from authentic indicators
        summary = (
            f"{trend} trend identified on {symbol}. RSI is {rsi:.1f} ({momentum}). "
            f"Price {'trades above' if current_price >= sma else 'trades below'} 20-period SMA (₹{sma:,.2f})."
        )

        obs = [
            f"Current price: ₹{current_price:,.2f}",
            f"20-period SMA: ₹{sma:,.2f}",
            f"14-period RSI: {rsi:.1f}",
            f"Annualized volatility: {vol_str}",
        ]

        output: dict[str, Any] = {
            "trend": trend,
            "momentum": momentum,
            "volatility_assessment": vol_assessment,
            "key_observations": obs,
            "confidence": 0.88,
            "indicators_summary": indicators,
            "summary": summary,
            "value": trend,
            "execution_mode": "deterministic_fallback",
            "provider": "deterministic_fallback",
            "model": None,
            "latency_ms": 0.0,
        }

        # Attempt local Ollama inference
        prompt = (
            f"Technical Analyst evaluating Indian equity {symbol} (NSE). "
            f"Current verified price: ₹{current_price:,.2f}, 20-day SMA: ₹{sma:,.2f}, "
            f"14-day RSI: {rsi:.1f}, Annualized Volatility: {vol*100:.1f}%. "
            f"Synthesize the technical setup and momentum."
        )
        system_prompt = (
            'Respond with JSON containing keys: '
            '"trend" ("Bullish"|"Bearish"|"Neutral"), '
            '"momentum" (string), '
            '"summary" (string explaining technical outlook based on the indicators)'
        )
        llm_res, meta = await local_llm_provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_keys=["trend", "summary"],
            temperature=0.1,
            num_predict=150,
        )

        if llm_res and "trend" in llm_res:
            parsed_trend = str(llm_res.get("trend", trend)).capitalize()
            if parsed_trend not in ("Bullish", "Bearish", "Neutral"):
                parsed_trend = trend
            output.update({
                "trend": parsed_trend,
                "momentum": llm_res.get("momentum", momentum),
                "summary": llm_res.get("summary", summary),
                "value": parsed_trend,
                "execution_mode": meta["execution_mode"],
                "provider": meta["provider"],
                "model": meta["model"],
                "latency_ms": meta["latency_ms"],
            })
        else:
            output["fallback_reason"] = meta.get("error")

        return output


market_analyst = MarketAnalyst()
