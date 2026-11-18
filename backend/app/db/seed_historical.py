import hashlib
import os
from typing import Any

from app.core.logging import logger
from app.datasets.importer import DatasetImporter
from app.db.models import Candle, Dataset
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

HISTORICAL_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "historical"
)

PRESET_HISTORICAL_SYMBOLS = [
    {"symbol": "RELIANCE", "name": "Reliance Industries Limited", "exchange": "NSE"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited", "exchange": "NSE"},
    {"symbol": "INFY", "name": "Infosys Limited", "exchange": "NSE"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Limited", "exchange": "NSE"},
    {"symbol": "NIFTY50", "name": "NIFTY 50 Benchmark Index", "exchange": "NSE"},
]


def seed_verified_historical_datasets(db: Session) -> list[dict[str, Any]]:
    """
    Imports and registers verified historical OHLCV daily datasets from local disk
    into the HISTORICAL_RESEARCH dataset store for Backtest Studio.
    Strictly isolated: does not touch live quotes or live-tick tables.
    """
    results = []
    if not os.path.exists(HISTORICAL_DATA_DIR):
        logger.info("No local historical archive is installed.")
        return results

    for item in PRESET_HISTORICAL_SYMBOLS:
        sym = item["symbol"]
        csv_path = os.path.join(HISTORICAL_DATA_DIR, f"{sym}.csv")
        if not os.path.exists(csv_path):
            continue

        dataset_id = f"ds_{sym.lower()}_daily"
        existing = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        db.query(Candle).filter(Candle.dataset_id == dataset_id).count()
        if existing:
            if not existing.checksum_sha256 and os.path.exists(csv_path):
                with open(csv_path, "rb") as f:
                    existing.checksum_sha256 = hashlib.sha256(f.read()).hexdigest()
                db.commit()
            results.append({
                "dataset_id": existing.id,
                "symbol": existing.symbol,
                "candle_count": existing.candle_count,
                "status": "ALREADY_REGISTERED"
            })
            continue

        try:
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()

            file_hash = hashlib.sha256(csv_bytes).hexdigest()

            prov = (
                f"Verified Daily Historical Archive for NSE ({sym}, 2025-2026). "
                f"Source file: {sym}.csv | SHA256:{file_hash}"
            )

            res = DatasetImporter.import_csv(
                db=db,
                csv_source=csv_bytes,
                dataset_id=dataset_id,
                dataset_name=f"{sym} Daily (Verified Historical Archive)",
                symbol=sym,
                asset_name=item["name"],
                exchange=item["exchange"],
                source="NSE_HISTORICAL_ARCHIVE",
                provenance=prov,
                timeframe="1d",
                is_adjusted=False,
                adjustment_status="UNADJUSTED",
                license_info="Educational and personal quantitative research use only",
            )
            results.append(res)
            logger.info(f"Registered historical dataset '{dataset_id}' ({sym}) with {res['candle_count']} bars.")
        except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as e:
            logger.error(f"Failed to seed historical dataset for {sym}: {e}")

    return results


if __name__ == "__main__":
    from app.db.session import SessionLocal
    sess = SessionLocal()
    try:
        res = seed_verified_historical_datasets(sess)
        print("Seeding completed:", res)
    finally:
        sess.close()
