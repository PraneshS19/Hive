import os
import sys

sys.path.insert(0, os.path.abspath("backend"))

from app.datasets.importer import DatasetImporter
from app.db.init_db import HISTORICAL_DATA_DIR, REAL_ASSETS
from app.db.models import Candle, Quote
from app.db.session import SessionLocal

print("=== Re-importing Finalized Historical Datasets into SQLite ===")
db = SessionLocal()

for item in REAL_ASSETS:
    csv_path = os.path.join(HISTORICAL_DATA_DIR, item["csv_file"])
    with open(csv_path, "r", encoding="utf-8") as f:
        csv_text = f.read()

    res = DatasetImporter.import_csv(
        db=db,
        csv_source=csv_text,
        dataset_id=item["dataset_id"],
        dataset_name=item["dataset_name"],
        symbol=item["symbol"],
        asset_name=item["name"],
        exchange=item["exchange"],
        source=item["source"],
        provenance=item["provenance"],
        timeframe="1d",
        is_adjusted=False,
        adjustment_status="UNADJUSTED"
    )
    print(f"Imported {item['symbol']}: {res['candle_count']} candles, range: {res['start_date']} to {res['end_date']}")

# Reconcile Quotes table with final close
for item in REAL_ASSETS:
    last_candle = db.query(Candle).filter(Candle.symbol == item["symbol"]).order_by(Candle.timestamp.desc()).first()
    prev_candle = db.query(Candle).filter(Candle.symbol == item["symbol"]).order_by(Candle.timestamp.desc()).offset(1).first()
    q = db.query(Quote).filter(Quote.symbol == item["symbol"]).first()
    if q and last_candle and prev_candle:
        q.price = last_candle.close
        q.previous = prev_candle.close
        q.change = round(last_candle.close - prev_candle.close, 2)
        q.change_pct = round((q.change / prev_candle.close) * 100.0, 2)
        q.volume = last_candle.volume
        db.commit()
        print(f"Updated Quote {item['symbol']}: Price={q.price}, Prev={q.previous}, Change%={q.change_pct}%")

db.close()
print("\n[OK] All 5 finalized historical datasets re-imported and reconciled.")
