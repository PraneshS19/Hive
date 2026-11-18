"""
HIVE — DhanHQ Live Feed & Market State Endpoints
Provides real-time feed telemetry, broad watchlist quotes, detected events,
and safe configuration management.
"""

from typing import Any, Literal
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.security import require_operator
from app.market.dhan_adapter import dhan_live_feed
from app.market.event_detector import event_detector
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

router = APIRouter()


class DhanConfigUpdate(BaseModel):
    client_id: str | None = Field(default=None, max_length=128)
    access_token: str | None = Field(default=None, max_length=4096, repr=False)
    feed_enabled: bool | None = None
    staleness_threshold_seconds: float | None = Field(default=None, ge=1, le=3600)
    provider: Literal["0xramm_yahoo_rest", "ramm_stock_api", "dhanhq_live"] | None = None
    ram_base_url: str | None = None
    ram_poll_interval_seconds: float | None = Field(default=None, ge=1, le=3600)
    ram_feed_enabled: bool | None = None

    @field_validator("ram_base_url")
    @classmethod
    def validate_local_adapter_url(cls, value):
        if value is not None:
            url = urlsplit(value)
            if url.scheme not in ("http", "https") or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.username or url.password:
                raise ValueError("The adapter URL must use an HTTP loopback address without credentials.")
        return value


@router.get("/status")
def get_dhan_feed_status():
    """
    Returns truthful status of the active market-data feed.
    Never misrepresents historical or disconnected state as live.
    """
    return dhan_live_feed.get_status()


@router.post("/poll")
def trigger_market_feed_poll():
    """
    Triggers an immediate single-flight poll of the active provisional REST market-data adapter.
    """
    if hasattr(dhan_live_feed, "poll_now"):
        res = dhan_live_feed.poll_now()
        return res
    return {"status": "not_supported", "message": "Active feed does not support polling"}


@router.get("/candles/{symbol}")
def get_feed_candles(symbol: str, interval_minutes: int = Query(default=5, ge=1, le=60), limit: int = Query(default=30, ge=1, le=100)):
    """
    Retrieve polling-derived interval candles for a symbol, labeled as POLLING_DERIVED_APPROXIMATION.
    """
    if hasattr(dhan_live_feed, "get_aggregated_candles"):
        return dhan_live_feed.get_aggregated_candles(symbol, interval_minutes=interval_minutes, limit=limit)
    return []


@router.get("/watchlist")
def get_dhan_watchlist():
    """
    Returns quotes and status for the configured 30-instrument broad watchlist.
    Clearly marks whether quotes are LIVE from Dhan or HISTORICAL from database.
    """
    return dhan_live_feed.get_watchlist()


@router.get("/quote/{symbol}")
def get_dhan_quote(symbol: str):
    """
    Retrieve single instrument quote with full provenance.
    """
    q = dhan_live_feed.get_quote(symbol)
    if not q:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol}' not found in registry.")
    return q


@router.get("/events")
def list_detected_events(limit: int = Query(default=30, ge=1, le=100)):
    """
    Retrieve the most recent market events detected via deterministic rules.
    """
    return event_detector.get_recent_events(limit=limit)


@router.post("/trigger-event")
def trigger_user_analysis_event(payload: dict[str, Any]):
    """
    Creates an explicit user-initiated market event to trigger the intelligence workflow.
    """
    symbol = str(payload.get("symbol", "RELIANCE")).upper()
    reason = str(payload.get("reason", "User requested on-demand analysis via HIVE interface"))
    return event_detector.trigger_user_analysis_event(symbol=symbol, reason=reason)


@router.post("/config", dependencies=[Depends(require_operator)])
def update_dhan_config(cfg: DhanConfigUpdate):
    """
    Update DhanHQ feed settings safely in backend configuration.
    """
    if not cfg.model_fields_set:
        raise HTTPException(422, "Provide at least one market feed setting.")
    dhan_live_feed.stop()
    if cfg.client_id is not None:
        settings.DHAN_CLIENT_ID = cfg.client_id.strip()
    if cfg.access_token is not None:
        settings.DHAN_ACCESS_TOKEN = cfg.access_token.strip()
    if cfg.feed_enabled is not None:
        settings.DHAN_FEED_ENABLED = cfg.feed_enabled
    if cfg.staleness_threshold_seconds is not None:
        settings.DHAN_STALENESS_THRESHOLD_SECONDS = cfg.staleness_threshold_seconds
    if cfg.provider is not None:
        settings.MARKET_DATA_PROVIDER = cfg.provider.strip()
    if cfg.ram_base_url is not None:
        settings.RAM_STOCK_API_BASE_URL = cfg.ram_base_url.strip()
    if cfg.ram_poll_interval_seconds is not None:
        settings.RAM_POLL_INTERVAL_SECONDS = cfg.ram_poll_interval_seconds
    if cfg.ram_feed_enabled is not None:
        settings.RAM_FEED_ENABLED = cfg.ram_feed_enabled

    dhan_live_feed.start()
    status_obj = dhan_live_feed.get_status()
    return {
        "success": True,
        "message": "Market feed settings applied for this backend session.",
        "provider": getattr(settings, "MARKET_DATA_PROVIDER", "ramm_stock_api"),
        "feed_enabled": status_obj.get("feed_enabled", False),
        "status": status_obj.get("status", "UNKNOWN")
    }
