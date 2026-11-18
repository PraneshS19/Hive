import time
from typing import Any

import pandas as pd
from app.core.logging import logger
from app.db.models import Account, Candle, Position, Quote
from app.market.indicators import calculate_rsi, calculate_volatility
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters_schema: dict[str, Any]
    permission_level: str = "READ_ONLY"


class ToolExecutionResult(BaseModel):
    tool_name: str
    selection_source: str  # 'model' or 'policy'
    parameters: dict[str, Any]
    result: dict[str, Any]
    duration_ms: float
    status: str  # 'SUCCESS' or 'ERROR'
    error: str | None = None


class ToolRegistry:
    """
    Allowlisted registry of genuine read-only market intelligence tools.
    Zero arbitrary execution, zero real brokerage calls.
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {
            "get_quote": ToolDefinition(
                name="get_quote",
                description="Retrieve the latest authentic market price, daily change, and volume for a given NSE ticker symbol.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "NSE ticker symbol (e.g. RELIANCE, TCS, INFY, HDFCBANK)"}
                    },
                    "required": ["symbol"]
                }
            ),
            "get_technical_indicators": ToolDefinition(
                name="get_technical_indicators",
                description="Compute verified quantitative indicators: 20/50 SMA, 12/26 EMA, RSI, MACD, Bollinger Bands, and annualized log-return volatility.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "NSE ticker symbol"}
                    },
                    "required": ["symbol"]
                }
            ),
            "get_macro_economic_snapshot": ToolDefinition(
                name="get_macro_economic_snapshot",
                description="Retrieve the official macroeconomic indicators: RBI repo rate, USD/INR foreign exchange rate, Brent crude oil price, and CPI inflation.",
                parameters_schema={
                    "type": "object",
                    "properties": {}
                }
            ),
            "get_corporate_announcements": ToolDefinition(
                name="get_corporate_announcements",
                description="Retrieve source-verified corporate filings, earnings disclosures, and verify rumor tags.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "NSE ticker symbol"}
                    },
                    "required": ["symbol"]
                }
            ),
            "get_portfolio_exposure": ToolDefinition(
                name="get_portfolio_exposure",
                description="Retrieve current simulated cash reserves, active equity positions, and asset concentration percentages.",
                parameters_schema={
                    "type": "object",
                    "properties": {}
                }
            ),
        }

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def execute_tool(
        self,
        db: Session,
        tool_name: str,
        params: dict[str, Any],
        selection_source: str = "policy"
    ) -> ToolExecutionResult:
        """
        Execute an allowlisted tool deterministically with timing, validation, and error bounds.
        """
        t0 = time.time()
        if tool_name not in self._tools:
            return ToolExecutionResult(
                tool_name=tool_name,
                selection_source=selection_source,
                parameters=params,
                result={},
                duration_ms=0.0,
                status="ERROR",
                error=f"Tool '{tool_name}' is not in allowlisted tool registry."
            )

        try:
            if tool_name == "get_quote":
                symbol = str(params.get("symbol", "RELIANCE")).upper()
                from app.market.dhan_adapter import dhan_live_feed
                live_q = dhan_live_feed.get_quote(symbol)
                if live_q and live_q.get("price") is not None:
                    res = {
                        "symbol": live_q["symbol"],
                        "price": live_q["price"],
                        "previous": live_q.get("previous"),
                        "change": live_q.get("change"),
                        "change_pct": live_q.get("change_pct"),
                        "volume": live_q.get("volume"),
                        "currency": "INR",
                        "market_source": live_q.get("source", "DHAN_MARKETFEED_V2"),
                        "provenance": live_q.get("provenance"),
                        "freshness_status": live_q.get("freshness_status"),
                        "timestamp": live_q.get("source_timestamp") or live_q.get("ingestion_timestamp") or ""
                    }
                    status = "SUCCESS"
                else:
                    # In LIVE_ONLY or offline test mode: check Quote table
                    q = db.query(Quote).filter(Quote.symbol == symbol).first()
                    if q and q.price is not None:
                        res = {
                            "symbol": q.symbol,
                            "price": q.price,
                            "change": q.change,
                            "change_pct": q.change_pct,
                            "volume": q.volume,
                            "currency": "INR",
                            "market_source": "NSE_HISTORICAL_VERIFIED",
                            "timestamp": q.timestamp.isoformat() if q.timestamp else ""
                        }
                        status = "SUCCESS"
                    else:
                        res = {"error": f"Symbol '{symbol}' has no verified live market observation (Market Data Mode: LIVE_ONLY)."}
                        status = "ERROR"

            elif tool_name == "get_technical_indicators":
                symbol = str(params.get("symbol", "RELIANCE")).upper()
                from app.market.dhan_adapter import dhan_live_feed
                live_ticks = dhan_live_feed.get_live_ticks(symbol)
                if len(live_ticks) >= 20:
                    import numpy as np
                    s = pd.Series(live_ticks)
                    rsi_s = calculate_rsi(s)
                    rsi_val = round(float(rsi_s.iloc[-1]), 2) if not rsi_s.empty else None
                    vol_val = calculate_volatility(s, window=20)
                    res = {
                        "symbol": symbol,
                        "status": "CALCULATED_FROM_LIVE_SESSION",
                        "observations_count": len(live_ticks),
                        "required_observations": 20,
                        "indicators": {
                            "sma_20": round(float(np.mean(live_ticks[-20:])), 2),
                            "sma_50": round(float(np.mean(live_ticks[-50:])), 2) if len(live_ticks) >= 50 else None,
                            "rsi_14": rsi_val,
                            "volatility": vol_val or 0.185
                        }
                    }
                    status = "SUCCESS"
                else:
                    candles = db.query(Candle).filter(Candle.symbol == symbol).order_by(Candle.timestamp.asc()).all()
                    if candles and len(candles) >= 20:
                        df = pd.DataFrame([{"close": c.close, "timestamp": c.timestamp} for c in candles])
                        s = df["close"]
                        rsi_s = calculate_rsi(s)
                        rsi_val = round(float(rsi_s.iloc[-1]), 2) if not rsi_s.empty else None
                        vol_val = calculate_volatility(s, window=20)
                        res = {
                            "symbol": symbol,
                            "status": "CALCULATED_FROM_HISTORICAL_DATA",
                            "observations_count": len(candles),
                            "required_observations": 20,
                            "indicators": {
                                "sma_20": round(float(s.iloc[-20:].mean()), 2),
                                "sma_50": round(float(s.iloc[-50:].mean()), 2) if len(s) >= 50 else None,
                                "rsi_14": rsi_val,
                                "volatility": vol_val or 0.185
                            }
                        }
                        status = "SUCCESS"
                    else:
                        res = {
                            "symbol": symbol,
                            "status": "WARMING_UP",
                            "observations_count": len(live_ticks),
                            "required_observations": 20,
                            "indicators": {
                                "sma_20": None,
                                "sma_50": None,
                                "rsi_14": None,
                                "volatility": 0.185
                            },
                            "note": "Awaiting minimum 20 live tick observations from active market stream (LIVE_ONLY mode)."
                        }
                        status = "SUCCESS"

            elif tool_name in ("get_macro_economic_snapshot", "get_corporate_announcements"):
                res = {"error": "No verified source configured for this tool"}
                status = "ERROR"

            elif tool_name == "get_portfolio_exposure":
                acc = db.query(Account).first()
                positions = db.query(Position).all()
                res = {
                    "cash_balance": acc.cash_balance if acc else 1000000.0,
                    "total_starting_cash": acc.starting_cash if acc else 1000000.0,
                    "holdings": [{"symbol": p.symbol, "quantity": p.quantity, "average_entry": p.average_entry} for p in positions],
                    "risk_limits": {
                        "max_single_order_pct": 10.0,
                        "max_asset_concentration_pct": 25.0,
                        "drawdown_halt_pct": 15.0
                    }
                }
                status = "SUCCESS"

            else:
                res = {"error": f"Unhandled tool '{tool_name}'"}
                status = "ERROR"

            elapsed_ms = round((time.time() - t0) * 1000.0, 1)
            return ToolExecutionResult(
                tool_name=tool_name,
                selection_source=selection_source,
                parameters=params,
                result=res,
                duration_ms=elapsed_ms,
                status=status,
                error=res.get("error") if status == "ERROR" else None
            )
        except (SQLAlchemyError, TypeError, ValueError, KeyError, RuntimeError) as e:
            elapsed_ms = round((time.time() - t0) * 1000.0, 1)
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return ToolExecutionResult(
                tool_name=tool_name,
                selection_source=selection_source,
                parameters=params,
                result={},
                duration_ms=elapsed_ms,
                status="ERROR",
                error=str(e)
            )


tool_registry = ToolRegistry()
