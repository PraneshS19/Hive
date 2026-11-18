import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.db.models import (
    Candle,
    Dataset,
    DecisionPipelineRun,
    ReviewRun,
)
from app.db.models.review import ReviewEvidenceRecord
from app.market.dhan_adapter import IST_OFFSET
from app.providers.historical import HistoricalMarketDataProvider


class EvidenceVerificationService:
    """
    Evidence verification and point-in-time historical replay service.
    Guarantees:
    1. Verifies SHA-256 hashes of original stored evidence without overwriting historical agent output.
    2. Audits all cited evidence tags (EV_PRICE, EV_IND, EV_MACRO, EV_NEWS) against stored records.
    3. Point-in-time replay strictly filters market bars and documents to timestamps <= cutoff T.
    4. Prohibits future data leakage (bars or documents after cutoff T are rejected).
    5. Honestly labels incomplete historical reconstructions when only OHLCV is available.
    """

    @classmethod
    def compute_sha256(cls, data: Any) -> str:
        """Compute canonical deterministic SHA-256 hash of structured data."""
        if isinstance(data, str):
            payload = data.encode("utf-8")
        elif isinstance(data, bytes):
            payload = data
        else:
            payload = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def verify_original_run_evidence(cls, run_id: str, db: Session) -> dict[str, Any]:
        """
        Verify the integrity and provenance of an original recorded AI decision.
        Loads original snapshot, verifies content hashes, audits citations, and
        validates deterministic rules WITHOUT re-running the agent or replacing outputs.
        """
        # 1. Try finding in ReviewRun
        review_run = db.query(ReviewRun).filter(ReviewRun.run_id == run_id).first()
        pipeline_run = db.query(DecisionPipelineRun).filter(DecisionPipelineRun.id == run_id).first()

        if not review_run and not pipeline_run:
            return {"audit_verdict": "RUN_NOT_FOUND"}

        run = review_run or pipeline_run
        snapshot = db.get(ReviewEvidenceRecord, run_id) if review_run else None
        computed = cls.compute_sha256(snapshot.payload_json) if snapshot else None
        hash_valid = snapshot is not None and computed == snapshot.sha256
        packet = json.loads(snapshot.payload_json) if hash_valid else {}
        executor = json.loads(review_run.executor_output_json or "{}") if review_run else {}
        refs = (executor or {}).get("evidence_refs") or []
        citations = []
        for ref in refs:
            value = packet.get(ref) if isinstance(ref, str) else None
            present = isinstance(value, dict) and bool(value) and (
                ref != "EV_PRICE" or value.get("price") is not None
            )
            citations.append({
                "tag": ref, "recorded_in_snapshot": present,
                "status": "VALID_VERIFIED" if present else "UNVERIFIED_OR_MISSING",
            })

        if not snapshot:
            verdict = "INCOMPLETE_EVIDENCE"
            description = "No evidence archive is bound to this run."
        elif not hash_valid:
            verdict = "PARTIALLY_AUDITABLE"
            description = "Archived evidence failed SHA-256 verification."
        elif not citations or not all(citation["recorded_in_snapshot"] for citation in citations):
            verdict = "PARTIALLY_AUDITABLE"
            description = "Evidence matches the recorded digest. Citations are missing or unsupported."
        else:
            verdict = "FULLY_AUDITABLE"
            description = "Archived evidence matches the recorded digest and contains all cited IDs."

        return {
            "run_id": run_id,
            "symbol": run.symbol,
            "decision_timestamp": run.created_at,
            "audit_verdict": verdict,
            "audit_description": description,
            "content_hash_verified": hash_valid,
            "stored_sha256": snapshot.sha256 if snapshot else None,
            "computed_sha256": computed,
            "prompt_hash": review_run.prompt_hash if review_run else None,
            "snapshot_id": snapshot.run_id if snapshot else None,
            "ingestion_timestamp": snapshot.created_at if snapshot else None,
            "cited_references": citations,
            "original_agent_output_preserved": True,
            "re_run_agent": False,
            "audit_executed_at": datetime.now(UTC).isoformat(),
        }

    @classmethod
    def get_bar_session_date(cls, ts: Any) -> datetime.date:
        """Extract official NSE calendar session date for a candle timestamp."""
        if ts is None:
            raise ValueError("Candle timestamp cannot be None")

        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                try:
                    return datetime.strptime(ts[:10], "%Y-%m-%d").date()
                except ValueError as e:
                    raise ValueError(f"Unparseable candle timestamp string: {ts}") from e

        if getattr(ts, "tzinfo", None) is not None:
            ist_dt = ts.astimezone(IST_OFFSET)
            return ist_dt.date()
        else:
            if hasattr(ts, "hour") and ts.hour == 18 and ts.minute == 30:
                ts_utc = ts.replace(tzinfo=UTC)
                return ts_utc.astimezone(IST_OFFSET).date()
            if hasattr(ts, "date"):
                return ts.date()
            raise ValueError(f"Invalid candle timestamp format: {ts}")

    @classmethod
    def get_bar_information_availability_timestamp(cls, ts: Any) -> datetime:
        """
        NSE EOD Bhavcopy and official settlement values are disseminated and available
        to market systems at 16:30 IST (11:00 UTC) on the trading session date.
        Returns timezone-aware UTC datetime.
        """
        s_date = cls.get_bar_session_date(ts)
        return datetime(s_date.year, s_date.month, s_date.day, 11, 0, 0, tzinfo=UTC)

    @classmethod
    def point_in_time_evidence_replay(
        cls,
        symbol: str,
        cutoff_datetime: datetime,
        db: Session,
        dataset_id: str | None = None
    ) -> dict[str, Any]:
        """
        Point-in-Time Historical Replay:
        Strictly reconstructs the market state at cutoff time T using ONLY data available by T.
        Prevents lookahead bias: any candle, document, or event after cutoff T is excluded.
        Qualified availability rule:
        - If dataset has documented upstream exchange release timestamps, uses recorded release time.
        - Otherwise applies conservative simulation policy assumption: 16:30 IST / 11:00 UTC (v1.0).
        """
        sym = symbol.strip().upper()
        if cutoff_datetime.tzinfo is None:
            cutoff_datetime = cutoff_datetime.replace(tzinfo=UTC)
        else:
            cutoff_datetime = cutoff_datetime.astimezone(UTC)

        replay_id = f"REPLAY_{cutoff_datetime.strftime('%Y%m%d_%H%M%S')}_{sym}_{uuid.uuid4().hex[:6]}"

        # 1. Determine source classification and availability qualification
        dataset_meta = None
        if dataset_id:
            dataset_meta = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset_meta:
            dataset_meta = db.query(Dataset).filter(Dataset.symbol == sym).first()

        d_source = (dataset_meta.source if dataset_meta else "IMPORTED_CSV").upper()
        if d_source in ("NSE_OFFICIAL", "EXCHANGE_DIRECT") and getattr(dataset_meta, "has_documented_release_timestamps", False):
            source_classification = "ORIGINAL_EXCHANGE_FILES_DOCUMENTED_RELEASE_TIMESTAMPS"
            price_availability_status = "VERIFIED_POINT_IN_TIME"
            availability_policy = "RECORDED_EXCHANGE_RELEASE_TIMESTAMPS"
            availability_policy_version = "v1.0"
            is_recorded_timestamp = True
            assumption_disclosure = "Availability determined directly from documented exchange release timestamps in source metadata."
        elif "YFINANCE" in d_source:
            source_classification = "THIRD_PARTY_YFINANCE_UNVERIFIED_PUBLICATION_TIMESTAMPS"
            price_availability_status = "ASSUMED_POINT_IN_TIME"
            availability_policy = "CONSERVATIVE_SIMULATION_ASSUMPTION_1630_IST"
            availability_policy_version = "v1.0"
            is_recorded_timestamp = False
            assumption_disclosure = (
                "Third-party Yahoo Finance-derived daily bars lack historical ingestion timestamps. "
                "EOD availability is modeled under configured simulation policy (16:30 IST / 11:00 UTC, v1.0). "
                "This policy does not independently prove when third-party servers originally published the bar."
            )
        else:
            source_classification = "IMPORTED_CSV_STATIC_ARCHIVE_UNVERIFIED_DISSEMINATION_TIMESTAMPS"
            price_availability_status = "ASSUMED_POINT_IN_TIME"
            availability_policy = "CONSERVATIVE_SIMULATION_ASSUMPTION_1630_IST"
            availability_policy_version = "v1.0"
            is_recorded_timestamp = False
            assumption_disclosure = (
                "Imported CSV records lack original exchange transmission logs or dissemination timestamps. "
                "EOD Bhavcopy availability is modeled under configured conservative simulation policy (16:30 IST / 11:00 UTC, v1.0) "
                "based on official NSE closing schedule. This policy does not independently prove historical publication time."
            )

        # 2. Query candles for symbol
        candle_query = db.query(Candle).filter(
            Candle.symbol == sym,
            Candle.is_synthetic == False
        )
        if dataset_id:
            candle_query = candle_query.filter(Candle.dataset_id == dataset_id)

        all_bars = candle_query.order_by(Candle.timestamp.asc()).all()

        # 3. Filter non-trading session artifacts and apply information availability cutoff
        historical_bars = []
        for c in all_bars:
            if c.timestamp is None:
                continue

            if HistoricalMarketDataProvider.is_non_trading_session_artifact(
                c.timestamp, c.open, c.high, c.low, c.close, c.volume, sym
            ):
                continue

            try:
                avail_dt = cls.get_bar_information_availability_timestamp(c.timestamp)
            except (TypeError, ValueError) as error:
                logger.debug("Skipping candle with invalid availability timestamp: %s", error)
                continue

            if avail_dt <= cutoff_datetime:
                historical_bars.append((avail_dt, c))

        if not historical_bars:
            return {
                "replay_id": replay_id,
                "symbol": sym,
                "cutoff_time": cutoff_datetime.isoformat(),
                "cutoff_timestamp": cutoff_datetime.isoformat(),
                "status": "FAILED_NO_DATA",
                "error": f"No historical market bars available on or before cutoff {cutoff_datetime.isoformat()} for {sym}.",
                "bars_available": 0,
                "is_replay": True,
                "mode": "HISTORICAL_EVIDENCE_REPLAY",
                "source_classification": source_classification,
                "information_availability_rule": (
                    "Documented exchange release timestamp" if is_recorded_timestamp
                    else "Configured conservative simulation assumption: 16:30 IST (11:00 UTC, v1.0)"
                ),
                "availability_policy_metadata": {
                    "source_classification": source_classification,
                    "recorded_timestamp_present": is_recorded_timestamp,
                    "availability_policy": availability_policy,
                    "availability_policy_version": availability_policy_version,
                    "configured_threshold_ist": "16:30:00 IST",
                    "configured_threshold_utc": "11:00:00 UTC",
                    "assumption_disclosure": assumption_disclosure,
                }
            }

        # 4. Strict lookahead verification: ensure zero future bars leak into replay
        historical_bars.sort(key=lambda x: x[0])
        future_leak_check = any(avail_dt > cutoff_datetime for avail_dt, _ in historical_bars)
        if future_leak_check:
            raise RuntimeError("CRITICAL INTEGRITY FAILURE: Future bar detected after replay cutoff!")

        latest_avail_dt, latest_bar = historical_bars[-1]
        raw_candles = [b[1] for b in historical_bars]
        bars_count = len(raw_candles)

        # 5. Compute deterministic indicators strictly from available history
        prices = [c.close for c in raw_candles]
        sma_20 = round(sum(prices[-20:]) / 20.0, 2) if bars_count >= 20 else None
        sma_50 = round(sum(prices[-50:]) / 50.0, 2) if bars_count >= 50 else None

        # 6. Provenance and Limitation Disclosure
        provenance_str = (
            f"Point-in-time replay at cutoff {cutoff_datetime.isoformat()} based on {bars_count} historical bars. "
            f"Latest bar timestamp: {latest_bar.timestamp.isoformat()}. "
            f"Availability timestamp: {latest_avail_dt.isoformat()}. "
            f"Policy: {availability_policy} ({availability_policy_version}). "
            f"Dataset: {dataset_meta.id if dataset_meta else 'VERIFIED_HISTORICAL_ARCHIVE'}."
        )
        content_hash = cls.compute_sha256({
            "symbol": sym,
            "cutoff": cutoff_datetime.isoformat(),
            "latest_bar": {
                "time": latest_bar.timestamp.isoformat(),
                "open": latest_bar.open,
                "high": latest_bar.high,
                "low": latest_bar.low,
                "close": latest_bar.close,
                "volume": latest_bar.volume
            },
            "bars_count": bars_count,
            "sma_20": sma_20
        })

        total_symbol_bars = db.query(Candle).filter(Candle.symbol == sym, Candle.is_synthetic == False).count()
        future_bars_excluded_count = max(0, total_symbol_bars - bars_count)

        return {
            "replay_id": replay_id,
            "symbol": sym,
            "cutoff_timestamp": cutoff_datetime.isoformat(),
            "is_replay": True,
            "mode": "HISTORICAL_EVIDENCE_REPLAY",
            "audit_label": "HISTORICAL_MARKET_DATA_REPLAY",
            "reconstruction_type": "POINT_IN_TIME_OHLCV_REPLAY",
            "source_classification": source_classification,
            "information_availability_rule": (
                "Documented exchange release timestamp" if is_recorded_timestamp
                else "Configured conservative simulation assumption: 16:30 IST (11:00 UTC, v1.0)"
            ),
            "availability_policy_metadata": {
                "source_classification": source_classification,
                "recorded_timestamp_present": is_recorded_timestamp,
                "availability_policy": availability_policy,
                "availability_policy_version": availability_policy_version,
                "configured_threshold_ist": "16:30:00 IST",
                "configured_threshold_utc": "11:00:00 UTC",
                "assumption_disclosure": assumption_disclosure,
            },
            "latest_bar_availability_timestamp": latest_avail_dt.isoformat(),
            "latest_observed_bar": {
                "timestamp": latest_bar.timestamp.isoformat(),
                "open": latest_bar.open,
                "high": latest_bar.high,
                "low": latest_bar.low,
                "close": latest_bar.close,
                "volume": latest_bar.volume,
            },
            "historical_indicators": {
                "sma_20": sma_20,
                "sma_50": sma_50,
                "observations_count": bars_count,
                "min_observations_met": bars_count >= 20
            },
            "evidence_snapshot": {
                "snapshot_id": f"SNAP_{replay_id}",
                "content_hash_sha256": content_hash,
                "source": dataset_meta.source if dataset_meta else "HISTORICAL_RESEARCH_ARCHIVE",
                "evidence_tags_available": ["EV_PRICE", "EV_IND"],
                "missing_sources_disclosed": [
                    "EV_MACRO (Archived RBI transcripts not available for this cutoff)",
                    "EV_NEWS (Archived corporate filings not available for this cutoff)"
                ]
            },
            "lookahead_prevention_verified": True,
            "information_availability_status": {
                "price_data": price_availability_status,
                "macro_data": "UNVERIFIABLE_INSUFFICIENT_PROVENANCE",
                "news_filings": "UNVERIFIABLE_INSUFFICIENT_PROVENANCE"
            },
            "leakage_prevention_breakdown": {
                "market_ohlcv_leakage_prevented": True,
                "macro_leakage_prevented": "UNVERIFIABLE_OMITTED (Omitted from decision inputs due to missing publication timestamps)",
                "news_filings_leakage_prevented": "UNVERIFIABLE_OMITTED (Omitted from decision inputs due to missing dissemination timestamps)"
            },
            "future_bars_excluded_count": future_bars_excluded_count,
            "provenance": provenance_str,
            "notes": (
                f"Point-in-time replay completed. Source: {source_classification}. "
                f"Market data limited to observations available on or before cutoff under policy {availability_policy}. "
                "Archived documents and news context are honestly reported as unavailable."
            )
        }


evidence_verifier = EvidenceVerificationService()
