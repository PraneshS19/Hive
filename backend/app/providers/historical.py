from datetime import UTC, datetime
from typing import Any

import pandas as pd
from app.db.models import Candle, Dataset
from app.market.dhan_adapter import IST_OFFSET, NSE_HOLIDAYS_2026, NSE_WEEKEND_HOLIDAYS_2026
from sqlalchemy.orm import Session


class DatasetNotFoundError(Exception):
    """Raised when a requested historical dataset or symbol does not exist in registry."""


class InsufficientDataError(Exception):
    """Raised when historical data exists but is insufficient for strategy indicators."""


class HistoricalMarketDataProvider:
    """
    Historical Market Data Provider.
    Retrieves validated historical candles from SQLite.
    Distinguishes raw imported rows from active research observations,
    excluding non-trading session carry-forward artifacts from quantitative indicator calculations.
    Strictly zero synthetic fallback or data fabrication.
    """

    @classmethod
    def is_non_trading_session_artifact(
        cls,
        candle_timestamp: datetime,
        open_p: float,
        high_p: float,
        low_p: float,
        close_p: float,
        volume: float,
        symbol: str = ""
    ) -> bool:
        """
        Identifies whether a historical candle is a non-trading session carry-forward artifact.
        Conditions:
        1. Flat prices: open == high == low == close.
        2. Zero volume: volume == 0.0.
        3. The session date (in IST) is an official exchange trading holiday or weekend closure.
        Does NOT globally discard legitimate low-volume trading bars or index rows.
        """
        # Benchmark indices (e.g. NIFTY50) may have 0 volume reported but non-flat prices
        if not (open_p == high_p == low_p == close_p and volume == 0.0):
            return False

        dt = candle_timestamp if candle_timestamp.tzinfo else candle_timestamp.replace(tzinfo=UTC)
        ist_dt = dt.astimezone(IST_OFFSET)
        ist_date_str = ist_dt.strftime("%Y-%m-%d")

        is_holiday = (
            ist_date_str in NSE_HOLIDAYS_2026 or
            ist_date_str in NSE_WEEKEND_HOLIDAYS_2026 or
            ist_dt.weekday() in (5, 6)
        )
        return is_holiday

    def get_candles(
        self,
        db: Session,
        symbol: str | None = None,
        dataset_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        min_bars: int = 15,
        exclude_non_trading_artifacts: bool = True,
    ) -> pd.DataFrame:
        query = db.query(Candle).filter(Candle.is_synthetic == False)

        if dataset_id:
            query = query.filter(Candle.dataset_id == dataset_id)
        elif symbol:
            query = query.filter(Candle.symbol == symbol.strip().upper())
        else:
            raise DatasetNotFoundError("Must specify either dataset_id or symbol for historical market data.")

        if start_date:
            try:
                start_dt = pd.to_datetime(start_date)
                query = query.filter(Candle.timestamp >= start_dt)
            except (TypeError, ValueError):
                pass

        if end_date:
            try:
                end_dt = pd.to_datetime(end_date)
                query = query.filter(Candle.timestamp <= end_dt)
            except (TypeError, ValueError):
                pass

        candles = query.order_by(Candle.timestamp.asc()).all()

        if not candles:
            target = f"dataset_id='{dataset_id}'" if dataset_id else f"symbol='{symbol}'"
            raise DatasetNotFoundError(
                f"No verified historical candles found for {target}. "
                f"Please import or download a historical dataset for this asset first."
            )

        data = []
        for c in candles:
            is_artifact = self.is_non_trading_session_artifact(
                candle_timestamp=c.timestamp,
                open_p=c.open,
                high_p=c.high,
                low_p=c.low,
                close_p=c.close,
                volume=c.volume,
                symbol=c.symbol
            )

            if exclude_non_trading_artifacts and is_artifact:
                continue

            data.append({
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "is_valid_for_research": not is_artifact,
                "research_status": "NON_TRADING_SESSION_ARTIFACT" if is_artifact else "VALID_RESEARCH"
            })

        if len(data) < min_bars:
            raise InsufficientDataError(
                f"Insufficient historical bars ({len(data)}) for strategy indicators (minimum {min_bars} required)."
            )

        df = pd.DataFrame(data)
        return df

    @classmethod
    def align_series_by_session_date(
        cls,
        df_target: pd.DataFrame,
        df_benchmark: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Aligns two market data series strictly by their calendar session date (IST).
        Handles unequal coverage (e.g. ICICIBANK with 245 bars starting 2025-10-23 vs
        NIFTY50 with 246 bars starting 2025-10-21) via deterministic inner intersection
        on session_date. Strictly prevents silent value insertion, forward-filling,
        or date-mismatched index comparison.
        """
        from app.market.evidence_verifier import EvidenceVerificationService

        target = df_target.copy()
        benchmark = df_benchmark.copy()

        target["session_date"] = target["timestamp"].apply(
            lambda ts: EvidenceVerificationService.get_bar_session_date(ts).strftime("%Y-%m-%d")
        )
        benchmark["session_date"] = benchmark["timestamp"].apply(
            lambda ts: EvidenceVerificationService.get_bar_session_date(ts).strftime("%Y-%m-%d")
        )

        common_dates = sorted(set(target["session_date"]).intersection(set(benchmark["session_date"])))
        aligned_target = target[target["session_date"].isin(common_dates)].sort_values("session_date").reset_index(drop=True)
        aligned_benchmark = benchmark[benchmark["session_date"].isin(common_dates)].sort_values("session_date").reset_index(drop=True)

        return aligned_target, aligned_benchmark

    def get_dataset(self, db: Session, dataset_id: str) -> Dataset | None:
        return db.query(Dataset).filter(Dataset.id == dataset_id).first()

    def list_datasets(self, db: Session) -> list[Dataset]:
        return db.query(Dataset).order_by(Dataset.created_at.desc()).all()

    def get_provenance(self) -> dict[str, Any]:
        return {
            "provider": "HistoricalMarketDataProvider",
            "storage": "SQLite Verified Registry",
            "policy": "Strict Real-Data Only (Synthetic Data Disallowed)",
            "supported_exchanges": ["NSE"],
        }


historical_provider = HistoricalMarketDataProvider()
