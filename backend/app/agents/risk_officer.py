import math
from typing import Any

from app.agents.llm_provider import local_llm_provider
from app.market.indicators import calculate_gaussian_var_cvar
from app.market.scenarios import resolve_scenario_type


class RiskOfficer:
    """
    Role: Institutional Risk & Compliance Officer
    Performs deterministic pre-trade risk validation, exact Gaussian Value-at-Risk (VaR)
    and Expected Shortfall (CVaR) estimation, stress testing, and allocation concentration limits.
    Fails safe (0% sizing cap) when required historical volatility data is unavailable.
    """

    async def analyze(
        self,
        symbol: str,
        current_price: float,
        equity: float,
        volatility: float | None = None,
        scenario_type: str | None = None
    ) -> dict[str, Any]:
        resolved_scenario = resolve_scenario_type(scenario_type) if scenario_type else None

        # Fail-Safe Handling: Missing or Uncomputable Volatility
        if volatility is None:
            risk_status = "Risk Assessment Inconclusive (Insufficient Volatility Data)"
            value = "Gate Veto: Missing Volatility Data"
            sizing_cap_pct = 0.0
            var_95_pct = None
            cvar_99_pct = None
            stress_drawdown_pct = None
            summary = (
                f"Insufficient historical return data available to compute statistical VaR/CVaR for {symbol}. "
                f"Institutional risk policy mandates an immediate 0% sizing cap (fail-safe veto) until verified price bars exist."
            )
            observations = [
                "1-Day Parametric VaR (95%): UNAVAILABLE",
                "Expected Shortfall (CVaR 99%): UNAVAILABLE",
                "Historical Volatility: Insufficient return observations (<2)",
                "Policy Enforced: FAIL-SAFE 0% sizing cap active (No new positions permitted)",
            ]
        elif volatility == 0.0:
            daily_vol = 0.0
            var_95_pct = 0.0
            cvar_99_pct = 0.0
            stress_drawdown_pct = 0.0
            risk_status = "Zero Volatility Stagnation"
            sizing_cap_pct = 5.0
            value = "Normal Guard (VaR 0.0%)"
            summary = (
                f"Price series displays zero price variance over estimation window for {symbol}. "
                f"Statistical tail loss is 0.0%, with sizing restricted to {sizing_cap_pct}% due to liquidity stagnation caution."
            )
            observations = [
                "1-Day Parametric VaR (95%): 0.0%",
                "Expected Shortfall (CVaR 99%): 0.0%",
                "Stress-Test Max Drawdown: 0.0%",
                f"Max Recommended Sizing: {sizing_cap_pct}% of Equity (Liquidity Stagnation Cap)",
            ]
        else:
            # 1. Exact Gaussian Parametric VaR & Analytic Expected Shortfall (CVaR)
            daily_vol = volatility / math.sqrt(252)
            var_95_pct, _ = calculate_gaussian_var_cvar(daily_vol, alpha=0.95)
            _, cvar_99_pct = calculate_gaussian_var_cvar(daily_vol, alpha=0.99)

            # 2. Stress-testing under historical shock
            if resolved_scenario == "RISK_OFF_PULLBACK":
                stress_drawdown_pct = round(var_95_pct * 3.8, 1)
                risk_status = "Elevated Risk (Risk-Off Regime)"
                sizing_cap_pct = 5.0
                value = f"High Alert (VaR {var_95_pct}%)"
                summary = (
                    f"Historical risk-off stress-test projects potential {stress_drawdown_pct}% portfolio impact. "
                    f"Institutional risk policy mandates reducing position sizing cap to {sizing_cap_pct}%."
                )
            elif resolved_scenario == "LIQUIDITY_SQUEEZE":
                stress_drawdown_pct = round(var_95_pct * 2.5, 1)
                risk_status = "Liquidity Haircut Active"
                sizing_cap_pct = 6.0
                value = "Liquidity Warning (Haircut 40%)"
                summary = (
                    f"Widened market spreads increase liquidation slippage risk. "
                    f"Sizing restricted to {sizing_cap_pct}% of equity with strict limit orders."
                )
            elif resolved_scenario == "UNVERIFIED_RUMOR":
                stress_drawdown_pct = round(var_95_pct * 1.8, 1)
                risk_status = "Information Integrity Breach"
                sizing_cap_pct = 0.0
                value = "Gate Veto: Unverified Source"
                summary = (
                    "Headline fails institutional source verification check. Risk compliance "
                    "mandates deterministic trade rejection to prevent chasing rumor-driven volatility."
                )
            else:
                stress_drawdown_pct = round(var_95_pct * 1.5, 1)
                risk_status = "Normal Governance"
                sizing_cap_pct = 10.0
                value = f"Normal Guard (VaR {var_95_pct}%)"
                summary = (
                    f"Standard risk parameters validated. 1-day 95% VaR is {var_95_pct}%, "
                    f"stress drawdown bounded at {stress_drawdown_pct}%. Sizing cap is {sizing_cap_pct}%."
                )

            observations = [
                f"1-Day Parametric VaR (95%): {var_95_pct}% (Gaussian: z=1.645)",
                f"Expected Shortfall (CVaR 99%): {cvar_99_pct}% (Exact Analytic Gaussian: factor=2.665)",
                f"Stress-Test Max Drawdown: -{stress_drawdown_pct}%",
                f"Max Recommended Sizing: {sizing_cap_pct}% of Equity",
                "Model Limitation: Gaussian distribution assumes normal tails and underestimates extreme leptokurtic shocks",
            ]

        output: dict[str, Any] = {
            "risk_status": risk_status,
            "var_95_pct": var_95_pct,
            "cvar_99_pct": cvar_99_pct,
            "stress_drawdown_pct": stress_drawdown_pct,
            "sizing_cap_pct": sizing_cap_pct,
            "key_observations": observations,
            "confidence": 0.94 if volatility is not None else 0.50,
            "summary": summary,
            "value": value,
            "execution_mode": "deterministic_fallback",
            "provider": "deterministic_fallback",
            "model": None,
            "latency_ms": 0.0,
        }

        # If volatility is missing, do not call LLM — fail-safe directly
        if volatility is None:
            return output

        # Attempt local Ollama generation
        prompt = (
            f"Risk & Compliance Officer auditing proposed action on Indian equity {symbol}: "
            f"VaR95={var_95_pct}%, CVaR99={cvar_99_pct}%, scenario={resolved_scenario or 'Normal'}, "
            f"risk status={risk_status}, sizing cap={sizing_cap_pct}%. "
            "Synthesize institutional compliance governance."
        )
        system_prompt = (
            'Respond with JSON containing keys: '
            '"risk_status" (string), '
            '"summary" (string explaining institutional risk compliance stance)'
        )
        llm_res, meta = await local_llm_provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            expected_keys=["risk_status", "summary"],
            temperature=0.1,
            num_predict=150,
        )

        if llm_res and "summary" in llm_res:
            output.update({
                "risk_status": llm_res.get("risk_status", risk_status),
                "summary": llm_res.get("summary", summary),
                "value": f"{llm_res.get('risk_status', risk_status)} (VaR {var_95_pct}%)",
                "execution_mode": meta["execution_mode"],
                "provider": meta["provider"],
                "model": meta["model"],
                "latency_ms": meta["latency_ms"],
            })
        else:
            output["fallback_reason"] = meta.get("error")

        return output


risk_officer = RiskOfficer()
