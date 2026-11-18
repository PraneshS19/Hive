from datetime import UTC, datetime, timedelta

from app.db.models import Candle, EvidenceSnapshotRecord, ReviewRun
from app.market.evidence_verifier import EvidenceVerificationService


def test_pit_replay_future_candle_leakage_defense(db):
    """
    Challenge PIT replay by injecting future candles into the database.
    Verify that candles with timestamp > cutoff T are strictly excluded from observations,
    and that computed SMA indicators strictly ignore future price data.
    """
    sym = "TEST_LEAK_SYM"
    cutoff = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

    # 1. Insert 25 past candles (before cutoff) with price = 100.0
    for i in range(25):
        c_time = cutoff - timedelta(days=26 - i)
        c = Candle(
            symbol=sym,
            timestamp=c_time,
            open=100.0,
            high=105.0,
            low=95.0,
            close=100.0,
            volume=10000,
            is_synthetic=False,
            dataset_id="ds_test_pit"
        )
        db.add(c)

    # 2. Insert 10 FUTURE candles (after cutoff) with extreme price = 5000.0
    for i in range(1, 11):
        future_time = cutoff + timedelta(days=i)
        c_future = Candle(
            symbol=sym,
            timestamp=future_time,
            open=5000.0,
            high=5100.0,
            low=4900.0,
            close=5000.0,
            volume=99999,
            is_synthetic=False,
            dataset_id="ds_test_pit"
        )
        db.add(c_future)

    db.commit()

    # 3. Execute Point-in-Time Replay at cutoff
    replay = EvidenceVerificationService.point_in_time_evidence_replay(
        symbol=sym,
        cutoff_datetime=cutoff,
        db=db,
        dataset_id="ds_test_pit"
    )

    # 4. Strict assertions:
    assert replay["is_replay"] is True
    assert replay["mode"] == "HISTORICAL_EVIDENCE_REPLAY"
    assert replay["lookahead_prevention_verified"] is True
    assert replay["latest_observed_bar"]["close"] == 100.0  # NOT 5000.0!
    assert replay["historical_indicators"]["sma_20"] == 100.0  # NOT contaminated by 5000.0!
    assert replay["historical_indicators"]["observations_count"] == 25
    assert replay["future_bars_excluded_count"] == 10  # Correctly identifies 10 excluded future bars!


def test_pit_replay_does_not_mutate_original_runs_or_snapshots(db):
    """
    Verify that point-in-time replay generates isolated execution records with a distinct
    replay identifier and leaves original ReviewRun and primary database records intact.
    """
    sym = "RELIANCE"
    cutoff = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)

    review_runs_before = db.query(ReviewRun).count()
    snapshots_before = db.query(EvidenceSnapshotRecord).count()

    replay = EvidenceVerificationService.point_in_time_evidence_replay(
        symbol=sym,
        cutoff_datetime=cutoff,
        db=db
    )

    review_runs_after = db.query(ReviewRun).count()
    snapshots_after = db.query(EvidenceSnapshotRecord).count()

    # Verify isolated ID
    assert replay["replay_id"].startswith("REPLAY_")
    assert "20260601" in replay["replay_id"]

    # Original tables remain unmutated by read-only replay
    assert review_runs_before == review_runs_after
    assert snapshots_before == snapshots_after


def test_pit_replay_discloses_missing_archival_sources(db):
    """
    Verify that when historical qualitative data is missing, the replay honestly
    discloses limitations rather than fabricating context.
    """
    sym = "TCS"
    cutoff = datetime(2026, 4, 15, 0, 0, 0, tzinfo=UTC)

    replay = EvidenceVerificationService.point_in_time_evidence_replay(
        symbol=sym,
        cutoff_datetime=cutoff,
        db=db
    )

    if replay.get("status") != "FAILED_NO_DATA":
        missing_sources = replay["evidence_snapshot"]["missing_sources_disclosed"]
        assert any("EV_MACRO" in s for s in missing_sources)
        assert any("EV_NEWS" in s for s in missing_sources)


def test_pit_replay_rejects_pre_dataset_cutoff_without_synthetic_fallback(db):
    """
    Verify that querying a cutoff earlier than available data truthfully returns FAILED_NO_DATA
    rather than synthesizing synthetic candles.
    """
    sym = "RELIANCE"
    cutoff = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)

    replay = EvidenceVerificationService.point_in_time_evidence_replay(
        symbol=sym,
        cutoff_datetime=cutoff,
        db=db
    )

    assert replay["status"] == "FAILED_NO_DATA"
    assert "No historical market bars available" in replay["error"]
    assert replay["bars_available"] == 0


def test_pit_replay_information_availability_metadata_handling(db):
    """
    Priority 5 Challenge:
    Verify that replay outputs distinguish verifiable point-in-time price data
    from unverifiable macroeconomic and news feeds that lack information-availability timestamps.
    """
    sym = "INFY"
    cutoff = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)

    replay = EvidenceVerificationService.point_in_time_evidence_replay(
        symbol=sym,
        cutoff_datetime=cutoff,
        db=db
    )

    if replay.get("status") != "FAILED_NO_DATA":
        assert "information_availability_status" in replay
        info_status = replay["information_availability_status"]
        assert info_status["price_data"] in ("VERIFIED_POINT_IN_TIME", "ASSUMED_POINT_IN_TIME")
        assert info_status["macro_data"] == "UNVERIFIABLE_INSUFFICIENT_PROVENANCE"
        assert info_status["news_filings"] == "UNVERIFIABLE_INSUFFICIENT_PROVENANCE"

        assert "leakage_prevention_breakdown" in replay
        breakdown = replay["leakage_prevention_breakdown"]
        assert breakdown["market_ohlcv_leakage_prevented"] is True
        assert "UNVERIFIABLE_OMITTED" in breakdown["macro_leakage_prevented"]
        assert "UNVERIFIABLE_OMITTED" in breakdown["news_filings_leakage_prevented"]
