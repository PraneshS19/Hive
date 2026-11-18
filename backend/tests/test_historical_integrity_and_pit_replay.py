from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from app.backtesting.engine import backtest_engine, round_currency
from app.db.models import Account, Base, Candle, Dataset
from app.market.dhan_adapter import IST_OFFSET
from app.market.evidence_verifier import EvidenceVerificationService
from app.providers.historical import HistoricalMarketDataProvider
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    acc = Account(id=1, starting_cash=1000000.0, cash_balance=1000000.0, currency="INR")
    session.add(acc)
    session.commit()

    yield session
    session.close()


# =============================================================================
# 1. Non-Trading Date Candle & Holiday Invariance Tests
# =============================================================================

def test_non_trading_session_artifact_classification():
    """
    Verify HistoricalMarketDataProvider.is_non_trading_session_artifact accurately
    identifies flat zero-volume holiday/weekend carry-forward rows without
    flagging real trading candles or benchmark index series.
    """
    # 1. Holiday carry-forward row: Jan 15, 2026 (Maharashtra Election Holiday)
    holiday_dt = datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC)
    is_artifact = HistoricalMarketDataProvider.is_non_trading_session_artifact(
        candle_timestamp=holiday_dt,
        open_p=1250.0,
        high_p=1250.0,
        low_p=1250.0,
        close_p=1250.0,
        volume=0.0,
        symbol="RELIANCE"
    )
    assert is_artifact is True

    # 2. Legitimate trading day with low volume (open != close)
    normal_dt = datetime(2026, 1, 14, 0, 0, 0, tzinfo=UTC)
    is_artifact_trade = HistoricalMarketDataProvider.is_non_trading_session_artifact(
        candle_timestamp=normal_dt,
        open_p=1240.0,
        high_p=1255.0,
        low_p=1238.0,
        close_p=1250.0,
        volume=1000.0,
        symbol="RELIANCE"
    )
    assert is_artifact_trade is False

    # 3. Benchmark index series (e.g. NIFTY 50) on normal day with 0 volume but non-flat prices
    is_artifact_index = HistoricalMarketDataProvider.is_non_trading_session_artifact(
        candle_timestamp=normal_dt,
        open_p=24000.0,
        high_p=24150.0,
        low_p=23950.0,
        close_p=24100.0,
        volume=0.0,
        symbol="NIFTY50"
    )
    assert is_artifact_index is False


def test_zero_volume_holiday_injection_invariance(test_db):
    """
    Regression test: injecting a flat zero-volume holiday carry-forward candle
    (e.g. Jan 15, 2026) does NOT alter research dataset filtering, SMA, RSI,
    or backtest signals/metrics when excluded as non-trading artifact.
    """
    symbol = "TEST_INVAR"
    ds_id = "ds_test_invariance"

    ds = Dataset(
        id=ds_id,
        name="Test Invariance Dataset",
        symbol=symbol,
        exchange="NSE",
        source="TEST_ARCHIVE",
        provenance="Verified exchange daily archive",
        timeframe="1d",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 2, 1, tzinfo=UTC),
        candle_count=20
    )
    test_db.add(ds)

    # Insert 20 legitimate trading days in Jan 2026 (skipping Jan 15 holiday)
    trading_dates = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 7, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 8, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 9, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 12, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 13, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 14, 0, 0, 0, tzinfo=UTC),
        # Jan 15 is HOLIDAY
        datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 19, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 21, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 22, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 23, 0, 0, 0, tzinfo=UTC),
        # Jan 26 is Republic Day holiday
        datetime(2026, 1, 27, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 28, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 29, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 30, 0, 0, 0, tzinfo=UTC),
    ]

    base_price = 1000.0
    for i, t in enumerate(trading_dates):
        c = Candle(
            dataset_id=ds_id,
            symbol=symbol,
            timestamp=t,
            open=base_price + i * 5,
            high=base_price + i * 5 + 10,
            low=base_price + i * 5 - 5,
            close=base_price + i * 5 + 2,
            volume=50000 + i * 1000,
            is_synthetic=False
        )
        test_db.add(c)
    test_db.commit()

    provider = HistoricalMarketDataProvider()
    clean_df = provider.get_candles(test_db, symbol=symbol, min_bars=10, exclude_non_trading_artifacts=True)
    assert len(clean_df) == 20

    # Run backtest on baseline clean data
    res_baseline = backtest_engine.run_backtest(
        custom_df=clean_df,
        strategy="SMA crossover",
        symbol=symbol,
        starting_capital=1000000.0
    )

    # Now INJECT a flat zero-volume carry-forward row on Jan 15, 2026 holiday
    holiday_candle = Candle(
        dataset_id=ds_id,
        symbol=symbol,
        timestamp=datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC),
        open=base_price + 9 * 5 + 2,   # Jan 14 close carry-forward
        high=base_price + 9 * 5 + 2,
        low=base_price + 9 * 5 + 2,
        close=base_price + 9 * 5 + 2,
        volume=0.0,
        is_synthetic=False
    )
    test_db.add(holiday_candle)
    test_db.commit()

    # Raw DB count increases to 21 (raw data fidelity preserved)
    raw_count = test_db.query(Candle).filter(Candle.symbol == symbol).count()
    assert raw_count == 21

    # Filtered research data excludes the artifact and remains 20 rows
    filtered_df = provider.get_candles(test_db, symbol=symbol, min_bars=10, exclude_non_trading_artifacts=True)
    assert len(filtered_df) == 20

    # Backtest results are 100% IDENTICAL
    res_injected = backtest_engine.run_backtest(
        custom_df=filtered_df,
        strategy="SMA crossover",
        symbol=symbol,
        starting_capital=1000000.0
    )

    assert res_injected["total_return_pct"] == res_baseline["total_return_pct"]
    assert res_injected["final_equity"] == res_baseline["final_equity"]
    assert len(res_injected["trades"]) == len(res_baseline["trades"])


# =============================================================================
# 2. Point-in-Time Replay Availability Semantics Tests
# =============================================================================

def test_pit_replay_availability_cutoffs(test_db):
    """
    Verify explicit information-availability rule:
    NSE EOD Bhavcopy and official settlement are disseminated at 16:30 IST (11:00 UTC).
    Test cutoffs:
    - Before session end (11:00 IST) -> excludes current session
    - At session close (15:30 IST) -> excludes current session (Bhavcopy pending)
    - Before EOD publication (16:00 IST) -> excludes current session (Bhavcopy pending)
    - After EOD publication (18:30 IST) -> includes current session
    - Weekend / holiday -> includes previous session EOD
    - Pre-dataset cutoff -> returns FAILED_NO_DATA
    """
    symbol = "RELIANCE"
    ds_id = "ds_rel_test"

    # Insert 3 trading sessions:
    # Day 1: 2026-10-16 (Friday)
    # Day 2: 2026-10-19 (Monday) - note Oct 20 is Dussehra holiday
    # Day 3: 2026-10-21 (Wednesday)
    sessions = [
        (datetime(2026, 10, 16, 0, 0, 0, tzinfo=UTC), 1211.2),
        (datetime(2026, 10, 19, 0, 0, 0, tzinfo=UTC), 1202.0),
        (datetime(2026, 10, 21, 0, 0, 0, tzinfo=UTC), 1209.0),
    ]

    for dt, close_p in sessions:
        c = Candle(
            dataset_id=ds_id,
            symbol=symbol,
            timestamp=dt,
            open=close_p - 2.0,
            high=close_p + 5.0,
            low=close_p - 4.0,
            close=close_p,
            volume=15000000,
            is_synthetic=False
        )
        test_db.add(c)
    test_db.commit()

    # Cutoff 1: Pre-dataset cutoff -> FAILED_NO_DATA
    pre_cutoff = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    rep_pre = EvidenceVerificationService.point_in_time_evidence_replay(symbol, pre_cutoff, test_db)
    assert rep_pre["status"] == "FAILED_NO_DATA"
    assert rep_pre["bars_available"] == 0

    # Cutoff 2: 2026-10-21 11:00:00 IST (Intraday morning before close)
    # Oct 21 EOD Bhavcopy is not available until 16:30 IST.
    cutoff_11am_ist = datetime(2026, 10, 21, 11, 0, 0, tzinfo=IST_OFFSET)
    rep_11am = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_11am_ist, test_db)
    assert rep_11am.get("status") != "FAILED_NO_DATA"
    assert "2026-10-19" in rep_11am["latest_observed_bar"]["timestamp"]
    assert rep_11am["latest_observed_bar"]["close"] == 1202.0

    # Cutoff 3: 2026-10-21 15:30:00 IST (Market close bell)
    # Bhavcopy calculation is still ongoing and not released until 16:30 IST.
    cutoff_1530_ist = datetime(2026, 10, 21, 15, 30, 0, tzinfo=IST_OFFSET)
    rep_1530 = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_1530_ist, test_db)
    assert "2026-10-19" in rep_1530["latest_observed_bar"]["timestamp"]
    assert rep_1530["latest_observed_bar"]["close"] == 1202.0

    # Cutoff 4: 2026-10-21 16:00:00 IST (30 mins before Bhavcopy publication)
    cutoff_1600_ist = datetime(2026, 10, 21, 16, 0, 0, tzinfo=IST_OFFSET)
    rep_1600 = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_1600_ist, test_db)
    assert "2026-10-19" in rep_1600["latest_observed_bar"]["timestamp"]
    assert rep_1600["latest_observed_bar"]["close"] == 1202.0

    # Cutoff 5: 2026-10-21 16:29:59 IST (1 second BEFORE configured availability threshold)
    cutoff_162959_ist = datetime(2026, 10, 21, 16, 29, 59, tzinfo=IST_OFFSET)
    rep_162959 = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_162959_ist, test_db)
    assert "2026-10-19" in rep_162959["latest_observed_bar"]["timestamp"]
    assert rep_162959["latest_observed_bar"]["close"] == 1202.0

    # Cutoff 6: 2026-10-21 16:30:00 IST (EXACTLY AT configured availability threshold)
    cutoff_163000_ist = datetime(2026, 10, 21, 16, 30, 0, tzinfo=IST_OFFSET)
    rep_163000 = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_163000_ist, test_db)
    assert "2026-10-21" in rep_163000["latest_observed_bar"]["timestamp"]
    assert rep_163000["latest_observed_bar"]["close"] == 1209.0

    # Cutoff 7: 2026-10-21 18:30:00 IST (2 hours after EOD Bhavcopy publication at 16:30 IST)
    cutoff_1830_ist = datetime(2026, 10, 21, 18, 30, 0, tzinfo=IST_OFFSET)
    rep_1830 = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_1830_ist, test_db)
    assert "2026-10-21" in rep_1830["latest_observed_bar"]["timestamp"]
    assert rep_1830["latest_observed_bar"]["close"] == 1209.0

    # Cutoff 8: 2026-10-25 12:00:00 IST (Weekend Sunday)
    cutoff_weekend = datetime(2026, 10, 25, 12, 0, 0, tzinfo=IST_OFFSET)
    rep_weekend = EvidenceVerificationService.point_in_time_evidence_replay(symbol, cutoff_weekend, test_db)
    assert "2026-10-21" in rep_weekend["latest_observed_bar"]["timestamp"]
    assert rep_weekend["latest_observed_bar"]["close"] == 1209.0

    # Verify qualified availability policy metadata
    assert rep_163000["availability_policy_metadata"]["availability_policy"] == "CONSERVATIVE_SIMULATION_ASSUMPTION_1630_IST"
    assert rep_163000["availability_policy_metadata"]["availability_policy_version"] == "v1.0"
    assert rep_163000["availability_policy_metadata"]["recorded_timestamp_present"] is False
    assert rep_163000["information_availability_status"]["price_data"] == "ASSUMED_POINT_IN_TIME"

    # Verify disclosure of unverified macro & news sources
    assert rep_1830["information_availability_status"]["macro_data"] == "UNVERIFIABLE_INSUFFICIENT_PROVENANCE"
    assert rep_1830["information_availability_status"]["news_filings"] == "UNVERIFIABLE_INSUFFICIENT_PROVENANCE"
    assert "UNVERIFIABLE_OMITTED" in rep_1830["leakage_prevention_breakdown"]["macro_leakage_prevented"]
    assert "UNVERIFIABLE_OMITTED" in rep_1830["leakage_prevention_breakdown"]["news_filings_leakage_prevented"]

    # Verify safe handling of corrupt / missing timestamps without crashing
    with pytest.raises(ValueError):
        EvidenceVerificationService.get_bar_session_date(None)
    with pytest.raises(ValueError):
        EvidenceVerificationService.get_bar_session_date("NOT_A_VALID_DATE")


# =============================================================================
# 3. Fill Accounting Reproducibility & Traceability Tests
# =============================================================================

def test_trade_accounting_trace_and_equity_reconciliation():
    """
    Verify that every trade produced by backtest_engine carries an accounting_trace
    specifying raw vs full precision vs displayed execution prices, notionals,
    fees, cash debits/credits, net PnL, and half-up rounding at currency boundary.
    Prove that sum of net trade PnLs exactly equals final equity delta.
    """
    # Create deterministic oscillating series to trigger buys and sells
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    prices = [100.0 + 15.0 * np.sin(i / 3.0) for i in range(n)]
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices,
        "high": [p + 2.0 for p in prices],
        "low": [p - 2.0 for p in prices],
        "close": prices,
        "volume": [100000.0] * n
    })

    starting_capital = 1000000.0
    res = backtest_engine.run_backtest(
        custom_df=df,
        strategy="SMA crossover",
        symbol="TEST_ACCT",
        starting_capital=starting_capital,
        slippage_pct=0.05,
        commission_pct=0.10
    )

    trades = res["trades"]
    assert len(trades) > 0

    running_realized_pnl = 0.0
    for t in trades:
        trace = t.get("accounting_trace")
        assert trace is not None, f"Trade {t['id']} missing accounting_trace!"

        # Required fields in accounting trace
        assert "raw_entry_price" in trace
        assert "raw_exit_price" in trace
        assert "full_precision_entry_price" in trace
        assert "full_precision_exit_price" in trace
        assert "displayed_entry_price" in trace
        assert "displayed_exit_price" in trace
        assert "quantity" in trace
        assert "entry_notional" in trace
        assert "entry_fee" in trace
        assert "total_cash_debit" in trace
        assert "exit_notional" in trace
        assert "exit_fee" in trace
        assert "total_cash_credit" in trace
        assert "net_realized_pnl" in trace
        assert "rounding_policy" in trace

        # Invariant checks per trade
        assert trace["total_cash_debit"] == round(trace["entry_notional"] + trace["entry_fee"], 2)
        assert trace["total_cash_credit"] == round(trace["exit_notional"] - trace["exit_fee"], 2)
        calc_pnl = round(trace["total_cash_credit"] - trace["total_cash_debit"], 2)
        assert trace["net_realized_pnl"] == calc_pnl
        assert t["pnl"] == calc_pnl

        running_realized_pnl += calc_pnl

    # Final equity reconciliation:
    # All positions liquidated by backtest conclusion
    final_equity = res["final_equity"]
    expected_equity = round(starting_capital + running_realized_pnl, 2)
    assert abs(final_equity - expected_equity) < 0.01


# =============================================================================
# 4. Terminal Position Liquidation Rule Tests
# =============================================================================

def test_terminal_position_liquidation_rule():
    """
    Verify TERMINAL_DATASET_CLOSE_LIQUIDATION:
    1. Triggers ONLY when backtest concludes with an active open position.
    2. Liquidates at terminal bar close with slippage and commission applied.
    3. Lookahead-free: does not access any data beyond terminal bar.
    4. When backtest ends flat, TERMINAL_DATASET_CLOSE_LIQUIDATION does not trigger.
    """
    # Monotonically rising series: Buy and Hold enters at bar 0 Open and holds until end
    n = 20
    dates = pd.date_range("2026-01-01", periods=n, freq="D")
    df_rising = pd.DataFrame({
        "timestamp": dates,
        "open": [100.0 + i * 2.0 for i in range(n)],
        "high": [105.0 + i * 2.0 for i in range(n)],
        "low": [98.0 + i * 2.0 for i in range(n)],
        "close": [102.0 + i * 2.0 for i in range(n)],
        "volume": [100000.0] * n
    })

    res = backtest_engine.run_backtest(
        custom_df=df_rising,
        strategy="Buy and hold",
        symbol="TEST_TERM",
        starting_capital=1000000.0,
        slippage_pct=0.05,
        commission_pct=0.10
    )

    trades = res["trades"]
    assert len(trades) == 1
    term_trade = trades[0]

    # Verify exit reason and timing
    assert term_trade["exit_reason"] == "TERMINAL_DATASET_CLOSE_LIQUIDATION"
    assert term_trade["exit_time"] == str(dates[-1])[:10]
    assert term_trade["accounting_trace"] is not None
    assert term_trade["accounting_trace"]["raw_exit_price"] == df_rising["close"].iloc[-1]

    # Verify lookahead freedom: terminal exit price equals terminal bar close * (1 - slippage)
    expected_exit_exec = df_rising["close"].iloc[-1] * (1.0 - 0.0005)
    assert term_trade["accounting_trace"]["full_precision_exit_price"] == expected_exit_exec


# =============================================================================
# 5. Production Backtest Studio Filtering & Execution Path Tests
# =============================================================================

def test_production_backtest_path_applies_filtering_and_persists_metadata(test_db):
    """
    Verify production backtest path (run_backtest with db session):
    1. Applies exclude_non_trading_artifacts=True during candle retrieval.
    2. Correctly excludes non-trading holiday artifacts from research observations.
    3. Records observation_count, raw_candle_count, non_trading_artifacts_excluded_count,
       date_range, and dataset_checksum.
    4. Handles terminal position liquidation cleanly when dataset ends with open position.
    """
    symbol = "TEST_PROD_PATH"
    ds_id = "ds_test_prod_path"

    ds = Dataset(
        id=ds_id,
        name="Production Path Test Dataset",
        symbol=symbol,
        exchange="NSE",
        source="NSE_HISTORICAL_ARCHIVE",
        provenance="Verified exchange daily archive",
        timeframe="1d",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 1, 30, tzinfo=UTC),
        candle_count=20,
        checksum_sha256="abcd1234ef5678sha256checksum"
    )
    test_db.add(ds)

    # Insert 20 legitimate trading days + 1 flat zero-volume holiday candle on Jan 15, 2026
    dates = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 5, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 6, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 7, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 8, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 9, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 12, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 13, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 14, 0, 0, 0, tzinfo=UTC),
        # Jan 15 holiday artifact
        datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 16, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 19, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 21, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 22, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 23, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 27, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 28, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 29, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 30, 0, 0, 0, tzinfo=UTC),
    ]

    for d in dates:
        if d.day == 15:
            c = Candle(
                dataset_id=ds_id,
                symbol=symbol,
                timestamp=d,
                open=1050.0,
                high=1050.0,
                low=1050.0,
                close=1050.0,
                volume=0.0,
                is_synthetic=False
            )
        else:
            c = Candle(
                dataset_id=ds_id,
                symbol=symbol,
                timestamp=d,
                open=1000.0 + d.day * 2.0,
                high=1005.0 + d.day * 2.0,
                low=995.0 + d.day * 2.0,
                close=1002.0 + d.day * 2.0,
                volume=50000.0,
                is_synthetic=False
            )
        test_db.add(c)
    test_db.commit()

    # Execute backtest via production path (db=test_db, dataset_id=ds_id)
    res = backtest_engine.run_backtest(
        db=test_db,
        symbol=symbol,
        dataset_id=ds_id,
        strategy="Buy and hold",
        starting_capital=1000000.0
    )

    # Invariants verification
    assert res["raw_candle_count"] == 21
    assert res["observation_count"] == 20
    assert res["non_trading_artifacts_excluded_count"] == 1
    assert res["dataset_checksum"] == "abcd1234ef5678sha256checksum"
    assert "20 valid research candles" in res["notes"]
    assert "1 holiday/weekend carry-forward artifacts excluded" in res["notes"]

    # Terminal trade liquidation
    trades = res["trades"]
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "TERMINAL_DATASET_CLOSE_LIQUIDATION"
    assert trades[0]["accounting_trace"] is not None


# =============================================================================
# 6. Priority 1 & 2 Forensic Regression Tests
# =============================================================================

@pytest.mark.local_market_data
def test_persisted_cash_flow_reconciliation_invariants(test_db):
    """
    Priority 1 Regression Test:
    Independently verifies from the actual persisted accounting traces:
    1. Every trade's cash debit equals round(entry_notional + entry_fee, 2).
    2. Every trade's cash credit equals round(exit_notional - exit_fee, 2).
    3. Each net realized PnL equals round(cash credit - cash debit, 2).
    4. Aggregate debits and credits match exact sum of individual trades.
    5. Sum of net realized PnLs equals final equity delta.
    6. Ledger values and backtest summary agree to the exact paisa (INR 0.000000 discrepancy).
    """
    import os

    from app.datasets.importer import DatasetImporter
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historical")
    csv_path = os.path.join(data_dir, "RELIANCE.csv")
    with open(csv_path, "r", encoding="utf-8") as f:
        csv_text = f.read()

    DatasetImporter.import_csv(
        db=test_db,
        csv_source=csv_text,
        dataset_id="ds_reliance_daily",
        dataset_name="RELIANCE Daily",
        symbol="RELIANCE",
        asset_name="Reliance Industries Ltd",
        exchange="NSE",
        source="NSE_HISTORICAL_ARCHIVE",
        provenance="Verified exchange daily archive",
        timeframe="1d",
        is_adjusted=False,
        adjustment_status="UNADJUSTED",
    )

    res = backtest_engine.run_backtest(
        db=test_db,
        symbol="RELIANCE",
        dataset_id="ds_reliance_daily",
        strategy="SMA crossover",
        starting_capital=1000000.0,
        commission_pct=0.1,
        slippage_pct=0.05
    )

    trades = res["trades"]
    assert len(trades) == 11

    running_debits = 0.0
    running_credits = 0.0
    running_fees = 0.0
    running_pnl = 0.0

    for t in trades:
        trace = t["accounting_trace"]
        assert trace is not None

        # Verify invariant 1 & 2: transaction boundary rounding
        calc_debit = round(trace["entry_notional"] + trace["entry_fee"], 2)
        calc_credit = round(trace["exit_notional"] - trace["exit_fee"], 2)
        assert trace["total_cash_debit"] == calc_debit
        assert trace["total_cash_credit"] == calc_credit

        # Verify invariant 3: PnL formula
        calc_pnl = round(calc_credit - calc_debit, 2)
        assert trace["net_realized_pnl"] == calc_pnl
        assert t["pnl"] == calc_pnl

        running_debits += trace["total_cash_debit"]
        running_credits += trace["total_cash_credit"]
        running_fees += (trace["entry_fee"] + trace["exit_fee"])
        running_pnl += trace["net_realized_pnl"]

    # Verify invariant 4 & 5: exact aggregates
    assert round(running_debits, 2) == 1092377.12
    assert round(running_credits, 2) == 1086931.07
    assert round(running_fees, 2) == 2179.30
    assert round(running_pnl, 2) == -5446.05

    # Verify invariant 6: final equity reconciliation
    expected_final_equity = round(res["starting_capital"] + running_pnl, 2)
    assert res["final_equity"] == expected_final_equity
    assert res["final_equity"] == 994553.95
    assert abs(res["final_equity"] - expected_final_equity) < 0.000001


def test_icicibank_coverage_and_date_alignment(test_db):
    """
    Priority 2 Regression Test:
    Verifies that:
    1. HistoricalMarketDataProvider.align_series_by_session_date aligns datasets with
       unequal lengths (e.g. 245 bars vs 246 bars) strictly on valid calendar dates (IST).
    2. Excludes non-overlapping dates without fabricating values or shifting indices.
    3. Prevents lookahead or mismatched date comparisons.
    """
    dates_bench = pd.date_range("2025-10-21", periods=246, freq="D")
    dates_target = pd.date_range("2025-10-23", periods=245, freq="D")

    df_target = pd.DataFrame({
        "timestamp": dates_target,
        "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 10000.0
    })
    df_bench = pd.DataFrame({
        "timestamp": dates_bench,
        "open": 200.0, "high": 205.0, "low": 195.0, "close": 200.0, "volume": 20000.0
    })

    aligned_target, aligned_bench = HistoricalMarketDataProvider.align_series_by_session_date(
        df_target, df_bench
    )

    assert len(aligned_target) == len(aligned_bench)
    assert len(aligned_target) == 244
    assert list(aligned_target["session_date"]) == list(aligned_bench["session_date"])
    assert "2025-10-21" not in list(aligned_target["session_date"])
    assert "2025-10-21" not in list(aligned_bench["session_date"])


@pytest.mark.local_market_data
def test_dataset_specific_observation_counts_and_multi_instrument_alignment():
    """
    Priority 2 & 3 Regression Test:
    Verifies that:
    1. Dataset-specific observation counts are reported correctly:
       - Five single-stock / benchmark datasets (RELIANCE, TCS, INFY, HDFCBANK, NIFTY50):
         contain exactly 246 valid research bars (Oct 21, 2025 to Oct 21, 2026).
       - ICICI Bank (ds_icicibank_yf_1y_1d):
         contains exactly 245 valid research bars (Oct 23, 2025 to Oct 21, 2026).
    2. Multi-instrument alignment (inner intersection on session dates):
       - Exactly 245 common session dates when aligning ICICIBANK with any of the other five.
       - The single non-overlapping date is '2025-10-21'.
       - No synthetic rows, interpolation, or forward-filling are fabricated.
    """
    import os
    db_path = os.getenv("HIVE_VERIFICATION_DB") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "hive.db")
    if not os.path.exists(db_path):
        pytest.skip("HIVE verification database not found; set HIVE_VERIFICATION_DB")

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    db = Session()
    provider = HistoricalMarketDataProvider()

    expected_valid_counts = {
        "ds_reliance_daily": 246,
        "ds_tcs_daily": 246,
        "ds_infy_daily": 246,
        "ds_hdfcbank_daily": 246,
        "ds_nifty50_daily": 246,
        "ds_icicibank_yf_1y_1d": 245,
    }

    try:
        valid_dfs = {}
        for ds_id, expected_valid in expected_valid_counts.items():
            valid_df = provider.get_candles(db, dataset_id=ds_id, exclude_non_trading_artifacts=True)
            assert len(valid_df) == expected_valid, (
                f"Dataset {ds_id} expected {expected_valid} valid research bars, got {len(valid_df)}"
            )
            valid_dfs[ds_id] = valid_df

        df_icici = valid_dfs["ds_icicibank_yf_1y_1d"]
        for ref_id in ["ds_reliance_daily", "ds_tcs_daily", "ds_infy_daily", "ds_hdfcbank_daily", "ds_nifty50_daily"]:
            df_ref = valid_dfs[ref_id]
            al_icici, al_ref = provider.align_series_by_session_date(df_icici, df_ref)

            assert len(al_icici) == 245, f"Expected 245 aligned bars for ICICIBANK with {ref_id}, got {len(al_icici)}"
            assert len(al_ref) == 245, f"Expected 245 aligned bars for {ref_id} with ICICIBANK, got {len(al_ref)}"
            assert list(al_icici["session_date"]) == list(al_ref["session_date"]), (
                f"Aligned session dates between {ref_id} and ICICIBANK must match exactly 1-to-1"
            )
            assert "2025-10-21" not in list(al_icici["session_date"])
            assert "2025-10-21" not in list(al_ref["session_date"])
            assert al_icici["session_date"].is_monotonic_increasing
            assert al_ref["session_date"].is_monotonic_increasing
    finally:
        db.close()


@pytest.mark.local_market_data
def test_exact_static_source_file_sha256_matches_sqlite_registry():
    """
    Priority 1 Deterministic Verification Test:
    Independently reads the raw byte-level content of every static historical dataset CSV
    in backend/data/historical/ and asserts:
    1. The byte-level SHA-256 digest matches Dataset.checksum_sha256 in the active SQLite DB 100%.
    2. Zero discrepancy between source files and database records.
    3. Confirms that ICICIBANK has checksum_sha256 = None (dynamic yfinance fetch with no static CSV file).
    """
    import hashlib
    import os
    db_path = os.getenv("HIVE_VERIFICATION_DB") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "hive.db")
    if not os.path.exists(db_path):
        pytest.skip("HIVE verification database not found; set HIVE_VERIFICATION_DB")

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    db = Session()

    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historical")

    static_mapping = {
        "ds_reliance_daily": ("RELIANCE.csv", "e818f43d3b7422114de9b0a2d705df383f12ed5c5b4dcb0c38cb952c445e4c6b"),
        "ds_tcs_daily": ("TCS.csv", "a7097a63b98f50b518d1f7ba6b36d0e0f8e2b954005e1139cd00cc660a79ac95"),
        "ds_infy_daily": ("INFY.csv", "aae76f65d92224097efbc98e6951d22b830ed25bc41ab95d6e91001de9ebb6d0"),
        "ds_hdfcbank_daily": ("HDFCBANK.csv", "30c09205b32f08d96e3d338ddbe0acefe62c89c8ed5a11708a9323797c5f4f35"),
        "ds_nifty50_daily": ("NIFTY50.csv", "5157f26276875b5cb272a5c979a12ef319e2e6f868355a389c1782ce5f5cb11f"),
    }

    try:
        for ds_id, (filename, expected_sha) in static_mapping.items():
            fpath = os.path.join(data_dir, filename)
            assert os.path.exists(fpath), f"Source CSV file missing: {fpath}"
            with open(fpath, "rb") as f:
                content = f.read()
            computed_sha = hashlib.sha256(content).hexdigest()

            assert computed_sha == expected_sha, (
                f"Disk file bytes for {filename} do not match canonical expected digest: "
                f"{computed_sha} vs {expected_sha}"
            )

            dataset = db.query(Dataset).filter(Dataset.id == ds_id).first()
            assert dataset is not None, f"Dataset record missing for {ds_id}"
            assert dataset.checksum_sha256 == computed_sha, (
                f"Checksum mismatch for {ds_id} ({filename}): "
                f"file={computed_sha} vs db={dataset.checksum_sha256}"
            )

        # Verify ICICIBANK dynamic provenance (source checksum is null / None)
        icici_ds = db.query(Dataset).filter(Dataset.id == "ds_icicibank_yf_1y_1d").first()
        assert icici_ds is not None
        assert icici_ds.checksum_sha256 is None, (
            "ICICIBANK source-file checksum must be None because no static CSV source file exists"
        )
        assert icici_ds.candle_count == 246
    finally:
        db.close()


@pytest.mark.local_market_data
def test_dynamic_dataset_canonical_content_digests_dual_spec():
    """
    Priority 2 Deterministic Verification Test:
    Confirms the ICICI Bank dynamic dataset content digest specifications separately:
    1. Spec A (v1.0-raw-sqlite): e3785f84d5b7aac8b38a1541ac3fa4b9fccf41ee5ed4839685bea5b3479c4eb7
       Derived from raw SQLite cursor text representation with microsecond precision (.000000)
       and 4-decimal price formatting.
    2. Spec B (v1.0-orm-model): 960d6505a716fa96d07bdb3657c964935c5e79e3b79b87a431af6b2faf8c92b4
       Derived from SQLAlchemy ORM Candle model entities with standard datetime and default float formatting.
    3. Confirms that both specifications operate over the exact same 246 database rows.
    4. Confirms neither digest represents a physical file checksum or database file hash.
    """
    import hashlib
    import os
    import sqlite3
    db_path = os.getenv("HIVE_VERIFICATION_DB") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "hive.db")
    if not os.path.exists(db_path):
        pytest.skip("HIVE verification database not found; set HIVE_VERIFICATION_DB")

    # 1. Spec A verification via raw SQLite cursor
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT timestamp, open, high, low, close, volume FROM candles "
            "WHERE dataset_id = 'ds_icicibank_yf_1y_1d' ORDER BY timestamp ASC"
        )
        raw_rows = cur.fetchall()
        assert len(raw_rows) == 246, f"Expected 246 rows in raw cursor, got {len(raw_rows)}"

        # Verify raw microsecond timestamp formatting in raw SQLite
        assert ".000000" in str(raw_rows[0][0]), "Raw SQLite timestamp must retain microsecond precision"

        spec_a_str = "".join([
            f"{r[0]}|{r[1]:.4f}|{r[2]:.4f}|{r[3]:.4f}|{r[4]:.4f}|{r[5]}"
            for r in raw_rows
        ]).encode("utf-8")
        spec_a_digest = hashlib.sha256(spec_a_str).hexdigest()
        assert spec_a_digest == "e3785f84d5b7aac8b38a1541ac3fa4b9fccf41ee5ed4839685bea5b3479c4eb7", (
            f"Spec A digest mismatch: {spec_a_digest}"
        )
    finally:
        conn.close()

    # 2. Spec B verification via SQLAlchemy ORM Candle model
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        candles = db.query(Candle).filter(
            Candle.dataset_id == "ds_icicibank_yf_1y_1d"
        ).order_by(Candle.timestamp.asc()).all()
        assert len(candles) == 246, f"Expected 246 ORM candles, got {len(candles)}"

        spec_b_str = "".join([
            f"{c.timestamp}|{c.open}|{c.high}|{c.low}|{c.close}|{c.volume}"
            for c in candles
        ]).encode("utf-8")
        spec_b_digest = hashlib.sha256(spec_b_str).hexdigest()
        assert spec_b_digest == "960d6505a716fa96d07bdb3657c964935c5e79e3b79b87a431af6b2faf8c92b4", (
            f"Spec B digest mismatch: {spec_b_digest}"
        )

        # Confirm source-file checksum remains null
        ds = db.query(Dataset).filter(Dataset.id == "ds_icicibank_yf_1y_1d").first()
        assert ds.checksum_sha256 is None
    finally:
        db.close()


@pytest.mark.local_market_data
def test_currency_rounding_half_up_boundary_invariants():
    """
    Priority 2 Verification Test:
    Verify that financial currency calculations enforce deterministic ROUND_HALF_UP policy:
    1. Positive half-paisa boundaries (0.005 -> 0.01, 0.015 -> 0.02, 0.025 -> 0.03, etc.)
       where Python's built-in round() rounds towards even (round(0.005, 2) == 0.0, round(0.025, 2) == 0.02).
    2. Negative half-paisa boundaries (-0.005 -> -0.01, -0.015 -> -0.02, -0.025 -> -0.03, etc.).
    3. Standard non-boundary fractions (0.004 -> 0.00, 0.006 -> 0.01, -0.004 -> 0.00, -0.006 -> -0.01).
    4. Deterministic reconciliation of the 11-trade backtest ledger on RELIANCE dataset:
       Asserts cash debit sum, cash credit sum, realized P&L sum, and final equity reconcile
       to exactly INR 0.000000 difference.
    """
    # 1. Positive half-paisa boundary invariants
    assert round_currency(0.005) == 0.01
    assert round_currency(0.015) == 0.02
    assert round_currency(0.025) == 0.03
    assert round_currency(0.035) == 0.04
    assert round_currency(0.045) == 0.05
    assert round_currency(0.125) == 0.13
    assert round_currency(100.005) == 100.01
    assert round_currency(1234.565) == 1234.57

    # 2. Negative half-paisa boundary invariants
    assert round_currency(-0.005) == -0.01
    assert round_currency(-0.015) == -0.02
    assert round_currency(-0.025) == -0.03
    assert round_currency(-0.035) == -0.04
    assert round_currency(-0.045) == -0.05
    assert round_currency(-0.125) == -0.13
    assert round_currency(-100.005) == -100.01
    assert round_currency(-1234.565) == -1234.57

    # 3. Standard non-boundary invariants
    assert round_currency(0.004) == 0.00
    assert round_currency(0.006) == 0.01
    assert round_currency(-0.004) == 0.00
    assert round_currency(-0.006) == -0.01
    assert round_currency(100.1234) == 100.12
    assert round_currency(100.1278) == 100.13
    assert round_currency(-100.1234) == -100.12
    assert round_currency(-100.1278) == -100.13

    # 4. End-to-end 11-trade ledger reconciliation from active database
    import os

    from app.db.models import BacktestRun
    db_path = os.getenv("HIVE_VERIFICATION_DB") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "hive.db")
    if not os.path.exists(db_path):
        pytest.skip("HIVE verification database not found; set HIVE_VERIFICATION_DB")

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == "BT_a715f2dc6a").first()
        assert run is not None, "Persisted backtest run BT_a715f2dc6a missing"
        trades = run.trades_json
        if isinstance(trades, str):
            import json
            trades = json.loads(trades)
        assert len(trades) == 11

        total_debits = 0.0
        total_credits = 0.0
        total_pnl = 0.0

        for t in trades:
            trace = t["accounting_trace"]
            # Verify individual trade debit/credit/pnl relationships
            debit = trace["total_cash_debit"]
            credit = trace["total_cash_credit"]
            net_pnl = trace["net_realized_pnl"]
            assert round_currency(credit - debit) == round_currency(net_pnl)
            assert round_currency(net_pnl) == round_currency(t["pnl"])

            total_debits = round_currency(total_debits + debit)
            total_credits = round_currency(total_credits + credit)
            total_pnl = round_currency(total_pnl + net_pnl)

        assert total_debits == 1092377.12
        assert total_credits == 1086931.07
        assert total_pnl == -5446.05
        assert round_currency(total_credits - total_debits) == -5446.05

        starting_capital = run.starting_capital
        expected_final_equity = round_currency(starting_capital + total_pnl)
        assert expected_final_equity == 994553.95
        assert run.final_equity == 994553.95

        # Re-run live backtest calculation to assert engine outputs match exactly under ROUND_HALF_UP
        engine_res = backtest_engine.run_backtest(
            symbol="RELIANCE",
            strategy="SMA crossover",
            timeframe="1d",
            db=db,
            starting_capital=1000000.0,
            commission_pct=0.1,
            slippage_pct=0.05
        )
        assert engine_res["trade_count"] == 11
        assert engine_res["final_equity"] == 994553.95
        engine_debits = sum(t["accounting_trace"]["total_cash_debit"] for t in engine_res["trades"])
        engine_credits = sum(t["accounting_trace"]["total_cash_credit"] for t in engine_res["trades"])
        engine_pnl = sum(t["pnl"] for t in engine_res["trades"])
        assert round_currency(engine_debits) == 1092377.12
        assert round_currency(engine_credits) == 1086931.07
        assert round_currency(engine_pnl) == -5446.05
        assert round_currency(engine_credits - engine_debits) == -5446.05
    finally:
        db.close()
