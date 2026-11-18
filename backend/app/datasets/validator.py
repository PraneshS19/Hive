import math
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pandas as pd

# Known major Indian NSE Trading Holidays (recent years reference for gap detection)
INDIAN_EXCHANGE_HOLIDAYS = {
    "2023-01-26", "2023-03-07", "2023-03-30", "2023-04-04", "2023-04-07", "2023-04-14",
    "2023-05-01", "2023-06-29", "2023-08-15", "2023-09-19", "2023-10-02", "2023-10-24",
    "2023-11-14", "2023-11-27", "2023-12-25",
    "2024-01-22", "2024-01-26", "2024-03-08", "2024-03-25", "2024-03-29", "2024-04-11",
    "2024-04-17", "2024-05-01", "2024-05-20", "2024-06-17", "2024-07-17", "2024-08-15",
    "2024-10-02", "2024-11-01", "2024-11-15", "2024-12-25",
    "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
    "2025-04-18", "2025-05-01", "2025-06-07", "2025-08-15", "2025-08-27", "2025-10-02",
    "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
    "2026-01-26", "2026-03-03", "2026-03-20", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-08-15", "2026-10-02", "2026-10-20", "2026-11-09", "2026-12-25"
}


class ValidationReport:
    def __init__(self):
        self.total_rows: int = 0
        self.accepted_rows: int = 0
        self.rejected_rows: int = 0
        self.duplicate_count: int = 0
        self.rejections: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.gaps_detected: list[dict[str, Any]] = []
        self.start_date: datetime | None = None
        self.end_date: datetime | None = None
        self.clean_df: pd.DataFrame | None = None
        self.status: str = "VALIDATED"  # VALIDATED, WARNINGS, REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_rows": self.total_rows,
            "accepted_rows": self.accepted_rows,
            "rejected_rows": self.rejected_rows,
            "duplicate_count": self.duplicate_count,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "rejections": self.rejections[:50],  # cap rejection details to avoid huge payload
            "warnings": self.warnings,
            "gaps_detected": self.gaps_detected[:20],
        }


class DatasetValidator:
    """
    Strict OHLCV validator and data cleaner.
    Validates:
    - Invariants: High >= max(Open, Close), Low <= min(Open, Close), High >= Low
    - Positive prices and non-negative volume
    - Datetime parsing and timezone normalization (UTC)
    - Duplicate timestamp handling and chronological sorting
    - Calendar gaps vs known exchange holidays
    - Price discontinuities (e.g. split / unadjusted corporate action signals)
    """

    # Standard column header aliases for auto-mapping
    COLUMN_ALIASES: ClassVar[dict[str, list[str]]] = {
        "timestamp": ["date", "timestamp", "datetime", "time", "date/time", "trade_date", "trade date", "tradedate", "trans_date"],
        "open": ["open", "open price", "open_price", "first_price", "openprice", "open_val"],
        "high": ["high", "high price", "high_price", "highprice", "high_val"],
        "low": ["low", "low price", "low_price", "lowprice", "low_val"],
        "close": ["close", "close price", "close_price", "last_price", "closeprice", "ltp", "last price", "lastprice", "settle_price"],
        "volume": ["volume", "total traded quantity", "shares traded", "vol", "trade_volume", "total_volume", "qty", "tottrdqty", "net_trdqty"],
        "adj_close": ["adj close", "adj_close", "adjusted close", "adjusted_close", "adj close price"]
    }

    @classmethod
    def resolve_columns(cls, df: pd.DataFrame, custom_mapping: dict[str, str] | None = None) -> dict[str, str]:
        """
        Map dataframe column names to canonical ['timestamp', 'open', 'high', 'low', 'close', 'volume'].
        """
        mapping: dict[str, str] = {}
        df_cols_lower = {col.strip().lower(): col for col in df.columns}

        # Apply custom mapping first if provided
        if custom_mapping:
            for source_col, target_canonical in custom_mapping.items():
                if source_col in df.columns:
                    mapping[target_canonical.lower()] = source_col
                elif source_col.lower() in df_cols_lower:
                    mapping[target_canonical.lower()] = df_cols_lower[source_col.lower()]

        # For any canonical field not yet mapped, search aliases
        for canonical, aliases in cls.COLUMN_ALIASES.items():
            if canonical in mapping:
                continue
            for alias in aliases:
                if alias in df_cols_lower:
                    mapping[canonical] = df_cols_lower[alias]
                    break

        return mapping

    @classmethod
    def validate_and_clean(
        cls,
        df: pd.DataFrame,
        custom_mapping: dict[str, str] | None = None,
        symbol: str = "ASSET",
        timeframe: str = "1d"
    ) -> ValidationReport:
        report = ValidationReport()
        report.total_rows = len(df)

        if df.empty:
            report.status = "REJECTED"
            report.warnings.append("Dataset is completely empty.")
            return report

        col_map = cls.resolve_columns(df, custom_mapping)
        required = ["timestamp", "open", "high", "low", "close"]
        missing_required = [req for req in required if req not in col_map]

        if missing_required:
            report.status = "REJECTED"
            report.warnings.append(f"Missing required columns: {missing_required}. Available columns: {list(df.columns)}")
            return report

        # Extract columns
        raw_ts = df[col_map["timestamp"]]
        raw_open = df[col_map["open"]]
        raw_high = df[col_map["high"]]
        raw_low = df[col_map["low"]]
        raw_close = df[col_map["close"]]
        raw_vol = df[col_map["volume"]] if "volume" in col_map else pd.Series(0.0, index=df.index)

        valid_rows: list[dict[str, Any]] = []
        seen_timestamps = set()

        for idx in range(len(df)):
            row_idx = idx + 1
            ts_val = raw_ts.iloc[idx]
            o_val = raw_open.iloc[idx]
            h_val = raw_high.iloc[idx]
            l_val = raw_low.iloc[idx]
            c_val = raw_close.iloc[idx]
            v_val = raw_vol.iloc[idx] if idx < len(raw_vol) else 0.0

            # 1. Parse Datetime
            parsed_dt: datetime | None = None
            if pd.isna(ts_val):
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "reason": "Missing or null timestamp"})
                continue

            try:
                if isinstance(ts_val, (datetime, pd.Timestamp)):
                    parsed_dt = ts_val.to_pydatetime() if hasattr(ts_val, "to_pydatetime") else ts_val
                elif isinstance(ts_val, str):
                    # Clean string
                    clean_str = ts_val.strip()
                    # Try pandas parsing
                    parsed_dt = pd.to_datetime(clean_str).to_pydatetime()
                elif isinstance(ts_val, (int, float)):
                    # Epoch timestamp (check ms vs seconds)
                    if ts_val > 1e11:
                        parsed_dt = datetime.fromtimestamp(ts_val / 1000.0, tz=UTC)
                    else:
                        parsed_dt = datetime.fromtimestamp(ts_val, tz=UTC)
            except (TypeError, ValueError, OverflowError, OSError) as e:
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "reason": f"Unparseable datetime '{ts_val}': {e!s}"})
                continue

            if parsed_dt is None:
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "reason": f"Failed to parse datetime '{ts_val}'"})
                continue

            # Normalize timezone to UTC
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=UTC)
            else:
                parsed_dt = parsed_dt.astimezone(UTC)

            # Check duplicates
            ts_key = parsed_dt.isoformat()
            if ts_key in seen_timestamps:
                report.duplicate_count += 1
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"Duplicate timestamp '{ts_key}' ignored."})
                continue
            seen_timestamps.add(ts_key)

            # 2. Parse and Validate Numerics
            try:
                o = float(o_val)
                h = float(h_val)
                l = float(l_val)
                c = float(c_val)
                v = float(v_val) if not pd.isna(v_val) else 0.0
            except (ValueError, TypeError) as e:
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"Non-numeric OHLCV value: {e!s}"})
                continue

            # Check for NaN / Inf
            if any(math.isnan(val) or math.isinf(val) for val in [o, h, l, c, v]):
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": "NaN or infinite price/volume value"})
                continue

            # Check positivity
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"Non-positive price encountered: O={o}, H={h}, L={l}, C={c}"})
                continue

            if v < 0:
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"Negative volume encountered: V={v}"})
                continue

            # 3. OHLC Invariant Checks
            # Allow small floating point epsilon (0.0001) for rounded values
            eps = 1e-4
            if h < (l - eps):
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"OHLC invariant violation: High ({h}) < Low ({l})"})
                continue

            max_oc = max(o, c)
            min_oc = min(o, c)

            if h < (max_oc - eps):
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"OHLC invariant violation: High ({h}) < max(Open={o}, Close={c})"})
                continue

            if l > (min_oc + eps):
                report.rejected_rows += 1
                report.rejections.append({"row": row_idx, "timestamp": ts_key, "reason": f"OHLC invariant violation: Low ({l}) > min(Open={o}, Close={c})"})
                continue

            # Row is valid
            valid_rows.append({
                "timestamp": parsed_dt,
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": round(v, 2),
            })

        report.accepted_rows = len(valid_rows)

        if not valid_rows:
            report.status = "REJECTED"
            report.warnings.append("No valid candles remained after validation.")
            return report

        # 4. Chronological Sorting
        clean_df = pd.DataFrame(valid_rows).sort_values("timestamp").reset_index(drop=True)
        report.clean_df = clean_df
        report.start_date = clean_df["timestamp"].iloc[0]
        report.end_date = clean_df["timestamp"].iloc[-1]

        # 5. Gap and Holiday Analysis (for daily timeframe)
        if "d" in timeframe.lower() or "day" in timeframe.lower():
            dates = clean_df["timestamp"].dt.date
            for i in range(1, len(dates)):
                prev_d = dates.iloc[i-1]
                curr_d = dates.iloc[i]
                diff_days = (curr_d - prev_d).days

                if diff_days > 1:
                    # Check if all skipped days were weekends or exchange holidays
                    missing_business_days = 0
                    test_d = prev_d + timedelta(days=1)
                    while test_d < curr_d:
                        d_str = test_d.strftime("%Y-%m-%d")
                        is_weekend = test_d.weekday() >= 5
                        is_holiday = d_str in INDIAN_EXCHANGE_HOLIDAYS
                        if not (is_weekend or is_holiday):
                            missing_business_days += 1
                        test_d += timedelta(days=1)

                    if missing_business_days > 0:
                        report.gaps_detected.append({
                            "from_date": prev_d.isoformat(),
                            "to_date": curr_d.isoformat(),
                            "gap_calendar_days": diff_days,
                            "missing_trading_days": missing_business_days,
                            "type": "TRADING_CALENDAR_GAP"
                        })

        # 6. Price Continuity & Corporate Action Anomaly Detection
        close_series = clean_df["close"]
        price_changes = close_series.pct_change().dropna()
        large_jumps = price_changes[price_changes.abs() > 0.40]
        if not large_jumps.empty:
            for j_idx, jump in large_jumps.items():
                jump_date = clean_df["timestamp"].iloc[j_idx].strftime("%Y-%m-%d")
                report.warnings.append(
                    f"Possible corporate action or unadjusted price split on {jump_date}: overnight jump of {jump * 100:.1f}%."
                )

        if report.gaps_detected:
            report.warnings.append(
                f"Detected {len(report.gaps_detected)} trading gap(s) exceeding normal exchange weekends/holidays."
            )

        if report.rejected_rows > 0 or report.warnings:
            report.status = "WARNINGS" if report.accepted_rows > 0 else "REJECTED"
        else:
            report.status = "VALIDATED"

        return report
