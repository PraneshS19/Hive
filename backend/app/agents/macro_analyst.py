from typing import Any

from app.agents.llm_provider import local_llm_provider
from app.market.scenarios import resolve_scenario_type

# Sector thematic mappings for verified Indian market universe
SECTOR_MAPPINGS = {
    "RELIANCE": {"sector": "Energy & Conglomerate", "cyclicality": "Cyclical / Global Commodities", "rates_sensitivity": "Moderate"},
    "TCS": {"sector": "IT Services & Consulting", "cyclicality": "Non-Cyclical Secular Growth", "rates_sensitivity": "Low"},
    "INFY": {"sector": "IT Services & Consulting", "cyclicality": "Non-Cyclical Secular Growth", "rates_sensitivity": "Low"},
    "HDFCBANK": {"sector": "Banking & Financial Services", "cyclicality": "Credit Cycle Sensitive", "rates_sensitivity": "High"},
    "NIFTY50": {"sector": "Broad Market Benchmark", "cyclicality": "Macro Benchmark", "rates_sensitivity": "Moderate"},
}

# Traceable Macroeconomic Data Registry
# Explicitly tracks provenance, publication date, effective date, and status.
MACRO_DATA_REGISTRY = {
    "rbi_repo_rate": {
        "value": None,
        "status": "FEED_UNAVAILABLE",
        "publication_date": None,
        "effective_date": None,
        "source": "Reserve Bank of India (RBI)",
        "limitation": "No live authenticated macroeconomic API feed connected. Specific policy rates (e.g. repo rate) are unverified in this offline simulation environment."
    }
}


class MacroAnalyst:
    """
    Role: Macro & Sector Strategist
    Evaluates macroeconomic backdrop, sector rotation tailwinds,
    cost-of-capital pressures, and systemic liquidity conditions.
    Explicitly enforces data provenance and prevents unverified macro claims.
    """

    async def analyze(
        self,
        symbol: str,
        scenario_type: str | None = None,
        severity: float | None = None
    ) -> dict[str, Any]:
        info = SECTOR_MAPPINGS.get(symbol.upper(), {
            "sector": "Diversified Industry",
            "cyclicality": "Market-Neutral",
            "rates_sensitivity": "Moderate"
        })
        sector = info["sector"]
        cyclicality = info["cyclicality"]
        resolved_scenario = resolve_scenario_type(scenario_type) if scenario_type else None
        macro_feed = MACRO_DATA_REGISTRY["rbi_repo_rate"]

        if resolved_scenario == "RISK_OFF_PULLBACK":
            macro_regime = "Risk-Off Liquidity Drain"
            sector_rating = "Underweight Cyclicals"
            tailwind_score = -70
            summary = (
                f"Macro environment shifted to risk-off contraction. "
                f"Elevated equity risk premium compresses valuations across {sector}."
            )
            value = "Risk-Off Contraction"
        elif resolved_scenario == "VOLATILITY_SURGE":
            macro_regime = "Liquidity Expansion & Risk-On"
            sector_rating = "Overweight Growth"
            tailwind_score = 65
            summary = (
                f"Accommodative monetary backdrop and risk-on sentiment provide "
                f"strong tailwinds for {sector} expansion."
            )
            value = "Risk-On Expansion"
        elif resolved_scenario == "LIQUIDITY_SQUEEZE":
            macro_regime = "Systemic Liquidity Contraction"
            sector_rating = "Defensive / High Cash"
            tailwind_score = -55
            summary = (
                f"Interbank funding spreads widen; illiquidity premium rises. "
                f"High-beta positions in {sector} face heightened margin pressure."
            )
            value = "Liquidity Freeze"
        elif resolved_scenario == "UNVERIFIED_RUMOR":
            macro_regime = "Speculative Micro Disconnect"
            sector_rating = "Neutral / Audit Focus"
            tailwind_score = 10
            summary = (
                f"Headline-driven noise unverified by underlying macroeconomic data "
                f"or sector fundamentals in {sector}."
            )
            value = "Speculative Decoupling"
        else:
            macro_regime = "Neutral Macro Equilibrium"
            sector_rating = "Market Weight"
            tailwind_score = 25
            summary = (
                f"Macro feed is unavailable. The sector classification for {sector} is reference information."
            )
            value = "Macro data unavailable"

        observations = [
            f"Sector: {sector} ({cyclicality})",
            f"Interest Rate Sensitivity: {info['rates_sensitivity']}",
            f"Thematic Tailwind Score: {tailwind_score:+d}/100",
            f"Cross-Asset Alignment: {macro_regime}",
            f"Macro Data Status: {macro_feed['status']} (Live RBI policy feed unverified)",
        ]

        output: dict[str, Any] = {
            "macro_regime": macro_regime,
            "sector": sector,
            "sector_rating": sector_rating,
            "tailwind_score": tailwind_score,
            "cyclicality": cyclicality,
            "rates_sensitivity": info["rates_sensitivity"],
            "macro_data_status": macro_feed["status"],
            "macro_provenance_note": macro_feed["limitation"],
            "key_observations": observations,
            "confidence": 0.87,
            "summary": summary,
            "value": value,
            "execution_mode": "deterministic_fallback",
            "provider": "deterministic_fallback",
            "model": None,
            "latency_ms": 0.0,
        }

        # Attempt local Ollama generation with strict provenance constraint
        prompt = (
            f"Macro Strategist analyzing Indian asset {symbol} in sector '{sector}' ({cyclicality}). "
            f"Rates sensitivity: {info['rates_sensitivity']}. "
            f"Macro scenario: {resolved_scenario or 'Normal Baseline'}. Active regime: {macro_regime}. "
            f"IMPORTANT DATA CONSTRAINT: No live authenticated RBI repo-rate feed is connected in this offline simulation. "
            f"Do NOT invent or assert specific RBI repo rate percentages. Focus strictly on sector cyclicality and structural rate sensitivity. "
            "Synthesize sector tailwinds and macroeconomic positioning."
        )
        system_prompt = (
            'Respond with JSON containing keys: '
            '"macro_regime" (string), '
            '"sector_rating" ("Overweight"|"Market Weight"|"Underweight"), '
            '"summary" (string explaining macroeconomic sector dynamics without fabricating specific unverified central bank rates)'
        )
        llm_res, meta = await local_llm_provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_keys=["macro_regime", "summary"],
            temperature=0.1,
            num_predict=150,
        )

        if llm_res and "summary" in llm_res:
            output.update({
                "macro_regime": llm_res.get("macro_regime", macro_regime),
                "sector_rating": llm_res.get("sector_rating", sector_rating),
                "summary": llm_res.get("summary", summary),
                "value": f"{output['macro_regime']} ({output['sector_rating']})",
                "execution_mode": meta["execution_mode"],
                "provider": meta["provider"],
                "model": meta["model"],
                "latency_ms": meta["latency_ms"],
            })
        else:
            output["fallback_reason"] = meta.get("error")

        return output


macro_analyst = MacroAnalyst()
