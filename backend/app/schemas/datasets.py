from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    id: str
    name: str
    symbol: str
    asset_name: str | None = None
    exchange: str
    source: str
    provenance: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    candle_count: int
    checksum_sha256: str | None = None
    is_adjusted: bool
    adjustment_status: str
    quality_status: str
    license_info: str
    created_at: datetime
    updated_at: datetime


class DatasetDetail(DatasetSummary):
    validation_report: dict[str, Any] | None = None


class CSVPreviewRequest(BaseModel):
    csv_text: str | None = None
    symbol: str = Field(default="ASSET")
    timeframe: str = Field(default="1d")
    custom_mapping: dict[str, str] | None = None


class CSVImportRequest(BaseModel):
    csv_text: str
    symbol: str = Field(default="ASSET")
    dataset_name: str | None = None
    asset_name: str | None = None
    exchange: str = Field(default="NSE")
    source: str = Field(default="LOCAL_CSV")
    provenance: str = Field(default="Manual CSV import")
    timeframe: str = Field(default="1d")
    is_adjusted: bool = False
    adjustment_status: str = Field(default="UNADJUSTED")
    license_info: str = Field(default="Public educational / personal research use only")
    custom_mapping: dict[str, str] | None = None


class DownloadPreviewRequest(BaseModel):
    symbol: str = Field(default="RELIANCE")
    period: str = Field(default="1y")
    interval: str = Field(default="1d")


class DownloadExecuteRequest(BaseModel):
    symbol: str = Field(default="RELIANCE")
    period: str = Field(default="1y")
    interval: str = Field(default="1d")
    dataset_name: str | None = None
    asset_name: str | None = None
