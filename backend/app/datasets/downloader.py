import io
from datetime import UTC, datetime
from typing import Any

from app.core.logging import logger
from app.datasets.importer import DatasetImporter
from sqlalchemy.orm import Session


class OptionalMarketDownloader:
    """
    Workflow B: Optional, explicitly initiated historical market data downloader.
    Uses yfinance as an optional tool. Disabled by default, never runs on startup.
    Works completely offline when not triggered.
    """

    SUPPORTED_PERIODS = ("1mo", "3mo", "6mo", "1y", "2y", "5y", "max")
    SUPPORTED_INTERVALS = ("1d", "1wk", "1mo", "1h", "15m", "5m")

    @classmethod
    def format_symbol_for_yahoo(cls, symbol: str) -> str:
        s = symbol.strip().upper()
        if s.startswith("^"):
            return s
        if s in ["NIFTY", "NIFTY50", "NIFTY 50"]:
            return "^NSEI"
        if s in ["SENSEX", "BSESN"]:
            return "^BSESN"
        if "." not in s and not s.endswith(".NS") and not s.endswith(".BO"):
            # Default Indian symbols to National Stock Exchange (.NS)
            return f"{s}.NS"
        return s

    @classmethod
    def preview_download_scope(
        cls,
        symbol: str,
        period: str = "1y",
        interval: str = "1d"
    ) -> dict[str, Any]:
        """
        Inspect expected download scope before initiating data transfer.
        """
        formatted_ticker = cls.format_symbol_for_yahoo(symbol)
        return {
            "source": "Yahoo Finance (via open-source yfinance)",
            "requested_symbol": symbol,
            "resolved_ticker": formatted_ticker,
            "period": period,
            "interval": interval,
            "license_terms": "Yahoo Finance public web data. Educational & research use. Not official exchange data.",
            "requires_api_key": False,
            "rate_limit_info": "Polite non-concurrent polling; respect Yahoo terms of service.",
            "is_available": True,
        }

    @classmethod
    def download_and_import(
        cls,
        db: Session,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        dataset_name: str | None = None,
        asset_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Explicitly initiated download and ingestion.
        """
        try:
            import yfinance as yf
        except ImportError:
            raise RuntimeError(
                "yfinance is not installed in the environment. "
                "Install it with 'pip install yfinance' or import data via Workflow A (Local CSV)."
            )

        formatted_ticker = cls.format_symbol_for_yahoo(symbol)
        clean_symbol = symbol.strip().upper().replace(".NS", "").replace("^", "")

        logger.info(f"Initiating optional explicit historical download for {formatted_ticker} (period={period}, interval={interval})")

        try:
            ticker = yf.Ticker(formatted_ticker)
            # Fetch unadjusted OHLCV to maintain accurate raw exchange numbers
            df = ticker.history(period=period, interval=interval, auto_adjust=False)
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            raise RuntimeError(f"Network error or timeout connecting to Yahoo Finance for '{formatted_ticker}': {e!s}")

        if df is None or df.empty:
            raise ValueError(f"No historical data returned for ticker '{formatted_ticker}'. Verify the symbol or try Workflow A.")

        # Reset index to turn Datetime into a column
        df = df.reset_index()

        # Build custom mapping
        custom_mapping = {
            "Date": "timestamp",
            "Datetime": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }

        # Convert dataframe to CSV string buffer for DatasetImporter
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        dataset_id = f"ds_{clean_symbol.lower()}_yf_{period}_{interval}"
        if not dataset_name:
            dataset_name = f"{clean_symbol} Historical {interval.upper()} (Yahoo Finance)"
        if not asset_name:
            asset_name = f"{clean_symbol} Historical Asset"

        return DatasetImporter.import_csv(
            db=db,
            csv_source=csv_buffer,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            symbol=clean_symbol,
            asset_name=asset_name,
            exchange="NSE",
            source="YFINANCE",
            provenance=f"Downloaded via yfinance for ticker '{formatted_ticker}' on {datetime.now(UTC).isoformat()}",
            timeframe=interval,
            is_adjusted=False,
            adjustment_status="UNADJUSTED",
            license_info="Yahoo Finance public web data. Educational & research use only.",
            custom_mapping=custom_mapping,
        )
