import asyncio
import os

import numpy as np
import pandas as pd
import pytest
from app.agents.risk_officer import RiskOfficer
from app.db.models.market import Candle
from app.db.session import SessionLocal
from app.market.indicators import (
    calculate_gaussian_var_cvar,
    calculate_volatility,
    compute_all_indicators,
)


def test_volatility_edge_case_empty_series():
    """Volatility on empty series returns None, not a fabricated default."""
    empty = pd.Series([], dtype=float)
    assert calculate_volatility(empty) is None


def test_volatility_edge_case_single_observation():
    """Volatility with only 1 price observation has 0 returns, returning None."""
    single = pd.Series([100.0])
    assert calculate_volatility(single) is None


def test_volatility_edge_case_identical_flat_prices():
    """Flat prices produce zero return standard deviation, returning 0.0 (not None, not default)."""
    flat = pd.Series([150.0] * 25)
    vol = calculate_volatility(flat, window=20)
    assert vol == 0.0


def test_volatility_edge_case_missing_and_invalid_prices():
    """Invalid, zero, or negative prices are dropped and return None if < 2 returns remain."""
    invalid = pd.Series([100.0, np.nan, -50.0, 0.0])
    assert calculate_volatility(invalid) is None


def test_compute_all_indicators_missing_volatility_contract():
    """compute_all_indicators must return None for volatility when series has < 2 prices."""
    empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    res = compute_all_indicators(empty_df)
    assert res["volatility"] is None


def test_risk_officer_failsafe_on_missing_volatility():
    """
    RiskOfficer must fail-safe when volatility is None:
    - sizing_cap_pct must be exactly 0.0
    - Position Sizing Cap metric must be '0.0%'
    - Volatility Assessment must state 'Gate Veto: Missing Volatility Data'
    - Must not crash with TypeError or fall back to an invented 15% default.
    """
    officer = RiskOfficer()
    res = asyncio.run(officer.analyze(
        symbol="RELIANCE",
        current_price=1209.0,
        equity=1000000.0,
        volatility=None,
        scenario_type="VOLATILITY_SURGE"
    ))

    assert res["sizing_cap_pct"] == 0.0
    assert res["value"] == "Gate Veto: Missing Volatility Data"
    assert "0% sizing cap" in res["summary"]
    assert "fail-safe veto" in res["summary"]
    assert res["var_95_pct"] is None
    assert res["cvar_99_pct"] is None


def test_gaussian_var_cvar_mathematical_precision():
    """
    Validate analytic Gaussian VaR and CVaR (Expected Shortfall).
    VaR_alpha = sigma * z_alpha
    CVaR_alpha = sigma * (phi(z_alpha) / (1 - alpha))
    For alpha=0.99:
      z_0.99 = 2.326347874
      phi(z_0.99) = 0.026652142
      multiplier = 2.6652142...
    Returns are scaled to percentages (e.g. 3.49 for 3.49%).
    """
    daily_vol = 0.015  # 1.5% daily volatility

    var_99, cvar_99 = calculate_gaussian_var_cvar(daily_vol, alpha=0.99)
    assert var_99 is not None and cvar_99 is not None
    # Expected: 0.015 * 2.326348 * 100 = 3.4895% -> 3.49%
    assert var_99 == 3.49
    # Expected: 0.015 * 2.665214 * 100 = 3.9978% -> 4.00%
    assert cvar_99 == 4.00
    # CVaR must strictly exceed VaR for any alpha in (0, 1)
    assert cvar_99 > var_99

    # Edge cases
    assert calculate_gaussian_var_cvar(None) == (None, None)
    assert calculate_gaussian_var_cvar(-0.05) == (None, None)
    assert calculate_gaussian_var_cvar(0.0) == (0.0, 0.0)


def test_volatility_extreme_regime_unclamped():
    """
    Verify that extreme annualized volatility values exceeding 1.0 (e.g. 1.25 = 125% annualized vol)
    are mathematically supported and NOT artificially clamped to 1.0 or 0.15.
    """
    # Create price series with extreme day-to-day jumps (e.g. 10-15% daily swings)
    prices = [100.0, 115.0, 95.0, 112.0, 88.0, 108.0, 85.0, 105.0, 80.0, 102.0,
              75.0, 98.0, 72.0, 95.0, 68.0, 90.0, 65.0, 88.0, 62.0, 85.0, 60.0]
    series = pd.Series(prices)
    vol = calculate_volatility(series, window=20)
    assert vol is not None
    # Verify extreme volatility exceeds 1.0 (100% annualized)
    assert vol > 1.0, f"Expected volatility > 1.0, got {vol}"
    assert np.isfinite(vol)

    # Risk officer evaluates extreme volatility correctly:
    # VaR and CVaR are computed without clamping or numerical overflow
    officer = RiskOfficer()
    res = asyncio.run(officer.analyze(
        symbol="RELIANCE",
        current_price=1200.0,
        equity=1000000.0,
        volatility=vol,
        scenario_type="VOLATILITY_SURGE"
    ))
    assert res["sizing_cap_pct"] <= 10.0
    assert res["var_95_pct"] is not None and res["var_95_pct"] > 5.0
    assert res["cvar_99_pct"] is not None and res["cvar_99_pct"] > res["var_95_pct"]
    assert res["stress_drawdown_pct"] > res["var_95_pct"]



@pytest.mark.local_market_data
def test_october_21_finalized_candle_parity():
    """
    Verify that finalized October 21, 2026 candle in RELIANCE.csv and SQLite
    matches the official post-close session figures (VWAP Close: 1209.00, Low: 1199.30, Vol: 17,600,854)
    and DOES NOT contain the in-progress midday snapshot (Close: 1211.50, Low: 1208.00, Vol: 12,568,947).
    """
    csv_path = os.path.join("backend", "data", "historical", "RELIANCE.csv")
    assert os.path.exists(csv_path)

    df = pd.read_csv(csv_path)
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    oct_21_row = df[df["Date"] == "2026-10-21"]

    assert not oct_21_row.empty, "October 21, 2026 row must exist in finalized historical dataset"
    row = oct_21_row.iloc[0]

    # Verify finalized post-close figures
    assert float(row["Close"]) == 1209.00, f"Expected finalized close 1209.00, got {row['Close']}"
    assert float(row["Low"]) == 1199.30, f"Expected finalized low 1199.30, got {row['Low']}"
    assert int(row["Volume"]) == 17600854, f"Expected finalized volume 17,600,854, got {row['Volume']}"

    # Verify SQLite database parity if historical mode is active
    from app.core.config import settings
    if getattr(settings, "MARKET_DATA_MODE", "LIVE_ONLY") != "LIVE_ONLY":
        db = SessionLocal()
        try:
            db_record = (
                db.query(Candle)
                .filter(Candle.symbol == "RELIANCE")
                .order_by(Candle.timestamp.desc())
                .first()
            )
            assert db_record is not None
            assert db_record.timestamp.strftime("%Y-%m-%d") == "2026-10-21"
            assert float(db_record.close) == 1209.00
            assert float(db_record.low) == 1199.30
            assert int(db_record.volume) == 17600854
        finally:
            db.close()


@pytest.mark.local_market_data
def test_midday_archive_snapshot_integrity():
    """
    Verify that the superseded midday in-progress snapshot is safely archived
    in backend/data/historical/archive_midday_snapshots/RELIANCE_midday_snapshot_20261021.csv
    and preserves the 1:05 PM IST midday continuous snapshot values for audit provenance.
    """
    archive_path = os.path.join(
        "backend", "data", "historical", "archive_midday_snapshots", "RELIANCE_midday_snapshot_20261021.csv"
    )
    assert os.path.exists(archive_path), "Midday snapshot archive must exist"

    df_arch = pd.read_csv(archive_path)
    df_arch["Date"] = pd.to_datetime(df_arch["Date"]).dt.strftime("%Y-%m-%d")
    oct_21_arch = df_arch[df_arch["Date"] == "2026-10-21"]

    assert not oct_21_arch.empty
    arch_row = oct_21_arch.iloc[0]

    # Archived file contains midday 12:44:53 UTC / 13:05 IST snapshot
    assert float(arch_row["Close"]) == 1211.50
    assert float(arch_row["Low"]) == 1208.00
    assert int(arch_row["Volume"]) == 12568947
