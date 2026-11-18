import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from app.core.logging import logger
from app.datasets.validator import DatasetValidator, ValidationReport
from app.db.models import Asset, Candle, Dataset
from sqlalchemy.orm import Session


class DatasetImporter:
    """
    Manages CSV imports, validation, batch SQLite persistence, and dataset registry.
    """

    @classmethod
    def preview_csv(
        cls,
        csv_source: str | bytes | io.StringIO | io.BytesIO,
        symbol: str = "ASSET",
        timeframe: str = "1d",
        custom_mapping: dict[str, str] | None = None,
        max_preview_rows: int = 10
    ) -> dict[str, Any]:
        """
        Dry-run validation preview without writing to database.
        """
        if isinstance(csv_source, bytes):
            csv_source = io.BytesIO(csv_source)
        elif isinstance(csv_source, str) and "\n" in csv_source:
            csv_source = io.StringIO(csv_source)

        df = pd.read_csv(csv_source)
        report = DatasetValidator.validate_and_clean(
            df=df,
            custom_mapping=custom_mapping,
            symbol=symbol,
            timeframe=timeframe
        )

        preview_candles = []
        if report.clean_df is not None and not report.clean_df.empty:
            head_df = report.clean_df.head(max_preview_rows)
            for _, r in head_df.iterrows():
                preview_candles.append({
                    "timestamp": r["timestamp"].isoformat(),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                })

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "validation_report": report.to_dict(),
            "preview_candles": preview_candles,
            "column_mapping_resolved": DatasetValidator.resolve_columns(df, custom_mapping)
        }

    @classmethod
    def import_csv(
        cls,
        db: Session,
        csv_source: str | bytes | io.StringIO | io.BytesIO,
        dataset_id: str | None = None,
        dataset_name: str | None = None,
        symbol: str = "ASSET",
        asset_name: str | None = None,
        exchange: str = "NSE",
        source: str = "LOCAL_CSV",
        provenance: str = "Manual CSV import",
        timeframe: str = "1d",
        is_adjusted: bool = False,
        adjustment_status: str = "UNADJUSTED",
        license_info: str = "Public educational / personal research use only",
        custom_mapping: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Validates CSV and persists dataset and candles to SQLite.
        """
        import hashlib
        raw_bytes = None
        if isinstance(csv_source, bytes):
            raw_bytes = csv_source
            file_obj = io.BytesIO(csv_source)
        elif isinstance(csv_source, str) and "\n" in csv_source:
            raw_bytes = csv_source.encode("utf-8")
            file_obj = io.StringIO(csv_source)
        elif hasattr(csv_source, "read"):
            pos = csv_source.tell() if hasattr(csv_source, "tell") else 0
            content = csv_source.read()
            raw_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
            if hasattr(csv_source, "seek"):
                csv_source.seek(pos)
            file_obj = csv_source
        else:
            file_obj = csv_source

        checksum_sha256 = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes else None

        # 1. Read CSV with pandas (chunking safeguard for massive files)
        try:
            df = pd.read_csv(file_obj)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError, ValueError) as e:
            raise ValueError(f"Could not parse CSV file: {e!s}")

        # 2. Strict validation and invariant checks
        symbol_upper = symbol.strip().upper()
        report: ValidationReport = DatasetValidator.validate_and_clean(
            df=df,
            custom_mapping=custom_mapping,
            symbol=symbol_upper,
            timeframe=timeframe
        )

        if report.status == "REJECTED" or report.clean_df is None or report.clean_df.empty:
            raise ValueError(f"CSV import failed validation: {'; '.join(report.warnings or ['No valid records'])}")

        # 3. Determine Dataset ID & Name
        if not dataset_id:
            safe_source = source.lower().replace(" ", "_")
            dataset_id = f"ds_{symbol_upper.lower()}_{safe_source}_{uuid.uuid4().hex[:6]}"

        if not dataset_name:
            dataset_name = f"{symbol_upper} Historical {timeframe.upper()} ({source})"

        if not asset_name:
            asset_name = f"{symbol_upper} Equity"

        # 4. Ensure Asset exists in database
        asset = db.query(Asset).filter(Asset.symbol == symbol_upper).first()
        if not asset:
            asset = Asset(
                symbol=symbol_upper,
                name=asset_name,
                sector="Indian Equities" if exchange == "NSE" else "General Equities",
                currency="INR" if exchange == "NSE" else "USD",
                is_active=True,
            )
            db.add(asset)
            db.flush()

        # 5. Remove existing candles for this dataset_id to prevent duplicates on re-import
        db.query(Candle).filter(Candle.dataset_id == dataset_id).delete()

        # 6. Insert new candles in batch chunks of 1000
        clean_df = report.clean_df
        batch_size = 1000
        candles_to_insert = []
        for _, row in clean_df.iterrows():
            candles_to_insert.append(Candle(
                symbol=symbol_upper,
                timestamp=row["timestamp"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                is_synthetic=False,
                dataset_id=dataset_id,
            ))

            if len(candles_to_insert) >= batch_size:
                db.bulk_save_objects(candles_to_insert)
                candles_to_insert = []

        if candles_to_insert:
            db.bulk_save_objects(candles_to_insert)

        # 7. Upsert Dataset metadata in registry
        existing_ds = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if existing_ds:
            existing_ds.name = dataset_name
            existing_ds.symbol = symbol_upper
            existing_ds.asset_name = asset_name
            existing_ds.exchange = exchange
            existing_ds.source = source
            existing_ds.provenance = provenance
            existing_ds.checksum_sha256 = checksum_sha256
            existing_ds.timeframe = timeframe
            existing_ds.start_date = report.start_date
            existing_ds.end_date = report.end_date
            existing_ds.candle_count = report.accepted_rows
            existing_ds.is_adjusted = is_adjusted
            existing_ds.adjustment_status = adjustment_status
            existing_ds.quality_status = report.status
            existing_ds.validation_report_json = json.dumps(report.to_dict())
            existing_ds.license_info = license_info
            existing_ds.updated_at = datetime.now(UTC)
        else:
            new_ds = Dataset(
                id=dataset_id,
                name=dataset_name,
                symbol=symbol_upper,
                asset_name=asset_name,
                exchange=exchange,
                source=source,
                provenance=provenance,
                checksum_sha256=checksum_sha256,
                timeframe=timeframe,
                start_date=report.start_date,
                end_date=report.end_date,
                candle_count=report.accepted_rows,
                is_adjusted=is_adjusted,
                adjustment_status=adjustment_status,
                quality_status=report.status,
                validation_report_json=json.dumps(report.to_dict()),
                license_info=license_info,
            )
            db.add(new_ds)

        db.commit()
        logger.info(f"Successfully imported dataset '{dataset_id}' with {report.accepted_rows} candles.")

        return {
            "dataset_id": dataset_id,
            "name": dataset_name,
            "symbol": symbol_upper,
            "asset_name": asset_name,
            "exchange": exchange,
            "source": source,
            "checksum_sha256": checksum_sha256,
            "timeframe": timeframe,
            "candle_count": report.accepted_rows,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "quality_status": report.status,
            "adjustment_status": adjustment_status,
            "validation_report": report.to_dict()
        }
