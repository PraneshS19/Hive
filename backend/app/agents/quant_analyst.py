from typing import Any

from app.agents.llm_provider import local_llm_provider


class QuantAnalyst:
    """
    Role: Quantitative Alpha Strategist
    Computes multi-factor momentum, Bollinger Band squeeze/expansion,
    RSI mean-reversion setups, and statistical volatility regimes using Python/pandas/numpy.
    Uses local LLM for quantitative regime interpretation.
    """

    async def analyze(self, symbol: str, indicators: dict[str, Any], current_price: float) -> dict[str, Any]:
        rsi = indicators.get("rsi_14") or indicators.get("rsi") or 50.0
        sma20 = indicators.get("sma_20") or current_price
        ema50 = indicators.get("ema_50") or current_price
        indicators.get("volatility") or 0.15
        bb_upper = indicators.get("bollinger_upper") or (current_price * 1.05)
        bb_lower = indicators.get("bollinger_lower") or (current_price * 0.95)
        indicators.get("macd") or 0.0
        macd_signal = indicators.get("macd_signal") or 0.0
        macd_hist = indicators.get("macd_hist") or 0.0

        # 1. Deterministic Bollinger Band Width & %B
        bb_width = ((bb_upper - bb_lower) / current_price) * 100.0 if current_price > 0 else 5.0
        bb_pct = ((current_price - bb_lower) / (bb_upper - bb_lower)) if (bb_upper - bb_lower) > 0 else 0.5

        # 2. Deterministic Factor scoring: Momentum & Mean Reversion
        momentum_score = 0
        if current_price > sma20:
            momentum_score += 25
        if sma20 > ema50:
            momentum_score += 25
        if macd_hist > 0:
            momentum_score += 25
        if rsi > 52:
            momentum_score += 25

        alpha_score = momentum_score - 50  # scale roughly -50 to +50
        if rsi < 35:
            alpha_score += 20  # mean-reversion bonus on oversold
            regime = "Mean-Reversion Oversold Setup"
        elif rsi > 70:
            alpha_score -= 15  # overbought stretch
            regime = "Overbought Exhaustion"
        elif bb_width < 4.5:
            regime = "Low-Volatility Squeeze (Breakout Imminent)"
        elif momentum_score >= 75:
            regime = "Momentum Trend Continuation"
        elif momentum_score <= 25:
            regime = "Persistent Bearish Downtrend"
        else:
            regime = "Consolidation / Rangebound"

        # Signal interpretation
        if alpha_score >= 25:
            signal = "Bullish Alpha"
            value = f"+{alpha_score} Alpha ({regime.split()[0]})"
        elif alpha_score <= -25:
            signal = "Bearish Alpha"
            value = f"{alpha_score} Alpha ({regime.split()[0]})"
        else:
            signal = "Neutral Alpha"
            value = f"{alpha_score:+d} Alpha (Neutral)"

        observations = [
            f"14-day RSI: {rsi:.1f} ({'Oversold' if rsi < 35 else 'Overbought' if rsi > 65 else 'Neutral'})",
            f"Bollinger Band Width: {bb_width:.1f}% (%B position: {bb_pct:.2f})",
            f"MACD Histogram: {macd_hist:+.2f} (Signal: {macd_signal:+.2f})",
            f"Trend Spread (SMA20 vs EMA50): {((sma20 - ema50) / ema50) * 100:+.2f}%",
        ]

        summary = (
            f"Quantitative alpha model identifies {regime.lower()} for {symbol}. "
            f"Alpha score is {alpha_score:+d} with {bb_width:.1f}% Bollinger bandwidth."
        )

        output: dict[str, Any] = {
            "alpha_score": alpha_score,
            "regime": regime,
            "signal": signal,
            "bollinger_bandwidth_pct": round(bb_width, 2),
            "bollinger_pct_b": round(bb_pct, 2),
            "momentum_factor": momentum_score,
            "key_observations": observations,
            "confidence": 0.89,
            "summary": summary,
            "value": value,
            "execution_mode": "deterministic_fallback",
            "provider": "deterministic_fallback",
            "model": None,
            "latency_ms": 0.0,
        }

        # Attempt local Ollama generation
        prompt = (
            f"Quantitative Alpha Strategist evaluating Indian equity {symbol}: "
            f"verified price=₹{current_price:,.2f}, 14-day RSI={rsi:.1f}, "
            f"Bollinger Bandwidth={bb_width:.1f}%, %B={bb_pct:.2f}, "
            f"MACD histogram={macd_hist:+.2f}, alpha score={alpha_score:+d}, regime={regime}. "
            "Synthesize quantitative alpha signals."
        )
        system_prompt = (
            'Respond with JSON containing keys: '
            '"regime" (string), '
            '"signal" ("Bullish Alpha"|"Bearish Alpha"|"Neutral Alpha"), '
            '"summary" (string explaining quantitative alpha positioning)'
        )
        llm_res, meta = await local_llm_provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_keys=["regime", "summary"],
            temperature=0.1,
            num_predict=150,
        )

        if llm_res and "summary" in llm_res:
            output.update({
                "regime": llm_res.get("regime", regime),
                "signal": llm_res.get("signal", signal),
                "summary": llm_res.get("summary", summary),
                "value": f"{output['alpha_score']:+d} Alpha ({output['signal']})",
                "execution_mode": meta["execution_mode"],
                "provider": meta["provider"],
                "model": meta["model"],
                "latency_ms": meta["latency_ms"],
            })
        else:
            output["fallback_reason"] = meta.get("error")

        return output


quant_analyst = QuantAnalyst()
