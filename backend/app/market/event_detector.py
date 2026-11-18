"""
HIVE — Deterministic Event Detection Service
Evaluates normalized market state using 100% deterministic rules.
Implements cooldowns, deduplication, and priority queuing to ensure the LLM
is only invoked on meaningful events rather than on every tick.
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import logger
from app.db.models import MarketEventRecord
from app.db.session import SessionLocal
from app.market.evidence_snapshot import evidence_snapshot_service


class DeterministicEventDetector:
    """
    Evaluates incoming price ticks against configurable, versioned thresholds.
    Zero LLM calls are involved in event detection.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self._cooldowns: dict[str, datetime] = {}  # symbol -> cooldown_until
        self._live_baselines: dict[str, float] = {}  # symbol -> live session baseline price
        self._recent_events: list[dict[str, Any]] = []

    def evaluate_tick(self, tick: dict[str, Any]) -> dict[str, Any] | None:
        """
        Evaluates a normalized market tick against deterministic triggers.
        In LIVE_ONLY mode: requires genuine positive price and establishes a live session baseline.
        Does not emit price-change events until subsequent valid live observations arrive.
        """
        symbol = tick.get("symbol", "").upper()
        if not symbol:
            return None

        price = tick.get("price")
        if price is None or price <= 0:
            return None

        now_utc = datetime.now(UTC)

        with self.lock:
            # Check per-instrument cooldown
            cooldown_expiry = self._cooldowns.get(symbol)
            if cooldown_expiry and now_utc < cooldown_expiry:
                return None

            # Check or establish live-session baseline
            baseline = self._live_baselines.get(symbol)
            if baseline is None or baseline <= 0:
                self._live_baselines[symbol] = price
                return None  # Baseline established; wait for next live observation

            change_pct = ((price - baseline) / baseline) * 100.0
            volume = tick.get("volume", 0)

            event_type = None
            headline = ""
            severity = 50
            trigger_val = None
            baseline_val = baseline
            thresh_val = None

            # Rule 1: Price Surge or Dump relative to live session baseline
            price_threshold = getattr(settings, "EVENT_PRICE_CHANGE_THRESHOLD_PCT", 1.5)
            if abs(change_pct) >= price_threshold:
                direction = "Surge" if change_pct > 0 else "Drop"
                event_type = "PRICE_SURGE"
                headline = f"{symbol} Intraday Price {direction} ({change_pct:+.2f}%) from live baseline (₹{baseline:,.2f})"
                severity = min(90, int(50 + abs(change_pct) * 10))
                trigger_val = change_pct
                thresh_val = price_threshold

            # Rule 2: Volume Anomaly
            elif volume and volume > 5000000:
                event_type = "VOLUME_SPIKE"
                headline = f"{symbol} Elevated Trading Volume ({volume:,} shares) observed on exchange"
                severity = 65
                trigger_val = float(volume)
                baseline_val = 1000000.0
                thresh_val = 5000000.0

            if not event_type:
                return None

            # Set cooldown for this instrument
            cooldown_duration = getattr(settings, "EVENT_COOLDOWN_SECONDS", 60.0)
            cooldown_until = now_utc + timedelta(seconds=cooldown_duration)
            self._cooldowns[symbol] = cooldown_until

            event_id = f"EVT_{now_utc.strftime('%Y%m%d_%H%M%S')}_{symbol}_{uuid.uuid4().hex[:6]}"

            event_data = {
                "event_id": event_id,
                "event_type": event_type,
                "symbol": symbol,
                "security_id": tick.get("security_id", ""),
                "severity": severity,
                "headline": headline,
                "trigger_value": trigger_val,
                "baseline_value": baseline_val,
                "threshold_value": thresh_val,
                "event_time": now_utc.isoformat(),
                "cooldown_until": cooldown_until.isoformat(),
                "status": "DETECTED"
            }

            self._recent_events.insert(0, event_data)
            if len(self._recent_events) > getattr(settings, "EVENT_MAX_PENDING", 50):
                self._recent_events.pop()

        # Persist event record to database
        try:
            with SessionLocal() as db:
                rec = MarketEventRecord(
                    event_id=event_id,
                    event_type=event_type,
                    symbol=symbol,
                    security_id=tick.get("security_id", ""),
                    severity=severity,
                    headline=headline,
                    trigger_value=trigger_val,
                    baseline_value=baseline_val,
                    threshold_value=thresh_val,
                    event_time=now_utc,
                    cooldown_until=cooldown_until,
                    status="DETECTED"
                )
                db.add(rec)
                db.commit()
        except SQLAlchemyError as e:
            logger.error(f"Failed to persist detected market event: {e}")

        # Automatically freeze evidence snapshot for this event
        try:
            snapshot = evidence_snapshot_service.freeze_snapshot(
                symbol=symbol,
                event_id=event_id,
                trigger_tick=tick
            )
            event_data["snapshot_id"] = snapshot.get("snapshot_id")
        except (TypeError, ValueError, OSError, RuntimeError, SQLAlchemyError) as snap_err:
            logger.error(f"Failed to freeze evidence snapshot for event {event_id}: {snap_err}")

        logger.info(f"Deterministic Event Triggered: [{event_type}] {headline} (ID: {event_id})")
        return event_data

    def trigger_user_analysis_event(self, symbol: str, reason: str = "User initiated on-demand analysis") -> dict[str, Any]:
        """Creates an explicit USER_TRIGGER market event for on-demand intelligence runs."""
        now_utc = datetime.now(UTC)
        event_id = f"EVT_USER_{now_utc.strftime('%Y%m%d_%H%M%S')}_{symbol.upper()}"
        event_data = {
            "event_id": event_id,
            "event_type": "USER_TRIGGER",
            "symbol": symbol.upper(),
            "severity": 40,
            "headline": f"{symbol.upper()} Analysis Triggered: {reason}",
            "trigger_value": 0.0,
            "baseline_value": 0.0,
            "threshold_value": 0.0,
            "event_time": now_utc.isoformat(),
            "status": "DETECTED"
        }

        try:
            with SessionLocal() as db:
                rec = MarketEventRecord(
                    event_id=event_id,
                    event_type="USER_TRIGGER",
                    symbol=symbol.upper(),
                    severity=40,
                    headline=event_data["headline"],
                    event_time=now_utc,
                    status="DETECTED"
                )
                db.add(rec)
                db.commit()
        except SQLAlchemyError as e:
            logger.error(f"Failed to persist user trigger event: {e}")

        # Freeze snapshot
        snapshot = evidence_snapshot_service.freeze_snapshot(
            symbol=symbol.upper(),
            event_id=event_id
        )
        event_data["snapshot_id"] = snapshot.get("snapshot_id")

        with self.lock:
            self._recent_events.insert(0, event_data)
            if len(self._recent_events) > 50:
                self._recent_events.pop()

        return event_data

    def get_recent_events(self, limit: int = 30) -> list[dict[str, Any]]:
        """Retrieve the most recent detected market events."""
        with self.lock:
            return list(self._recent_events[:limit])


# Global singleton instance
event_detector = DeterministicEventDetector()
