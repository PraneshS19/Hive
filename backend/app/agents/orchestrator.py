import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.agents.macro_analyst import macro_analyst
from app.agents.market_analyst import market_analyst
from app.agents.portfolio_manager import portfolio_manager
from app.agents.quant_analyst import quant_analyst
from app.agents.risk_officer import risk_officer
from app.agents.sentiment_analyst import sentiment_analyst
from app.db.models import AgentRun
from app.market.engine import market_engine
from app.portfolio.service import portfolio_service
from sqlalchemy.orm import Session


class AgentOrchestrator:
    """
    Coordinates multi-agent investment committee analysis with structured schema
    outputs, persistent audit logging, and transparent execution mode reporting.
    """

    async def run_multi_agent_analysis(
        self,
        db: Session,
        symbol: str,
        pipeline_run_id: str | None = None,
        scenario_type: str | None = None,
        headline: str | None = None,
        severity: float | None = None
    ) -> dict[str, Any]:
        run_id = pipeline_run_id or f"RUN_{uuid.uuid4().hex[:10]}"
        symbol = symbol.upper()

        # Authoritative market data and indicators
        quote = market_engine.get_quote(db, symbol)
        if not quote:
            raise ValueError(f"No market quote found for asset '{symbol}'. Please select an imported market asset.")
        current_price = quote["price"]
        indicators = market_engine.get_indicators(db, symbol)

        # Portfolio state
        portfolio_summary = portfolio_service.get_portfolio_summary(db)
        equity = portfolio_summary["equity"]
        volatility = indicators.get("volatility")

        # Execute 5 specialist analysts concurrently
        market_coro = market_analyst.analyze(symbol, indicators, current_price)
        sentiment_coro = sentiment_analyst.analyze(symbol, headline, scenario_type)
        quant_coro = quant_analyst.analyze(symbol, indicators, current_price)
        macro_coro = macro_analyst.analyze(symbol, scenario_type, severity)
        risk_coro = risk_officer.analyze(symbol, current_price, equity, volatility, scenario_type)

        (
            market_out,
            sentiment_out,
            quant_out,
            macro_out,
            risk_out
        ) = await asyncio.gather(
            market_coro,
            sentiment_coro,
            quant_coro,
            macro_coro,
            risk_coro
        )

        # 6. Portfolio Manager synthesizes all 5 specialist reports
        pm_out = await portfolio_manager.propose(
            symbol=symbol,
            market_analysis=market_out,
            sentiment_analysis=sentiment_out,
            equity=equity,
            current_price=current_price,
            scenario_type=scenario_type,
            quant_analysis=quant_out,
            macro_analysis=macro_out,
            risk_analysis=risk_out
        )

        now = datetime.now(UTC)

        # Persist audit runs for all 6 agents
        specialists = [
            ("Market Analyst", market_out),
            ("Sentiment Analyst", sentiment_out),
            ("Quantitative Alpha", quant_out),
            ("Macro Strategist", macro_out),
            ("Institutional Risk", risk_out),
            ("Portfolio Manager", pm_out),
        ]

        for role_name, out in specialists:
            run_record = AgentRun(
                pipeline_run_id=run_id,
                role=role_name,
                status="COMPLETED",
                execution_mode=out["execution_mode"],
                value=out["value"],
                summary=out["summary"],
                confidence=out.get("confidence", 0.85),
                output_json=json.dumps(out),
                created_at=now
            )
            db.add(run_record)

        db.commit()

        # Format cards for frontend and committee displays
        cards = [
            {
                "name": role_name,
                "status": "Complete",
                "value": out["value"],
                "text": out["summary"],
                "execution_mode": out["execution_mode"],
                "provider": out.get("provider", "deterministic_fallback"),
                "model": out.get("model"),
                "latency_ms": out.get("latency_ms"),
            }
            for role_name, out in specialists
        ]

        return {
            "pipeline_run_id": run_id,
            "symbol": symbol,
            "market_analyst": market_out,
            "sentiment_analyst": sentiment_out,
            "quant_analyst": quant_out,
            "macro_analyst": macro_out,
            "risk_officer": risk_out,
            "portfolio_manager": pm_out,
            "cards": cards,
        }


agent_orchestrator = AgentOrchestrator()
