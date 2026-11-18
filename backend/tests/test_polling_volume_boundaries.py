"""
Deterministic Boundary Test Suite for Polling-Derived Volume and Candle Aggregation.
Verifies the exact requirements of Section 2:
1. Volume changes before the first poll inside a candle
2. A valid baseline immediately before the interval
3. A missing prior baseline
4. Duplicate observations
5. Counter resets / counter decreases
6. Out-of-order events
7. Market open and market close session boundaries
8. Unavailable volume when snapshots lack volume
9. Two adjacent intervals without double-counting
"""

from datetime import UTC, datetime, timedelta

from app.market.ramm_adapter import PollingCandleAggregator


def test_volume_changes_before_first_poll_inside_candle():
    """
    Verify interval volume includes volume changes between candle boundary and first observation.
    Boundary T_start = 10:00:00 UTC.
    Baseline at 09:59:50 UTC had cumulative volume 1,000,000.
    First poll inside candle at 10:01:00 UTC had cumulative volume 1,020,000 (20k shares traded before first poll!).
    Last poll inside candle at 10:04:30 UTC had cumulative volume 1,050,000.
    Interval volume must be 50,000 (NOT 30,000!).
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Baseline immediately prior to T_start
    agg.add_observation("RELIANCE", 1200.0, 1000000, t_start - timedelta(seconds=10))

    # Polls inside interval [10:00, 10:05)
    agg.add_observation("RELIANCE", 1205.0, 1020000, t_start + timedelta(minutes=1))
    agg.add_observation("RELIANCE", 1210.0, 1050000, t_start + timedelta(minutes=4, seconds=30))

    candles = agg.get_aggregated_candles("RELIANCE", interval_minutes=5)
    # Target candle [10:00 - 10:05)
    target_candle = next(c for c in candles if "10:00:00" in c["timestamp"])

    # Must accurately reflect 50,000 shares total (1,050,000 - 1,000,000)
    assert target_candle["volume"] == 50000
    assert target_candle["volume_semantics"] == "BASELINE_DELTA_APPROXIMATION"
    assert target_candle["volume_is_approximate"] is True
    assert target_candle["open"] == 1205.0
    assert target_candle["close"] == 1210.0


def test_valid_baseline_immediately_before_interval():
    """
    Verify calculation with a valid baseline immediately before the interval.
    T_start = 10:00:00 UTC.
    Baseline at 09:59:59 UTC has cum_vol = 500,000.
    Latest poll at 10:04:00 UTC has cum_vol = 512,000.
    Interval volume must be 12,000.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    agg.add_observation("TCS", 3500.0, 500000, t_start - timedelta(seconds=1))
    agg.add_observation("TCS", 3510.0, 505000, t_start + timedelta(minutes=2))
    agg.add_observation("TCS", 3505.0, 512000, t_start + timedelta(minutes=4))

    candles = agg.get_aggregated_candles("TCS", interval_minutes=5)
    target_candle = next(c for c in candles if "10:00:00" in c["timestamp"])
    assert target_candle["volume"] == 12000
    assert target_candle["volume_semantics"] == "BASELINE_DELTA_APPROXIMATION"


def test_missing_prior_baseline():
    """
    Verify that when no baseline at or before the interval boundary exists,
    and strict prior baseline is required, volume is marked None and UNAVAILABLE.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # First observation arrives mid-interval without any prior baseline
    agg.add_observation("INFY", 1500.0, 10000000, t_start + timedelta(minutes=2))
    agg.add_observation("INFY", 1510.0, 10030000, t_start + timedelta(minutes=4))

    # With strict prior baseline required
    candles_strict = agg.get_aggregated_candles("INFY", interval_minutes=5, require_prior_baseline=True)
    assert len(candles_strict) == 1
    assert candles_strict[0]["volume"] is None
    assert candles_strict[0]["volume_semantics"] == "UNAVAILABLE"
    assert "Missing prior baseline" in candles_strict[0]["volume_diagnostic"]

    # Without strict flag (default backward-compatible fallback to internal delta)
    candles_fallback = agg.get_aggregated_candles("INFY", interval_minutes=5, require_prior_baseline=False)
    assert len(candles_fallback) == 1
    assert candles_fallback[0]["volume"] == 30000
    assert candles_fallback[0]["volume_semantics"] == "PARTIAL_INTERVAL_APPROXIMATION"


def test_duplicate_observations():
    """
    Verify duplicate identical observations are handled safely and do not corrupt sample count.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Baseline
    agg.add_observation("HDFCBANK", 1600.0, 200000, t_start)
    # Consecutive duplicate observation (same timestamp, price, volume)
    agg.add_observation("HDFCBANK", 1600.0, 200000, t_start)

    # Mid poll
    agg.add_observation("HDFCBANK", 1610.0, 210000, t_start + timedelta(minutes=2))
    agg.add_observation("HDFCBANK", 1610.0, 210000, t_start + timedelta(minutes=2))

    candles = agg.get_aggregated_candles("HDFCBANK", interval_minutes=5)
    assert len(candles) == 1
    assert candles[0]["volume"] == 10000
    assert candles[0]["open"] == 1600.0
    assert candles[0]["close"] == 1610.0
    # Duplicate filter preserved exact 2 unique observations
    assert candles[0]["sample_count"] == 2


def test_counter_resets_and_decreases():
    """
    Verify detection of non-monotonic counter decreases or provider resets.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Baseline at 50,000
    agg.add_observation("SBIN", 800.0, 50000, t_start - timedelta(seconds=5))
    # Subsequent observation unexpectedly drops to 10,000 (counter reset or corrupt data)
    agg.add_observation("SBIN", 805.0, 10000, t_start + timedelta(minutes=3))

    candles = agg.get_aggregated_candles("SBIN", interval_minutes=5)
    target_candle = next(c for c in candles if "10:00:00" in c["timestamp"])
    assert target_candle["volume"] is None
    assert target_candle["volume_semantics"] == "UNAVAILABLE"
    assert "decrease or reset" in target_candle["volume_diagnostic"]


def test_out_of_order_events():
    """
    Verify out-of-order observation timestamps are sorted chronologically before OHLC and volume calculation.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Baseline at boundary
    agg.add_observation("ICICIBANK", 1100.0, 100000, t_start)

    # Arriving out-of-order: 10:04 first, then 10:01, then 10:03
    agg.add_observation("ICICIBANK", 1120.0, 140000, t_start + timedelta(minutes=4))  # High / Close
    agg.add_observation("ICICIBANK", 1090.0, 110000, t_start + timedelta(minutes=1))  # Low / First in interval
    agg.add_observation("ICICIBANK", 1105.0, 125000, t_start + timedelta(minutes=3))

    candles = agg.get_aggregated_candles("ICICIBANK", interval_minutes=5)
    assert len(candles) == 1
    c = candles[0]
    # Sorted order: 10:00 (1100), 10:01 (1090), 10:03 (1105), 10:04 (1120)
    assert c["open"] == 1100.0
    assert c["low"] == 1090.0
    assert c["high"] == 1120.0
    assert c["close"] == 1120.0
    assert c["volume"] == 40000  # 140000 - 100000


def test_market_open_and_close_session_boundaries():
    """
    Verify session boundary: yesterday's baseline cannot be subtracted from today's market open candle.
    At market open (09:15 IST), exchange cumulative daily volume resets to 0.
    """
    agg = PollingCandleAggregator()

    # Yesterday's closing tick at 15:29 IST (09:59 UTC on Oct 21)
    yesterday_tick = datetime(2026, 10, 21, 9, 59, 0, tzinfo=UTC)
    agg.add_observation("BHARTIARTL", 1500.0, 12000000, yesterday_tick)

    # Today's market open bucket at 09:15 IST (03:45 UTC on Oct 22)
    today_open_bucket = datetime(2026, 10, 22, 3, 45, 0, tzinfo=UTC)
    # Observation inside today's first candle at 09:16 IST (03:46 UTC)
    agg.add_observation("BHARTIARTL", 1510.0, 50000, today_open_bucket + timedelta(minutes=1))

    candles = agg.get_aggregated_candles("BHARTIARTL", interval_minutes=5, require_prior_baseline=True)
    # We should have candles for both buckets
    today_candle = next(c for c in candles if "03:45:00" in c["timestamp"])

    # Yesterday's 12M volume MUST NOT be subtracted from today's 50k opening volume!
    assert today_candle["volume"] is None
    assert today_candle["volume_semantics"] == "UNAVAILABLE"
    assert "Session boundary" in today_candle["volume_diagnostic"]


def test_unavailable_volume_when_snapshots_lack_volume():
    """
    Verify interval volume is marked None when volume is unavailable or unverified in raw observations.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    agg.add_observation("MARUTI", 12000.0, None, t_start)
    agg.add_observation("MARUTI", 12050.0, None, t_start + timedelta(minutes=2))

    candles = agg.get_aggregated_candles("MARUTI", interval_minutes=5)
    assert len(candles) == 1
    assert candles[0]["volume"] is None
    assert candles[0]["volume_semantics"] == "UNAVAILABLE"


def test_two_adjacent_intervals_without_double_counting():
    """
    Verify mathematical consistency across adjacent intervals:
    Total volume across Interval 1 + Interval 2 must equal (V_last2 - V_base1).
    Zero double-counting and zero volume omission between interval boundaries.
    """
    agg = PollingCandleAggregator()
    t0 = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Baseline at 10:00:00 with cum_vol = 10,000
    agg.add_observation("LT", 3200.0, 10000, t0)

    # Observations in Interval 1 [10:00 - 10:05)
    agg.add_observation("LT", 3210.0, 12000, t0 + timedelta(minutes=2))
    agg.add_observation("LT", 3220.0, 15000, t0 + timedelta(minutes=4))  # Last poll in Interval 1

    # Observations in Interval 2 [10:05 - 10:10)
    agg.add_observation("LT", 3225.0, 18000, t0 + timedelta(minutes=7))
    agg.add_observation("LT", 3230.0, 22000, t0 + timedelta(minutes=9))  # Last poll in Interval 2

    candles = agg.get_aggregated_candles("LT", interval_minutes=5)
    assert len(candles) == 2

    c1 = candles[0]
    c2 = candles[1]

    # Interval 1: 15,000 - 10,000 = 5,000
    assert c1["volume"] == 5000
    # Interval 2: 22,000 - 15,000 = 7,000 (uses last observation <= 10:05 as baseline)
    assert c2["volume"] == 7000

    # Total combined: 5,000 + 7,000 = 12,000 == 22,000 - 10,000!
    assert c1["volume"] + c2["volume"] == 12000
    assert c1["volume_semantics"] == "BASELINE_DELTA_APPROXIMATION"
    assert c2["volume_semantics"] == "BASELINE_DELTA_APPROXIMATION"


def test_insufficient_baseline_single_sample_returns_null_not_zero():
    """
    Verify volume integrity when baseline is insufficient:
    A single observation inside a candle without a boundary baseline CANNOT establish a volume delta.
    It MUST be represented as unavailable (None / null in JSON) with explicit status,
    NOT a numeric zero that falsely implies no trades occurred.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Only a single observation arrives inside the interval [10:00, 10:05)
    agg.add_observation("WIPRO", 550.0, 500000, t_start + timedelta(minutes=2))

    candles = agg.get_aggregated_candles("WIPRO", interval_minutes=5)
    assert len(candles) == 1
    c = candles[0]

    # Must be None, NEVER numeric 0!
    assert c["volume"] is None
    assert c["volume_semantics"] == "UNAVAILABLE"
    assert "insufficient_baseline" in c["volume_diagnostic"].lower()


def test_insufficient_baseline_single_boundary_sample_returns_null():
    """
    Verify volume integrity when only a start-boundary sample exists:
    An observation at T_start without any subsequent intra-interval poll cannot establish
    what trades occurred during the candle interval. Must return None and UNAVAILABLE.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Observation exactly at 10:00:00, but no further polls in [10:00, 10:05)
    agg.add_observation("COALINDIA", 450.0, 1200000, t_start)

    candles = agg.get_aggregated_candles("COALINDIA", interval_minutes=5)
    assert len(candles) == 1
    c = candles[0]

    assert c["volume"] is None
    assert c["volume_semantics"] == "UNAVAILABLE"
    assert "insufficient_baseline" in c["volume_diagnostic"].lower()


def test_insufficient_baseline_flat_intra_interval_without_boundary():
    """
    Verify volume integrity when volume is unchanged between intra-candle polls
    but no boundary baseline exists: cannot determine trades prior to first poll,
    so delta is unavailable (None), NOT a numeric 0.
    """
    agg = PollingCandleAggregator()
    t_start = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)

    # Two observations inside candle with unchanged cumulative volume, but no baseline at 10:00:00
    agg.add_observation("NTPC", 380.0, 800000, t_start + timedelta(minutes=1))
    agg.add_observation("NTPC", 380.5, 800000, t_start + timedelta(minutes=3))

    candles = agg.get_aggregated_candles("NTPC", interval_minutes=5)
    assert len(candles) == 1
    c = candles[0]

    assert c["volume"] is None
    assert c["volume_semantics"] == "UNAVAILABLE"
    assert "insufficient_baseline" in c["volume_diagnostic"].lower()
