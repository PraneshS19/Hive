from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import pandas as pd


class BaseMarketDataProvider(ABC):
    """Abstract base class for verified historical and real market data providers."""

    @abstractmethod
    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch latest price quote for symbol."""

    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        bars: int = 60,
        interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch OHLCV historical bars as a pandas DataFrame."""

    @abstractmethod
    def get_provenance(self) -> dict[str, Any]:
        """Return source provenance metadata."""
