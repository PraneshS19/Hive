import json

from app.api.dependencies import get_db
from app.datasets.downloader import OptionalMarketDownloader
from app.datasets.importer import DatasetImporter
from app.db.models import Candle, Dataset
from app.schemas.datasets import (
    CSVImportRequest,
    CSVPreviewRequest,
    DatasetDetail,
    DatasetSummary,
    DownloadExecuteRequest,
    DownloadPreviewRequest,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

router = APIRouter()
MAX_CSV_BYTES = 10 * 1024 * 1024


def checked_csv_size(content: bytes) -> bytes:
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV input exceeds the 10 MiB processing limit.")
    if not content:
        raise HTTPException(400, "Supply a non-empty CSV.")
    return content


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(db: Session = Depends(get_db)):
    """List all registered historical datasets."""
    records = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
    return records


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """Retrieve detailed metadata and quality report for a dataset."""
    record = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")

    val_rep = None
    if record.validation_report_json:
        try:
            val_rep = json.loads(record.validation_report_json)
        except (TypeError, ValueError):
            val_rep = None

    return DatasetDetail(
        id=record.id,
        name=record.name,
        symbol=record.symbol,
        asset_name=record.asset_name,
        exchange=record.exchange,
        source=record.source,
        provenance=record.provenance,
        timeframe=record.timeframe,
        start_date=record.start_date,
        end_date=record.end_date,
        candle_count=record.candle_count,
        is_adjusted=record.is_adjusted,
        adjustment_status=record.adjustment_status,
        quality_status=record.quality_status,
        license_info=record.license_info,
        created_at=record.created_at,
        updated_at=record.updated_at,
        validation_report=val_rep,
    )


@router.get("/datasets/{dataset_id}/candles")
def get_dataset_candles(
    dataset_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    """Retrieve candles for a registered dataset."""
    record = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")

    candles = (
        db.query(Candle)
        .filter(Candle.dataset_id == dataset_id)
        .order_by(Candle.timestamp.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "dataset_id": dataset_id,
        "symbol": record.symbol,
        "count": len(candles),
        "total": record.candle_count,
        "candles": [
            {
                "timestamp": c.timestamp.isoformat(),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    }


@router.post("/datasets/preview-csv")
def preview_csv(payload: CSVPreviewRequest):
    """
    Dry-run validation preview from JSON payload with csv_text.
    """
    csv_bytes = checked_csv_size((payload.csv_text or "").encode("utf-8"))

    try:
        preview = DatasetImporter.preview_csv(
            csv_source=csv_bytes,
            symbol=payload.symbol,
            timeframe=payload.timeframe,
            custom_mapping=payload.custom_mapping,
        )
        return preview
    except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as e:
        raise HTTPException(status_code=400, detail=f"Preview failed: {e!s}")


@router.post("/datasets/preview-csv-file")
def preview_csv_file(
    file: UploadFile = File(...),
    symbol: str = Form("ASSET"),
    timeframe: str = Form("1d"),
):
    """
    Dry-run validation preview from multipart file upload.
    """
    csv_bytes = checked_csv_size(file.file.read(MAX_CSV_BYTES + 1))
    try:
        preview = DatasetImporter.preview_csv(
            csv_source=csv_bytes,
            symbol=symbol,
            timeframe=timeframe,
        )
        return preview
    except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as e:
        raise HTTPException(status_code=400, detail=f"File preview failed: {e!s}")


@router.post("/datasets/import-csv")
def import_csv(payload: CSVImportRequest, db: Session = Depends(get_db)):
    """
    Import historical CSV data into HIVE from JSON payload.
    """
    csv_bytes = checked_csv_size((payload.csv_text or "").encode("utf-8"))

    try:
        res = DatasetImporter.import_csv(
            db=db,
            csv_source=csv_bytes,
            dataset_name=payload.dataset_name,
            symbol=payload.symbol,
            asset_name=payload.asset_name,
            exchange=payload.exchange,
            source=payload.source,
            provenance=payload.provenance,
            timeframe=payload.timeframe,
            is_adjusted=payload.is_adjusted,
            adjustment_status=payload.adjustment_status,
            license_info=payload.license_info,
            custom_mapping=payload.custom_mapping,
        )
        return res
    except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as e:
        raise HTTPException(status_code=400, detail=f"Import failed: {e!s}")


@router.post("/datasets/import-csv-file")
def import_csv_file(
    file: UploadFile = File(...),
    symbol: str = Form("ASSET"),
    dataset_name: str | None = Form(None),
    asset_name: str | None = Form(None),
    exchange: str = Form("NSE"),
    source: str = Form("LOCAL_CSV"),
    timeframe: str = Form("1d"),
    license_info: str = Form("Public educational / personal research use only"),
    db: Session = Depends(get_db)
):
    """
    Import historical CSV data into HIVE from multipart file upload.
    """
    csv_bytes = checked_csv_size(file.file.read(MAX_CSV_BYTES + 1))
    try:
        prov = f"Uploaded file: {file.filename}"
        res = DatasetImporter.import_csv(
            db=db,
            csv_source=csv_bytes,
            dataset_name=dataset_name,
            symbol=symbol,
            asset_name=asset_name,
            exchange=exchange,
            source=source,
            provenance=prov,
            timeframe=timeframe,
            license_info=license_info,
        )
        return res
    except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as e:
        raise HTTPException(status_code=400, detail=f"File import failed: {e!s}")


@router.post("/datasets/download/preview")
def preview_download(payload: DownloadPreviewRequest):
    """Preview scope for optional explicit download (Workflow B)."""
    return OptionalMarketDownloader.preview_download_scope(
        symbol=payload.symbol,
        period=payload.period,
        interval=payload.interval
    )


@router.post("/datasets/download")
def execute_download(payload: DownloadExecuteRequest, db: Session = Depends(get_db)):
    """Explicitly trigger historical download via yfinance (Workflow B)."""
    try:
        res = OptionalMarketDownloader.download_and_import(
            db=db,
            symbol=payload.symbol,
            period=payload.period,
            interval=payload.interval,
            dataset_name=payload.dataset_name,
            asset_name=payload.asset_name,
        )
        return res
    except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {e!s}")


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, db: Session = Depends(get_db)):
    """Delete an imported dataset and its candles."""
    record = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")

    deleted_candles = db.query(Candle).filter(Candle.dataset_id == dataset_id).delete()
    db.delete(record)
    db.commit()

    return {
        "success": True,
        "message": f"Dataset '{dataset_id}' and {deleted_candles} associated candles deleted.",
        "dataset_id": dataset_id
    }
