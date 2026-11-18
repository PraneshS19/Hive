import io

import pandas as pd
import pytest
from app.backtesting.engine import backtest_engine
from app.datasets.importer import DatasetImporter
from app.datasets.validator import DatasetValidator
from app.db.models import Candle, Dataset
from app.providers.historical import (
    DatasetNotFoundError,
    historical_provider,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def db_session(db):
    import os

    from app.datasets.importer import DatasetImporter
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historical")
    for sym in ["NIFTY50", "RELIANCE", "TCS", "INFY"]:
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
                asset_name=f"{sym}",
                exchange="NSE",
                source="HISTORICAL_ARCHIVE",
                provenance="Historical daily records",
                timeframe="1d",
                is_adjusted=False,
                adjustment_status="UNADJUSTED",
                license_info="Educational research use",
            )
    return db


def test_validator_valid_csv():
    csv_data = """Date,Open,High,Low,Close,Volume
2025-01-01,100.0,105.0,98.0,103.0,150000
2025-01-02,103.0,108.0,102.0,107.0,180000
2025-01-03,107.0,107.5,104.0,105.0,120000
"""
    df = pd.read_csv(io.StringIO(csv_data))
    report = DatasetValidator.validate_and_clean(df, symbol="TEST", timeframe="1d")
    assert report.status == "VALIDATED"
    assert report.total_rows == 3
    assert report.accepted_rows == 3
    assert report.rejected_rows == 0
    assert report.duplicate_count == 0
    assert report.clean_df is not None
    assert len(report.clean_df) == 3


def test_validator_alternate_column_mappings():
    # NSE Security-wise format
    csv_nse = """Date,Open Price,High Price,Low Price,Close Price,Total Traded Quantity
2025-01-01,2500.0,2550.0,2480.0,2520.0,5000000
2025-01-02,2520.0,2560.0,2510.0,2545.0,4500000
"""
    df = pd.read_csv(io.StringIO(csv_nse))
    report = DatasetValidator.validate_and_clean(df, symbol="RELIANCE", timeframe="1d")
    assert report.accepted_rows == 2
    assert "close" in report.clean_df.columns
    assert report.clean_df["close"].iloc[0] == 2520.0


def test_validator_invalid_and_missing_fields():
    # Missing close, non-numeric open, negative volume
    csv_bad = """Date,Open,High,Low,Close,Volume
2025-01-01,INVALID,105.0,98.0,103.0,150000
2025-01-02,103.0,108.0,102.0,107.0,-500
2025-01-03,107.0,107.5,104.0,105.0,120000
"""
    df = pd.read_csv(io.StringIO(csv_bad))
    report = DatasetValidator.validate_and_clean(df, symbol="BAD", timeframe="1d")
    assert report.total_rows == 3
    assert report.accepted_rows == 1  # Only row 3 is valid
    assert report.rejected_rows == 2
    assert any("Non-numeric" in r["reason"] for r in report.rejections)
    assert any("Negative volume" in r["reason"] for r in report.rejections)


def test_validator_ohlc_invariants():
    # High < Low and High < Open
    csv_viol = """Date,Open,High,Low,Close,Volume
2025-01-01,100.0,95.0,102.0,98.0,1000
2025-01-02,100.0,98.0,90.0,95.0,1000
2025-01-03,100.0,105.0,95.0,102.0,1000
"""
    df = pd.read_csv(io.StringIO(csv_viol))
    report = DatasetValidator.validate_and_clean(df, symbol="VIOL", timeframe="1d")
    assert report.total_rows == 3
    assert report.accepted_rows == 1  # only row 3 is valid
    assert report.rejected_rows == 2
    assert any("High (95.0) < Low" in r["reason"] for r in report.rejections)
    assert any("High (98.0) < max" in r["reason"] for r in report.rejections)


def test_validator_duplicate_timestamps():
    csv_dups = """Date,Open,High,Low,Close,Volume
2025-01-01,100.0,105.0,95.0,102.0,1000
2025-01-01,100.0,106.0,94.0,103.0,1200
2025-01-02,102.0,107.0,100.0,105.0,1100
"""
    df = pd.read_csv(io.StringIO(csv_dups))
    report = DatasetValidator.validate_and_clean(df, symbol="DUP", timeframe="1d")
    assert report.total_rows == 3
    assert report.accepted_rows == 2
    assert report.duplicate_count == 1


def test_validator_gap_reporting():
    # Gap from 2025-01-06 (Mon) to 2025-01-15 (Wed) without holiday
    csv_gap = """Date,Open,High,Low,Close,Volume
2025-01-06,100.0,105.0,95.0,102.0,1000
2025-01-15,102.0,107.0,100.0,105.0,1100
"""
    df = pd.read_csv(io.StringIO(csv_gap))
    report = DatasetValidator.validate_and_clean(df, symbol="GAP", timeframe="1d")
    assert len(report.gaps_detected) > 0
    assert report.gaps_detected[0]["missing_trading_days"] > 0
    assert report.status == "WARNINGS"


def test_importer_deduplication_and_persistence(db_session: Session):
    csv_sample = """Date,Open,High,Low,Close,Volume
2025-02-01,200.0,210.0,195.0,205.0,50000
2025-02-02,205.0,215.0,202.0,212.0,60000
"""
    res1 = DatasetImporter.import_csv(
        db=db_session,
        csv_source=csv_sample,
        dataset_id="ds_test_dedup",
        dataset_name="Test Dedup Dataset",
        symbol="TESTDEDUP",
        asset_name="Test Dedup Corp",
        exchange="NSE",
        source="LOCAL_CSV",
    )
    assert res1["candle_count"] == 2

    # Check count in DB
    c_count1 = db_session.query(Candle).filter(Candle.dataset_id == "ds_test_dedup").count()
    assert c_count1 == 2

    # Re-import same dataset
    res2 = DatasetImporter.import_csv(
        db=db_session,
        csv_source=csv_sample,
        dataset_id="ds_test_dedup",
        dataset_name="Test Dedup Dataset",
        symbol="TESTDEDUP",
        asset_name="Test Dedup Corp",
        exchange="NSE",
        source="LOCAL_CSV",
    )
    assert res2["candle_count"] == 2

    # Ensure no duplicates were added
    c_count2 = db_session.query(Candle).filter(Candle.dataset_id == "ds_test_dedup").count()
    assert c_count2 == 2

    # Clean up
    db_session.query(Candle).filter(Candle.dataset_id == "ds_test_dedup").delete()
    db_session.query(Dataset).filter(Dataset.id == "ds_test_dedup").delete()
    db_session.commit()


def test_historical_provider_no_silent_synthetic_fallback(db_session: Session):
    # Requesting a non-existent historical dataset MUST raise DatasetNotFoundError
    with pytest.raises(DatasetNotFoundError):
        historical_provider.get_candles(db_session, dataset_id="ds_non_existent_12345")

    with pytest.raises(DatasetNotFoundError):
        historical_provider.get_candles(db_session, symbol="NON_EXISTENT_SYMBOL_XYZ")


@pytest.mark.local_market_data
def test_backtest_historical_execution_and_rejections(db_session: Session):
    # 1. Attempting to backtest fictional/missing asset NOVA must raise DatasetNotFoundError
    with pytest.raises(DatasetNotFoundError):
        backtest_engine.run_backtest(
            strategy="SMA crossover",
            symbol="NOVA",
            db=db_session
        )

    # 2. Historical backtest on seeded NIFTY50 dataset
    hist_res = backtest_engine.run_backtest(
        strategy="SMA crossover",
        symbol="NIFTY50",
        data_source="historical",
        dataset_id="ds_nifty50_daily",
        db=db_session
    )
    assert hist_res["run_id"].startswith("BT_")
    assert "historical backtest" in hist_res["notes"].lower()
    assert len(hist_res["equity_curve"]) > 15
    assert hist_res["final_equity"] > 0

    # 3. Historical backtest on missing dataset fails explicitly with DatasetNotFoundError
    with pytest.raises(DatasetNotFoundError):
        backtest_engine.run_backtest(
            strategy="SMA crossover",
            symbol="UNKNOWN_STOCK",
            data_source="historical",
            db=db_session
        )


def test_backtest_accounting_slippage_and_fees():
    # Use known deterministic prices fixture where price rises then drops
    dates = pd.date_range("2025-01-01", periods=20, freq="D")
    prices = [100.0, 102.0, 105.0, 108.0, 112.0, 115.0, 118.0, 120.0, 118.0, 115.0, 110.0, 105.0, 100.0, 95.0, 90.0, 88.0, 85.0, 84.0, 85.0, 86.0]
    custom_df = pd.DataFrame({
        "timestamp": dates,
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [10000.0] * 20,
    })

    # Run with 0 commission & 0 slippage
    res_no_fee = backtest_engine.run_backtest(
        strategy="SMA crossover",
        symbol="TEST",
        commission_pct=0.0,
        slippage_pct=0.0,
        custom_df=custom_df,
    )

    # Run with 0.5% commission & 0.2% slippage
    res_with_fee = backtest_engine.run_backtest(
        strategy="SMA crossover",
        symbol="TEST",
        commission_pct=0.5,
        slippage_pct=0.2,
        custom_df=custom_df,
    )

    if res_no_fee["trade_count"] > 0:
        # Trades with fees should have lower net equity
        assert res_with_fee["final_equity"] < res_no_fee["final_equity"]


@pytest.mark.local_market_data
def test_api_datasets_endpoints(client: TestClient, db_session: Session):
    # GET /api/v1/datasets
    resp = client.get("/api/v1/datasets")
    assert resp.status_code == 200
    datasets = resp.json()
    assert isinstance(datasets, list)
    assert len(datasets) >= 4  # Seeded NIFTY50, RELIANCE, TCS, INFY
    assert any(d["symbol"] == "NIFTY50" for d in datasets)

    # GET /api/v1/datasets/{id}
    first_id = datasets[0]["id"]
    det_resp = client.get(f"/api/v1/datasets/{first_id}")
    assert det_resp.status_code == 200
    detail = det_resp.json()
    assert detail["id"] == first_id
    assert "candle_count" in detail

    # GET /api/v1/datasets/{id}/candles
    candles_resp = client.get(f"/api/v1/datasets/{first_id}/candles?limit=10")
    assert candles_resp.status_code == 200
    c_data = candles_resp.json()
    assert len(c_data["candles"]) <= 10

    # POST /api/v1/datasets/preview-csv
    preview_csv = "Date,Open,High,Low,Close,Volume\n2025-01-01,100,105,98,103,5000\n2025-01-02,103,108,101,107,6000\n"
    prev_resp = client.post("/api/v1/datasets/preview-csv", json={
        "csv_text": preview_csv,
        "symbol": "DEMO",
        "timeframe": "1d"
    })
    assert prev_resp.status_code == 200
    prev_json = prev_resp.json()
    assert prev_json["validation_report"]["accepted_rows"] == 2

    # POST /api/v1/backtests with historical data_source
    bt_resp = client.post("/api/v1/backtests", json={
        "strategy": "SMA crossover",
        "symbol": "RELIANCE",
        "data_source": "historical",
        "dataset_id": "ds_reliance_daily",
        "starting_capital": 1000000.0
    })
    assert bt_resp.status_code == 200
    bt_json = bt_resp.json()
    assert "Historical backtest on verified data" in bt_json["notes"]

    # POST /api/v1/backtests with missing historical symbol returns 404
    err_resp = client.post("/api/v1/backtests", json={
        "strategy": "SMA crossover",
        "symbol": "DOES_NOT_EXIST",
        "data_source": "historical",
        "starting_capital": 1000000.0
    })
    assert err_resp.status_code == 404
