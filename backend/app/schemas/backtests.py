from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    strategy: str = Field(default="SMA crossover", description="Buy and hold, SMA crossover, RSI-based strategy, MACD-based strategy")
    symbol: str = Field(default="RELIANCE")
    timeframe: str = Field(default="1d")
    starting_capital: float = Field(default=1000000.0, gt=1000.0)
    commission_pct: float = Field(default=0.1, ge=0.0)
    slippage_pct: float = Field(default=0.05, ge=0.0)
    rsi_oversold: float = Field(default=35.0, ge=10.0, le=50.0, description="RSI oversold entry threshold")
    rsi_overbought: float = Field(default=65.0, ge=50.0, le=90.0, description="RSI overbought exit threshold")
    data_source: str = Field(default="historical", description="'historical'")
    dataset_id: str | None = Field(default=None, description="Registered dataset ID for historical backtest")
    start_date: str | None = Field(default=None, description="Optional start date filter (ISO or YYYY-MM-DD)")
    end_date: str | None = Field(default=None, description="Optional end date filter (ISO or YYYY-MM-DD)")


class BacktestTrade(BaseModel):
    id: int
    symbol: str
    entry_time: str
    exit_time: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    status: str
    exit_reason: str | None = "STRATEGY_SIGNAL_EXIT"
    accounting_trace: dict[str, Any] | None = None


class BacktestEquityPoint(BaseModel):
    time: str
    equity: float
    benchmark: float


class BacktestResponse(BaseModel):
    run_id: str
    strategy: str
    symbol: str
    timeframe: str
    starting_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    trade_count: int
    win_rate_pct: float
    sharpe_ratio: float
    profit_factor: float
    equity_curve: list[BacktestEquityPoint]
    trades: list[BacktestTrade]
    dataset_id: str | None = None
    dataset_checksum: str | None = None
    observation_count: int | None = None
    raw_candle_count: int | None = None
    non_trading_artifacts_excluded_count: int | None = 0
    date_range: dict[str, str | None] | None = None
    data_source: str = "historical"
    is_synthetic: bool = False
    notes: str = "Historical backtest on authentic market data. Simulation only."
    created_at: datetime
