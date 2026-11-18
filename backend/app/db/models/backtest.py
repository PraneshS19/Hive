from datetime import datetime

from app.db.base import Base, get_utc_now
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), default="RELIANCE")
    timeframe: Mapped[str] = mapped_column(String(50), default="1 year daily")
    starting_capital: Mapped[float] = mapped_column(Float, default=1000000.0)
    final_equity: Mapped[float] = mapped_column(Float, default=1064000.0)
    total_return_pct: Mapped[float] = mapped_column(Float, default=6.4)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=3.2)
    trade_count: Mapped[int] = mapped_column(Integer, default=14)
    win_rate_pct: Mapped[float] = mapped_column(Float, default=57.1)
    sharpe_ratio: Mapped[float] = mapped_column(Float, default=1.85)
    equity_curve_json: Mapped[str] = mapped_column(Text, default="[]")
    trades_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
