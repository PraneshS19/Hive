from typing import Any

import numpy as np
import pandas as pd


def calculate_sma(series: pd.Series, window: int = 20) -> pd.Series:
    """Calculate Simple Moving Average."""
    return series.rolling(window=window, min_periods=1).mean()


def calculate_ema(series: pd.Series, span: int = 20) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    # Handle zero division: when loss is 0 and gain > 0 -> 100; when gain is 0 and loss > 0 -> 0; flat -> 50
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    all_gains = (avg_gain > 0) & (avg_loss == 0)
    all_losses = (avg_gain == 0) & (avg_loss > 0)
    is_flat = (avg_gain == 0) & (avg_loss == 0)

    rsi = rsi.where(~all_gains, 100.0)
    rsi = rsi.where(~all_losses, 0.0)
    rsi = rsi.where(~is_flat, 50.0)
    return rsi.fillna(50.0)


def calculate_macd(
    series: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> dict[str, pd.Series]:
    """Calculate Moving Average Convergence Divergence (MACD)."""
    fast_ema = calculate_ema(series, span=fast_period)
    slow_ema = calculate_ema(series, span=slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal_period, adjust=False, min_periods=1).mean()
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram
    }


def calculate_bollinger_bands(
    series: pd.Series,
    window: int = 20,
    num_std: float = 2.0
) -> dict[str, pd.Series]:
    """Calculate Bollinger Bands."""
    middle = calculate_sma(series, window=window)
    std = series.rolling(window=window, min_periods=1).std().fillna(0.0)
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower
    }


def calculate_volatility(series: pd.Series, window: int = 20) -> float | None:
    """
    Calculate annualized rolling volatility from daily log returns.
    Standard financial annualization convention for daily market sessions:
    annualized_volatility = std(daily_log_returns, ddof=1) * sqrt(252)

    Fails safe: returns None if fewer than 2 valid return observations are available.
    Does not substitute fabricated default volatility estimates.
    Returns 0.0 if prices are completely flat (zero variance).
    """
    if series is None or len(series) < 2:
        return None
    clean = series.dropna()
    clean = clean[clean > 0]
    if len(clean) < 2:
        return None
    log_returns = np.log(clean / clean.shift(1)).dropna()
    if len(log_returns) < 2:
        return None
    sub_returns = log_returns.iloc[-min(len(log_returns), window):]
    if len(sub_returns) < 2:
        return None
    vol = sub_returns.std(ddof=1)
    if np.isnan(vol) or np.isinf(vol) or vol < 0:
        return None
    if vol == 0.0:
        return 0.0
    annualized = vol * np.sqrt(252)
    if np.isnan(annualized) or np.isinf(annualized):
        return None
    return round(float(annualized), 4)


def calculate_gaussian_var_cvar(
    daily_vol: float | None,
    alpha: float = 0.99
) -> tuple[float | None, float | None]:
    """
    Compute exact analytic Gaussian Parametric Value-at-Risk (VaR) and
    Conditional Value-at-Risk (CVaR / Expected Shortfall).

    Mathematical Foundation:
      Assumes zero-mean continuous Gaussian returns R ~ N(0, sigma^2).
      Loss L = -R ~ N(0, sigma^2).
      VaR_alpha = sigma * z_alpha, where z_alpha = Phi^(-1)(alpha).
      CVaR_alpha = E[L | L >= VaR_alpha] = sigma * (phi(z_alpha) / (1 - alpha)),
      where phi(z) = (1 / sqrt(2*pi)) * exp(-z^2 / 2).

    Parameters:
      daily_vol: Daily return standard deviation (sigma). If None or negative, returns (None, None).
      alpha: Confidence level (default 0.99 for 99% tail risk).

    Model Assumptions & Known Limitations:
      1. Zero drift assumption: daily mean return mu is assumed to be 0.
      2. Distributional assumption: returns are assumed to be independent and Gaussian.
      3. Critical limitation: Empirical asset returns exhibit leptokurtosis (fat tails)
         and negative skewness. Gaussian CVaR underestimates tail risk during extreme
         market crash regimes.

    Returns:
      (var_pct, cvar_pct) as percentages, e.g. (2.60, 4.21), or (None, None).
    """
    if daily_vol is None or daily_vol < 0:
        return None, None
    if daily_vol == 0.0:
        return 0.0, 0.0

    # Gaussian quantiles and density constants
    if abs(alpha - 0.99) < 1e-4:
        z_alpha = 2.3263478740408408
        phi_z = 0.02665214224752288
        cvar_factor = phi_z / (1.0 - alpha)  # 2.6652142
    elif abs(alpha - 0.95) < 1e-4:
        z_alpha = 1.6448536269514722
        phi_z = 0.10313564037680226
        cvar_factor = phi_z / (1.0 - alpha)  # 2.0627128
    else:
        # General Gaussian formula
        # Use erf inverse approximation
        from scipy import stats
        z_alpha = stats.norm.ppf(alpha)
        phi_z = (1.0 / np.sqrt(2.0 * np.pi)) * np.exp(-0.5 * z_alpha * z_alpha)
        cvar_factor = phi_z / (1.0 - alpha)

    var_pct = round(z_alpha * daily_vol * 100.0, 2)
    cvar_pct = round(cvar_factor * daily_vol * 100.0, 2)
    return var_pct, cvar_pct


def calculate_drawdown_series(equity_series: pd.Series) -> pd.Series:
    """Calculate running drawdown percentage from peak."""
    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak.replace(0, 1.0) * 100.0
    return drawdown


def compute_all_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute full technical indicator suite from OHLCV candle DataFrame.
    """
    if df.empty or "close" not in df.columns:
        return {
            "sma_20": None,
            "ema_20": None,
            "rsi_14": None,
            "macd": None,
            "macd_signal": None,
            "macd_hist": None,
            "bb_upper": None,
            "bb_middle": None,
            "bb_lower": None,
            "volatility": None,
            "trend": "Neutral",
            "momentum": "Neutral"
        }

    close = df["close"]
    sma20 = calculate_sma(close, 20).iloc[-1]
    ema20 = calculate_ema(close, 20).iloc[-1]
    rsi14 = calculate_rsi(close, 14).iloc[-1]
    macd_res = calculate_macd(close)
    bb_res = calculate_bollinger_bands(close)
    vol = calculate_volatility(close)

    latest_close = close.iloc[-1]
    latest_sma = float(sma20)
    latest_rsi = float(rsi14)

    # Determine qualitative trend and momentum deterministically
    if latest_close > latest_sma * 1.01:
        trend = "Bullish"
    elif latest_close < latest_sma * 0.99:
        trend = "Bearish"
    else:
        trend = "Neutral"

    if latest_rsi > 60:
        momentum = "Strong Positive"
    elif latest_rsi < 40:
        momentum = "Weak / Oversold"
    else:
        momentum = "Neutral"

    return {
        "sma_20": round(float(sma20), 2),
        "ema_20": round(float(ema20), 2),
        "rsi_14": round(float(rsi14), 2),
        "macd": round(float(macd_res["macd"].iloc[-1]), 3),
        "macd_signal": round(float(macd_res["signal"].iloc[-1]), 3),
        "macd_hist": round(float(macd_res["histogram"].iloc[-1]), 3),
        "bb_upper": round(float(bb_res["upper"].iloc[-1]), 2),
        "bb_middle": round(float(bb_res["middle"].iloc[-1]), 2),
        "bb_lower": round(float(bb_res["lower"].iloc[-1]), 2),
        "volatility": vol,
        "trend": trend,
        "momentum": momentum
    }
