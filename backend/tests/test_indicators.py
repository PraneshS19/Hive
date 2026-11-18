import numpy as np
import pandas as pd
import pytest
from app.market.indicators import (
    calculate_bollinger_bands,
    calculate_drawdown_series,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    calculate_volatility,
    compute_all_indicators,
)


def test_sma_and_ema_calculations():
    data = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    sma = calculate_sma(data, window=3)
    assert round(sma.iloc[-1], 2) == 14.0  # (13+14+15)/3

    ema = calculate_ema(data, span=3)
    assert ema.iloc[-1] > 14.0


def test_rsi_bounds_and_values():
    # Uptrend prices should have high RSI
    uptrend = pd.Series([10.0 + i * 2.0 for i in range(25)])
    rsi_up = calculate_rsi(uptrend, period=14)
    assert 0 <= rsi_up.iloc[-1] <= 100
    assert rsi_up.iloc[-1] > 70.0

    # Downtrend prices should have low RSI
    downtrend = pd.Series([100.0 - i * 2.0 for i in range(25)])
    rsi_down = calculate_rsi(downtrend, period=14)
    assert 0 <= rsi_down.iloc[-1] <= 100
    assert rsi_down.iloc[-1] < 30.0


def test_macd_and_bollinger():
    data = pd.Series([100 + np.sin(i) * 5 for i in range(40)])
    macd = calculate_macd(data)
    assert "macd" in macd and "signal" in macd and "histogram" in macd

    bb = calculate_bollinger_bands(data, window=10)
    assert "upper" in bb and "middle" in bb and "lower" in bb
    assert (bb["upper"] >= bb["middle"]).all()
    assert (bb["middle"] >= bb["lower"]).all()


def test_drawdown_calculation():
    equity = pd.Series([1000.0, 1100.0, 1050.0, 990.0, 1200.0])
    dd = calculate_drawdown_series(equity)
    assert dd.iloc[0] == 0.0
    assert dd.iloc[1] == 0.0
    assert dd.iloc[2] < 0.0
    assert round(dd.iloc[3], 2) == -10.0  # (990-1100)/1100 * 100
    assert dd.iloc[4] == 0.0


def test_compute_all_indicators():
    df = pd.DataFrame({
        "close": [100.0 + i * 0.5 for i in range(30)],
        "open": [100.0 + i * 0.5 for i in range(30)],
        "high": [101.0 + i * 0.5 for i in range(30)],
        "low": [99.0 + i * 0.5 for i in range(30)],
        "volume": [10000.0] * 30,
    })
    ind = compute_all_indicators(df)
    assert ind["trend"] in ("Bullish", "Bearish", "Neutral")
    assert ind["rsi_14"] is not None
    assert ind["macd"] is not None


@pytest.mark.local_market_data
def test_annualized_volatility_daily_log_returns():
    """
    Regression test: ensures annualized volatility uses daily log returns and sqrt(252),
    and strictly fails if an arbitrary factor like sqrt(13) is reintroduced.
    """
    # Create controlled price series with constant daily return of +1%
    prices = pd.Series([100.0 * (1.01 ** i) for i in range(30)])
    log_ret = np.log(prices / prices.shift(1)).dropna()
    expected_daily_std = log_ret.rolling(window=20).std(ddof=1).iloc[-1]
    expected_annualized = expected_daily_std * np.sqrt(252)

    computed = calculate_volatility(prices, window=20)
    assert abs(computed - round(expected_annualized, 4)) < 1e-5

    # Flawed calculation with factor 13
    flawed_calculation = expected_daily_std * np.sqrt(252 * 13)
    # Assert computed is NOT inflated by sqrt(13)
    assert computed < flawed_calculation * 0.5, f"Volatility is inflated by extra factor: {computed} vs {flawed_calculation}"

    # Test on real RELIANCE dataset
    reliance_df = pd.read_csv("backend/data/historical/RELIANCE.csv")
    reliance_vol = calculate_volatility(reliance_df["Close"], window=20)
    assert 0.15 < reliance_vol < 0.35, f"Expected realistic equity volatility (15%-35%), got {reliance_vol*100:.2f}%"
    assert abs(reliance_vol - 0.2510) < 0.005, f"Expected ~25.10% on latest RELIANCE 20-day window, got {reliance_vol*100:.2f}%"
