from typing import Any

from app.agents.llm_provider import local_llm_provider
from app.market.scenarios import resolve_scenario_type


class PortfolioManager:
    """
    Role: Portfolio Manager & Chief Investment Officer (CIO)
    Synthesizes analyst reports (Market, Sentiment, Quant Alpha, Macro, Risk),
    computes an Investment Committee Consensus score, reviews portfolio exposure,
    and structures an auditable order proposal for the independent Risk Gate.
    """

    async def propose(
        self,
        symbol: str,
        market_analysis: dict[str, Any],
        sentiment_analysis: dict[str, Any],
        equity: float,
        current_price: float,
        scenario_type: str | None = None,
        quant_analysis: dict[str, Any] | None = None,
        macro_analysis: dict[str, Any] | None = None,
        risk_analysis: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        trend = market_analysis.get("trend", "Neutral")
        sentiment_analysis.get("sentiment", "Neutral")
        sentiment_score = sentiment_analysis.get("sentiment_score", 0)
        resolved_scenario = resolve_scenario_type(scenario_type) if scenario_type else None

        # Quantitative Alpha factor
        alpha_score = quant_analysis.get("alpha_score", 0) if quant_analysis else 0
        quant_regime = quant_analysis.get("regime", "Balanced") if quant_analysis else "Balanced"

        # Macro & Sector factor
        macro_tailwind = macro_analysis.get("tailwind_score", 0) if macro_analysis else 0
        sector_rating = macro_analysis.get("sector_rating", "Market Weight") if macro_analysis else "Market Weight"

        # Risk constraint
        sizing_cap_pct = risk_analysis.get("sizing_cap_pct", 10.0) if risk_analysis else 10.0
        risk_status = risk_analysis.get("risk_status", "Normal") if risk_analysis else "Normal"

        # Committee Consensus Score (-100 to +100)
        # Weights: Market (25%), Sentiment (25%), Quant Alpha (25%), Macro (25%)
        trend_score = 40 if trend == "Bullish" else -40 if trend == "Bearish" else 0
        consensus_score = int(
            0.25 * trend_score +
            0.25 * sentiment_score +
            0.25 * alpha_score +
            0.25 * macro_tailwind
        )

        # Target sizing default: strictly capped by 10.0% single-order limit
        target_allocation_pct = min(10.0, max(2.0, sizing_cap_pct))
        # Use floor division (int) to prevent rounding up past the 10% notional boundary
        requested_qty = max(1, int((equity * (target_allocation_pct / 100.0)) / current_price))

        if resolved_scenario == "RISK_OFF_PULLBACK":
            action = "SELL"
            requested_qty = min(requested_qty, 50)
            rationale = "Protective de-risking proposal in response to historical risk-off pullback regime."
        elif resolved_scenario == "VOLATILITY_SURGE":
            action = "BUY"
            rationale = "Momentum expansion proposal following historical volatility surge regime."
        elif resolved_scenario == "UNVERIFIED_RUMOR":
            action = "BUY"
            rationale = "Speculative proposal triggered by unverified market rumor; subject to strict Risk Gate rejection."
        elif resolved_scenario == "LIQUIDITY_SQUEEZE":
            action = "SELL"
            rationale = "Defensive proposal to trim exposure under historical liquidity contraction regime."
        else:
            # Multi-agent consensus decision
            if consensus_score >= 20 or trend == "Bullish" or sentiment_score > 30:
                action = "BUY"
                rationale = (
                    f"Consensus score ({consensus_score:+d}) and constructive alignment "
                    f"across specialist committee support adding exposure."
                )
            elif consensus_score <= -20 or trend == "Bearish" or sentiment_score < -30:
                action = "SELL"
                rationale = (
                    f"Consensus score ({consensus_score:+d}) signals negative momentum "
                    f"and macro headwinds; proposing de-risking."
                )
            else:
                action = "HOLD"
                requested_qty = 0
                rationale = "Neutral multi-factor alignment across committee; maintaining current allocations."

        citations = [
            f"Market Analyst: {market_analysis.get('summary', 'Trend checked')}",
            f"Sentiment Analyst: {sentiment_analysis.get('summary', 'Sentiment checked')}",
            f"Quant Alpha: {quant_regime} (Alpha: {alpha_score:+d})",
            f"Macro Strategist: {sector_rating} (Tailwind: {macro_tailwind:+d})",
            f"Risk Officer: {risk_status} (Cap: {sizing_cap_pct}%)",
            f"Verified market price: ₹{current_price:,.2f}",
        ]

        deterministic_output: dict[str, Any] = {
            "action": action,
            "symbol": symbol,
            "target_quantity": requested_qty,
            "estimated_price": current_price,
            "consensus_score": consensus_score,
            "rationale": rationale,
            "evidence_citations": citations,
            "proposed_weight_pct": round((requested_qty * current_price / equity) * 100.0, 1) if equity > 0 else 0.0,
            "confidence": 0.88,
            "summary": f"{action} proposal for {requested_qty} {symbol} (Consensus: {consensus_score:+d}) subject to Risk Gate validation.",
            "value": f"{action} {requested_qty} {symbol}" if action != "HOLD" else f"HOLD {symbol}",
            "execution_mode": "deterministic_fallback",
            "provider": "deterministic_fallback",
            "model": None,
            "latency_ms": 0.0,
        }

        # Attempt local Ollama generation
        prompt = (
            f"Portfolio Manager synthesizing specialist committee for {symbol}: "
            f"action={action}, requested_qty={requested_qty}, consensus_score={consensus_score:+d}, "
            f"verified price=₹{current_price:,.2f}, equity=₹{equity:,.2f}. "
            f"Market outlook: {market_analysis.get('trend')}, Macro: {sector_rating}, Quant: {quant_regime}. "
            "Synthesize committee consensus and structure the allocation proposal."
        )
        system_prompt = (
            'Respond with JSON containing keys: '
            '"action" ("BUY"|"SELL"|"HOLD"), '
            '"target_quantity" (integer), '
            '"rationale" (string synthesizing committee evidence and allocation logic)'
        )
        llm_res, meta = await local_llm_provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_keys=["action", "rationale"],
            temperature=0.1,
            num_predict=150,
        )

        if llm_res and "action" in llm_res:
            parsed_action = str(llm_res.get("action", action)).upper()
            if parsed_action not in ("BUY", "SELL", "HOLD"):
                parsed_action = action
            try:
                target_q = int(llm_res.get("target_quantity", requested_qty))
                target_q = max(0, min(1000, target_q))
            except (TypeError, ValueError, OverflowError):
                target_q = requested_qty

            deterministic_output.update({
                "action": parsed_action,
                "target_quantity": target_q,
                "rationale": llm_res.get("rationale", rationale),
                "summary": f"{parsed_action} proposal for {target_q} {symbol} (Consensus: {consensus_score:+d}) subject to Risk Gate validation.",
                "value": f"{parsed_action} {target_q} {symbol}" if parsed_action != "HOLD" else f"HOLD {symbol}",
                "execution_mode": meta["execution_mode"],
                "provider": meta["provider"],
                "model": meta["model"],
                "latency_ms": meta["latency_ms"],
            })
        else:
            deterministic_output["fallback_reason"] = meta.get("error")

        return deterministic_output


portfolio_manager = PortfolioManager()
