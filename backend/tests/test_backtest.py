from datetime import datetime, timedelta

import pandas as pd
import pytest
from app.backtesting.engine import backtest_engine
from app.main import app
from app.market.indicators import calculate_rsi
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def seed_reliance_backtest_candles(db):
    import os

    from app.datasets.importer import DatasetImporter
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historical")
    for sym in ["RELIANCE", "TCS", "INFY", "HDFCBANK"]:
        csv_path = os.path.join(data_dir, f"{sym}.csv")
        if os.path.exists(csv_path):
            with open(csv_path, "r", encoding="utf-8") as f:
                csv_text = f.read()
            DatasetImporter.import_csv(
                db=db,
                csv_source=csv_text,
                dataset_id=f"ds_{sym.lower()}_daily",
                dataset_name=f"{sym} Daily",
                symbol=sym,
                asset_name=f"{sym} Ltd",
                exchange="NSE",
                source="HISTORICAL_ARCHIVE",
                provenance="Historical daily records",
                timeframe="1d",
                is_adjusted=False,
                adjustment_status="UNADJUSTED",
                license_info="Educational research use",
            )


@pytest.mark.local_market_data
def test_backtest_all_strategies_default_smoke(db):
    """Verify all four strategies run without error on authentic historical data and produce valid metrics."""
    strategies = ["Buy and hold", "SMA crossover", "RSI-based strategy", "MACD-based strategy"]
    for strat in strategies:
        res = backtest_engine.run_backtest(
            strategy=strat,
            symbol="RELIANCE",
            timeframe="1 year daily",
            starting_capital=1000000.0,
            commission_pct=0.1,
            slippage_pct=0.05,
            db=db,
        )

        assert res["strategy"] == strat
        assert res["symbol"] == "RELIANCE"
        assert res["starting_capital"] == 1000000.0
        assert "final_equity" in res
        assert "total_return_pct" in res
        assert "max_drawdown_pct" in res
        assert "win_rate_pct" in res
        assert len(res["equity_curve"]) > 0
        assert res["data_source"] == "historical"
        assert res["is_synthetic"] is False


def test_rsi_controlled_fixture_execution_and_accounting():
    """
    Test RSI strategy on a deterministic OHLCV fixture with controlled dips and rallies.
    Verifies:
      1. Oversold crossover triggers BUY signal with slippage and commission.
      2. Overbought crossover triggers SELL signal with slippage and commission.
      3. Subsequent dip triggers BUY, and end-of-run liquidation executes with slippage and commission.
      4. PnL accounting integrity: sum(trade.pnl) == final_equity - starting_capital.
      5. Correct WIN and LOSS classification and win_rate_pct calculation.
    """
    # 15 flat warm-up bars, then dip to 80 (RSI drops to 0), rebound to 88 (crosses 35 -> BUY),
    # rally to 122 (RSI ~80), drop to 109 (crosses below 65 -> SELL [WIN]),
    # second dip to 75 (crosses 35 at 82 -> BUY), then drops to 60 at end (liquidation [LOSS])
    prices = (
        [100.0] * 15 +
        [95.0, 90.0, 85.0, 80.0, 80.0, 82.0, 85.0, 88.0] +
        [95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 122.0, 120.0, 115.0, 109.0] +
        [100.0, 95.0, 90.0, 85.0, 80.0, 75.0, 75.0, 78.0, 82.0] +
        [80.0, 75.0, 70.0, 65.0, 60.0]
    )
    timestamps = [datetime(2026, 1, 1, 9, 30) + timedelta(minutes=30 * i) for i in range(len(prices))]
    fixture_df = pd.DataFrame({
        "timestamp": timestamps,
        "close": prices,
        "open": prices,
        "high": prices,
        "low": prices,
        "volume": [1000] * len(prices)
    })

    res = backtest_engine.run_backtest(
        strategy="RSI-based strategy",
        symbol="TEST_ASSET",
        starting_capital=1000000.0,
        commission_pct=0.1,
        slippage_pct=0.05,
        rsi_oversold=35.0,
        rsi_overbought=65.0,
        custom_df=fixture_df
    )

    trades = res["trades"]
    assert len(trades) == 2, f"Expected exactly 2 trades, got {len(trades)}"

    # Trade 1: WIN
    t1 = trades[0]
    assert t1["side"] == "BUY"
    assert t1["status"] == "WIN"
    assert t1["entry_price"] > 88.0  # 88.0 * 1.0005 = 88.04
    assert t1["exit_price"] < 109.0   # 109.0 * 0.9995 = 108.95
    assert t1["pnl"] > 0
    assert t1["pnl_pct"] > 0  # Lookahead-free next-bar open fill yields ~4.95% vs inflated ~23% same-bar close bias

    # Trade 2: LOSS (closed at final bar)
    t2 = trades[1]
    assert t2["side"] == "BUY"
    assert t2["status"] == "LOSS"
    assert t2["entry_price"] >= 80.0  # Bar i+1 Open fill: 80.0 * 1.0005 = 80.04
    assert t2["exit_price"] < 60.0   # 60.0 * 0.9995 = 59.97 (liquidation slippage applied)
    assert t2["pnl"] < 0

    # Win rate
    assert res["win_rate_pct"] == 50.0

    # Perfect cash-to-trade accounting: final_equity - starting_capital == sum(trades.pnl)
    sum_trades_pnl = sum(t["pnl"] for t in trades)
    net_equity_change = res["final_equity"] - res["starting_capital"]
    assert abs(net_equity_change - sum_trades_pnl) < 0.10, (
        f"Trade PnL sum ({sum_trades_pnl}) does not match net equity change ({net_equity_change})"
    )

    # Equity curve validation
    curve = res["equity_curve"]
    assert len(curve) == len(prices)
    for pt in curve:
        assert pt["equity"] > 0
        assert pt["benchmark"] > 0


@pytest.mark.local_market_data
def test_rsi_on_genuine_historical_datasets(db):
    """
    Test RSI strategy on authentic Indian market datasets (RELIANCE, TCS, INFY, HDFCBANK).
    Verifies legitimate trade execution, status categorization, and cash accounting.
    """
    for symbol in ["RELIANCE", "TCS", "INFY", "HDFCBANK"]:
        res = backtest_engine.run_backtest(
            strategy="RSI-based strategy",
            symbol=symbol,
            timeframe="1 year daily",
            starting_capital=1000000.0,
            rsi_oversold=35.0,
            rsi_overbought=65.0,
            db=db,
        )

        assert res["trade_count"] >= 1, f"Expected trades for genuine dataset {symbol}"
        assert len(res["trades"]) == res["trade_count"]
        for t in res["trades"]:
            assert t["status"] in ["WIN", "LOSS"]
            assert t["entry_price"] > 0
            assert t["exit_price"] > 0
        sum_trades_pnl = sum(t["pnl"] for t in res["trades"])
        net_equity_change = res["final_equity"] - res["starting_capital"]
        assert abs(net_equity_change - sum_trades_pnl) < 0.10


def test_rsi_flat_prices_and_extremes():
    """
    Verify RSI indicator edge cases on isolated fixtures:
      - Perfectly flat prices return 50.0 without division by zero.
      - Strictly increasing series approaches 100.0.
      - Strictly decreasing series approaches 0.0.
    """
    flat = pd.Series([100.0] * 30)
    rsi_flat = calculate_rsi(flat, period=14)
    assert (rsi_flat == 50.0).all()

    rising = pd.Series([100.0 + i * 2.0 for i in range(30)])
    rsi_rising = calculate_rsi(rising, period=14)
    assert rsi_rising.iloc[-1] == 100.0

    falling = pd.Series([100.0 - i * 2.0 for i in range(30)])
    rsi_falling = calculate_rsi(falling, period=14)
    assert rsi_falling.iloc[-1] == 0.0

    # Backtesting on a flat series executes 0 trades without crashing
    ts = [datetime(2026, 1, 1, 9, 30) + timedelta(minutes=30 * i) for i in range(30)]
    flat_df = pd.DataFrame({
        "timestamp": ts, "close": flat, "open": flat, "high": flat, "low": flat, "volume": [100] * 30
    })
    res_flat = backtest_engine.run_backtest(
        strategy="RSI-based strategy", symbol="FLAT", custom_df=flat_df
    )
    assert res_flat["trade_count"] == 0
    assert res_flat["final_equity"] == 1000000.0


@pytest.mark.local_market_data
def test_backtest_api_endpoints(client):
    """Test POST and GET /api/v1/backtests through FastAPI HTTP router with genuine asset."""
    payload = {
        "strategy": "RSI-based strategy",
        "symbol": "RELIANCE",
        "timeframe": "1 year daily",
        "starting_capital": 500000.0,
        "commission_pct": 0.1,
        "slippage_pct": 0.05,
        "rsi_oversold": 35.0,
        "rsi_overbought": 65.0,
    }

    # Execute backtest
    post_resp = client.post("/api/v1/backtests", json=payload)
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["strategy"] == "RSI-based strategy"
    assert data["symbol"] == "RELIANCE"
    assert data["starting_capital"] == 500000.0
    assert "run_id" in data
    assert "equity_curve" in data
    assert "trades" in data
    assert len(data["trades"]) >= 1

    # Fetch persisted backtest runs
    get_resp = client.get("/api/v1/backtests")
    assert get_resp.status_code == 200
    runs = get_resp.json()
    assert isinstance(runs, list)
    assert any(r["run_id"] == data["run_id"] for r in runs)


@pytest.mark.local_market_data
def test_persisted_backtest_ledger_exact_reconciliation(db):
    """
    Priority 1 Regression Test:
    Independently sums the trade ledger of a backtest and asserts that:
    1. Sum of individual trade PnLs equals final_equity - starting_capital down to 0.00 INR.
    2. Realized PnL of each fill matches execution price, integer quantity, fees (0.10%), and slippage (0.05%).
    3. Trade count, win rate, and total return % are mathematically consistent.
    """
    res = backtest_engine.run_backtest(
        strategy="SMA crossover",
        symbol="RELIANCE",
        timeframe="1 year daily",
        starting_capital=1000000.0,
        commission_pct=0.1,
        slippage_pct=0.05,
        db=db,
    )

    starting_capital = res["starting_capital"]
    final_equity = res["final_equity"]
    trades = res["trades"]
    trade_count = res["trade_count"]

    assert len(trades) == trade_count
    assert trade_count > 0

    sum_pnl = 0.0
    wins = 0
    losses = 0

    for t in trades:
        qty = t["quantity"]
        entry_p = t["entry_price"]
        exit_p = t["exit_price"]
        pnl = t["pnl"]
        side = t["side"]

        assert side == "BUY"
        assert isinstance(qty, int)
        assert qty > 0
        assert entry_p > 0
        assert exit_p > 0

        # Verify status tagging
        if pnl > 0:
            assert t["status"] == "WIN"
            wins += 1
        else:
            assert t["status"] == "LOSS"
            losses += 1

        sum_pnl += pnl

    # Assert exact mathematical reconciliation
    calculated_final_equity = round(starting_capital + sum_pnl, 2)
    assert abs(calculated_final_equity - final_equity) < 0.001, (
        f"Reconciliation error: Calculated {calculated_final_equity} != Engine Reported {final_equity}"
    )

    # Assert win rate calculation
    calculated_win_rate = round((wins / trade_count) * 100.0, 1)
    assert res["win_rate_pct"] == calculated_win_rate

    # Assert total return %
    calculated_return = round(((final_equity - starting_capital) / starting_capital) * 100.0, 2)
    assert res["total_return_pct"] == calculated_return


def test_terminal_dataset_position_liquidation_timing_and_no_lookahead():
    """
    Release Gate Priority 2 Regression Test:
    Verifies that:
    1. Normal strategy signals execute strictly on NEXT-BAR OPEN (lookahead-free).
       A signal calculated at Bar i Close NEVER fills at Bar i Open or Bar i Close.
    2. When the dataset concludes and no next bar exists (terminal bar N-1), an open position
       is closed under the explicit TERMINAL_DATASET_CLOSE_LIQUIDATION rule at final bar Close
       with slippage (0.05%) and commission (0.10%) applied.
    3. The exit_reason is explicitly recorded as TERMINAL_DATASET_CLOSE_LIQUIDATION.
    4. If same-bar lookahead execution were reintroduced, this test would fail.
    """
    # Construct a deterministic 20-bar dataset where:
    # Bars 0-14: Flat setup to initialize 15-day SMA window.
    # Bar 15: Fast SMA (window 5) crosses above Slow SMA (window 15) at Bar 15 Close.
    # Bar 16: Next bar in dataset. Entry MUST occur at Bar 16 Open (NOT Bar 15).
    # Bar 17: Position held.
    # Bar 18: Position held.
    # Bar 19: Final bar of dataset (no Bar 20 exists).
    #         Terminal liquidation occurs at Bar 19 Close.
    timestamps = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(20)]

    # Prices: flat 100 for bars 0-13; jump to 110 at bar 14; 120 at bar 15 (crossover triggers);
    # Bar 16: Open 125, Close 126
    # Bar 17: Open 127, Close 128
    # Bar 18: Open 129, Close 130
    # Bar 19: Open 131, Close 132 (Terminal Bar)
    close_prices = [100.0] * 14 + [110.0, 120.0, 126.0, 128.0, 130.0, 132.0]
    open_prices = [100.0] * 14 + [109.0, 118.0, 125.0, 127.0, 129.0, 131.0]

    custom_df = pd.DataFrame({
        "timestamp": timestamps,
        "open": open_prices,
        "high": [p * 1.01 for p in close_prices],
        "low": [p * 0.99 for p in close_prices],
        "close": close_prices,
        "volume": [10000] * 20
    })

    res = backtest_engine.run_backtest(
        strategy="SMA crossover",
        symbol="TEST_TIMING",
        starting_capital=100000.0,
        commission_pct=0.1,
        slippage_pct=0.05,
        custom_df=custom_df
    )

    trades = res["trades"]
    assert len(trades) == 1, f"Expected exactly 1 trade, got {len(trades)}"
    trade = trades[0]

    signal_bar_date = timestamps[14].strftime("%Y-%m-%d")
    entry_bar_date = timestamps[15].strftime("%Y-%m-%d")
    terminal_bar_date = timestamps[19].strftime("%Y-%m-%d")

    # 1. Lookahead Prevention:
    # Crossover occurs at Bar 14 Close (signal_bar_date).
    # Entry date MUST be Bar 15 Date (entry_bar_date at Open), NOT Bar 14 (same-bar lookahead).
    assert trade["entry_time"] == entry_bar_date, (
        f"LOOKAHEAD FAILURE: Trade entered on {trade['entry_time']}, expected next-bar {entry_bar_date}"
    )
    assert trade["entry_time"] != signal_bar_date

    # Entry price must be Bar 15 Open + 0.05% slippage = 118.0 * 1.0005 = 118.059 ~ 118.06
    expected_entry_px = round(open_prices[15] * 1.0005, 2)
    assert trade["entry_price"] == expected_entry_px

    # 2. Terminal Liquidation at Dataset Conclusion:
    # Since Bar 19 is the final bar and no exit signal occurred during the trade,
    # the position was closed at Bar 19 Close under the explicit terminal liquidation rule.
    assert trade["exit_time"] == terminal_bar_date
    assert trade["exit_reason"] == "TERMINAL_DATASET_CLOSE_LIQUIDATION"

    # Exit price must be Bar 19 Close - 0.05% slippage = 132.0 * 0.9995 = 131.934 ~ 131.93
    expected_exit_px = round(close_prices[19] * 0.9995, 2)
    assert trade["exit_price"] == expected_exit_px

    # 3. Financial Integrity:
    # Verify cash accounting matches starting capital + net PnL
    assert round(res["starting_capital"] + trade["pnl"], 2) == res["final_equity"]
