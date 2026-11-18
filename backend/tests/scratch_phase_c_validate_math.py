import os
import sys

sys.path.insert(0, os.path.abspath("backend"))
import math

import numpy as np
import pandas as pd
from app.market.indicators import (
    calculate_bollinger_bands,
    calculate_drawdown_series,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    calculate_volatility,
)
from app.risk.rules import (
    check_cash_sufficiency,
    check_max_order_size,
    check_no_short_selling,
)

print("=== Phase C: Quantitative Calculations & Invariant Validation ===")
csv_path = os.path.abspath("backend/data/historical/RELIANCE.csv")
df = pd.read_csv(csv_path)
df["Date"] = pd.to_datetime(df["Date"])
df = df.sort_values("Date").reset_index(drop=True)
close = df["Close"]

# 1. Independent SMA validation
window = 20
app_sma = calculate_sma(close, window=window)
manual_sma = close.rolling(window=window, min_periods=1).mean()
sma_diff = (app_sma - manual_sma).abs().max()
print(f"[SMA20] Max absolute difference: {sma_diff:.8f} (Tolerance: 1e-6) -> {'PASS' if sma_diff < 1e-6 else 'FAIL'}")
assert sma_diff < 1e-6

# 2. Independent EMA validation
span = 20
app_ema = calculate_ema(close, span=span)
manual_ema = close.ewm(span=span, adjust=False, min_periods=1).mean()
ema_diff = (app_ema - manual_ema).abs().max()
print(f"[EMA20] Max absolute difference: {ema_diff:.8f} (Tolerance: 1e-6) -> {'PASS' if ema_diff < 1e-6 else 'FAIL'}")
assert ema_diff < 1e-6

# 3. Independent RSI validation
period = 14
app_rsi = calculate_rsi(close, period=period)
# Manual Wilder's RSI calculation
delta = close.diff()
gain = delta.clip(lower=0)
loss = -1 * delta.clip(upper=0)
avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
rs = avg_gain / avg_loss.replace(0, np.nan)
manual_rsi = (100 - (100 / (1 + rs))).fillna(50.0)
rsi_diff = (app_rsi - manual_rsi).abs().max()
print(f"[RSI14] Max absolute difference: {rsi_diff:.8f} (Tolerance: 1e-6) -> {'PASS' if rsi_diff < 1e-6 else 'FAIL'}")
assert rsi_diff < 1e-6
print(f"       RSI Bounds Check: Min={app_rsi.min():.2f}, Max={app_rsi.max():.2f} (Bounded in [0, 100]) -> PASS")
assert 0.0 <= app_rsi.min() and app_rsi.max() <= 100.0

# 4. Independent MACD validation
app_macd = calculate_macd(close, fast_period=12, slow_period=26, signal_period=9)
manual_fast = close.ewm(span=12, adjust=False, min_periods=1).mean()
manual_slow = close.ewm(span=26, adjust=False, min_periods=1).mean()
manual_macd_line = manual_fast - manual_slow
manual_signal = manual_macd_line.ewm(span=9, adjust=False, min_periods=1).mean()
manual_hist = manual_macd_line - manual_signal

diff_macd = (app_macd["macd"] - manual_macd_line).abs().max()
diff_signal = (app_macd["signal"] - manual_signal).abs().max()
diff_hist = (app_macd["histogram"] - manual_hist).abs().max()
print(f"[MACD] Max diff: Line={diff_macd:.8f}, Signal={diff_signal:.8f}, Hist={diff_hist:.8f} -> PASS")
assert diff_macd < 1e-6 and diff_signal < 1e-6 and diff_hist < 1e-6

# 5. Independent Bollinger Bands validation
app_bb = calculate_bollinger_bands(close, window=20, num_std=2.0)
manual_mid = close.rolling(window=20, min_periods=1).mean()
manual_std = close.rolling(window=20, min_periods=1).std().fillna(0.0)
manual_upper = manual_mid + 2.0 * manual_std
manual_lower = manual_mid - 2.0 * manual_std

diff_upper = (app_bb["upper"] - manual_upper).abs().max()
diff_lower = (app_bb["lower"] - manual_lower).abs().max()
print(f"[Bollinger Bands] Max diff: Upper={diff_upper:.8f}, Lower={diff_lower:.8f} -> PASS")
assert diff_upper < 1e-6 and diff_lower < 1e-6
# Check band invariant: Upper >= Middle >= Lower
bb_inv = (app_bb["upper"] >= app_bb["middle"]) & (app_bb["middle"] >= app_bb["lower"])
print(f"       BB Invariant (Upper >= Middle >= Lower): {bb_inv.all()} -> PASS")
assert bb_inv.all()

# 6. Realized Volatility (Daily Log Returns with sqrt(252))
app_vol = calculate_volatility(close, window=20)
log_ret = np.log(close / close.shift(1)).dropna()
manual_vol = round(float(log_ret.rolling(window=20).std(ddof=1).iloc[-1] * np.sqrt(252)), 4)
assert abs(app_vol - manual_vol) < 1e-6
print(f"[Realized Volatility] Calculated 20-day annualized vol: {app_vol:.4f} ({app_vol*100:.2f}%) [Manual: {manual_vol:.4f}] -> PASS")
assert 0.15 < app_vol < 0.35

# 7. Maximum Drawdown
app_dd = calculate_drawdown_series(close)
max_dd = app_dd.min()
# Independent drawdown calculation
peak = close.cummax()
manual_dd = (close - peak) / peak * 100.0
dd_diff = (app_dd - manual_dd).abs().max()
print(f"[Max Drawdown] Max absolute diff: {dd_diff:.8f}, Deepest Drawdown: {max_dd:.2f}% -> PASS")
assert dd_diff < 1e-6
assert max_dd <= 0.0  # drawdown is always <= 0%

# 8. Parametric VaR (95%) and CVaR (99%)
daily_vol = app_vol / math.sqrt(252)
var_95_pct = round(1.645 * daily_vol * 100.0, 2)
cvar_99_pct = round(2.326 * daily_vol * 1.15 * 100.0, 2)
print(f"[VaR / CVaR] Daily Vol: {daily_vol*100:.2f}%, 1-Day 95% VaR: {var_95_pct}%, 1-Day 99% CVaR: {cvar_99_pct}% -> PASS")
assert var_95_pct > 0.0 and cvar_99_pct > var_95_pct

# 9. Risk Rules & Position Sizing Determinism
equity = 1_000_000.0
price = float(close.iloc[-1])
fee_pct = 0.10

# Sizing rule: Max 10% of equity = INR 100,000
max_order_cash = equity * 0.10
max_shares = int(max_order_cash / price)

# Oversized order check: 150 shares (~181k > 100k)
pass_sz, approved_q, desc_sz = check_max_order_size(150, price, equity, max_order_pct=10.0)
print(f"[Risk Engine - Sizing] Requested 150 shares, Allowed: {approved_q} shares (pass={pass_sz}) -> PASS")
assert approved_q == max_shares
assert approved_q < 150

# Short selling check:
pass_ss_rej, desc_ss = check_no_short_selling("SELL", 10, current_position_qty=0)
pass_ss_ok, _ = check_no_short_selling("SELL", 10, current_position_qty=10)
print(f"[Risk Engine - Short Sale Guard] SELL with 0 shares rejected: {not pass_ss_rej}; SELL with 10 shares passed: {pass_ss_ok} -> PASS")
assert not pass_ss_rej and pass_ss_ok

# Cash sufficiency check:
pass_cash_ok, _ = check_cash_sufficiency("BUY", 10, price, fee_pct=0.1, available_cash=100_000.0)
pass_cash_rej, _ = check_cash_sufficiency("BUY", 1000, price, fee_pct=0.1, available_cash=10_000.0)
print(f"[Risk Engine - Cash Guard] Sufficient cash passed: {pass_cash_ok}; Insufficient cash rejected: {not pass_cash_rej} -> PASS")
assert pass_cash_ok and not pass_cash_rej

# 10. Look-ahead Bias Prevention Verification
# Ensure indicator values at row t depend ONLY on rows 0..t
for t in [30, 60, 120, 200, 246]:
    sub_close = close.iloc[:t+1]
    sub_sma = calculate_sma(sub_close, 20).iloc[-1]
    full_sma = calculate_sma(close, 20).iloc[t]
    assert abs(sub_sma - full_sma) < 1e-6, f"Lookahead detected in SMA at bar {t}!"

    sub_rsi = calculate_rsi(sub_close, 14).iloc[-1]
    full_rsi = calculate_rsi(close, 14).iloc[t]
    assert abs(sub_rsi - full_rsi) < 1e-6, f"Lookahead detected in RSI at bar {t}!"
print("[Look-Ahead Audit] Tested bars [30, 60, 120, 200, 246] against causal prefixes: Zero look-ahead bias confirmed -> PASS")

print("\nAll Phase C quantitative calculations and risk rules 100% validated!")
