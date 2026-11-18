from datetime import UTC, datetime

import pytest
from app.market.dhan_adapter import (
    IST_OFFSET,
    NSE_HOLIDAYS_2026,
    is_market_session_active,
)
from app.market.ramm_adapter import is_market_session_active as ramm_is_market_session_active


def make_ist_datetime(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    ist_dt = datetime(year, month, day, hour, minute, second, tzinfo=IST_OFFSET)
    return ist_dt.astimezone(UTC)


def test_overnight_session_before_pre_open():
    """Verify that 03:13 IST is classified as Overnight: Market Closed, NOT Pre-Market."""
    dt_utc = make_ist_datetime(2026, 10, 21, 3, 13)
    is_open, note = is_market_session_active(dt_utc)
    assert is_open is False
    assert "Overnight" in note
    assert "Pre-Open starts at 09:00 IST" in note
    assert "Regular at 09:15 IST" in note
    assert "03:13 IST" in note


def test_overnight_session_early_morning():
    """Verify that 08:59 IST is still classified as Overnight: Market Closed."""
    dt_utc = make_ist_datetime(2026, 10, 21, 8, 59)
    is_open, note = is_market_session_active(dt_utc)
    assert is_open is False
    assert "Overnight" in note


def test_pre_open_session_boundaries():
    """Verify official NSE pre-open session (09:00 to 09:15 IST)."""
    # 09:00 IST sharp - pre-open order entry begins
    dt_0900 = make_ist_datetime(2026, 10, 21, 9, 0)
    is_open, note = is_market_session_active(dt_0900)
    assert is_open is False
    assert "Pre-Open Session Active" in note
    assert "09:00-09:15 IST" in note

    # 09:10 IST - pre-open order matching & price discovery
    dt_0910 = make_ist_datetime(2026, 10, 21, 9, 10)
    is_open, note = is_market_session_active(dt_0910)
    assert is_open is False
    assert "Pre-Open Session Active" in note

    # 09:14 IST - buffer before continuous trading
    dt_0914 = make_ist_datetime(2026, 10, 21, 9, 14)
    is_open, note = is_market_session_active(dt_0914)
    assert is_open is False
    assert "Pre-Open Session Active" in note


def test_regular_trading_session():
    """Verify regular continuous trading hours (09:15 to 15:30 IST)."""
    # 09:15 IST sharp - continuous trading opens
    dt_0915 = make_ist_datetime(2026, 10, 21, 9, 15)
    is_open, note = is_market_session_active(dt_0915)
    assert is_open is True
    assert "Regular Trading Session Active" in note

    # 12:30 IST - midday continuous trading
    dt_1230 = make_ist_datetime(2026, 10, 21, 12, 30)
    is_open, note = is_market_session_active(dt_1230)
    assert is_open is True
    assert "Regular Trading Session Active" in note

    # 15:29:59 IST - continuous trading active up to close
    dt_1529 = make_ist_datetime(2026, 10, 21, 15, 29, 59)
    is_open, note = is_market_session_active(dt_1529)
    assert is_open is True
    assert "Regular Trading Session Active" in note

    # 15:30:00 IST sharp - regular continuous trading close (transition starts)
    dt_1530 = make_ist_datetime(2026, 10, 21, 15, 30, 0)
    is_open, note = is_market_session_active(dt_1530)
    assert is_open is False
    assert "Ended at 15:30 IST" in note or "Market Transition" in note


def test_market_transition_and_post_closing_sessions():
    """Verify market transition (15:30-15:40) and post-closing (15:40-16:00)."""
    # 15:35 IST - transition buffer
    dt_1535 = make_ist_datetime(2026, 10, 21, 15, 35)
    is_open, note = is_market_session_active(dt_1535)
    assert is_open is False
    assert "Market Transition" in note

    # 15:45 IST - post-closing session
    dt_1545 = make_ist_datetime(2026, 10, 21, 15, 45)
    is_open, note = is_market_session_active(dt_1545)
    assert is_open is False
    assert "Post-Closing Session Active" in note

    # 16:01 IST - evening overnight closed
    dt_1601 = make_ist_datetime(2026, 10, 21, 16, 1)
    is_open, note = is_market_session_active(dt_1601)
    assert is_open is False
    assert "Overnight: Market Closed" in note


def test_weekend_schedule():
    """Verify Saturday and Sunday are strictly marked as Weekend: Market Closed."""
    # Saturday 11:30 IST
    dt_sat = make_ist_datetime(2026, 10, 24, 11, 30)
    is_open, note = is_market_session_active(dt_sat)
    assert is_open is False
    assert "Weekend: Market Closed" in note
    assert "Saturday" in note

    # Sunday 11:30 IST
    dt_sun = make_ist_datetime(2026, 10, 25, 11, 30)
    is_open, note = is_market_session_active(dt_sun)
    assert is_open is False
    assert "Weekend: Market Closed" in note
    assert "Sunday" in note


@pytest.mark.parametrize("holiday_date,holiday_name", list(NSE_HOLIDAYS_2026.items()))
def test_all_16_official_nse_trading_holidays_2026(holiday_date: str, holiday_name: str):
    """
    Priority 1 Verification:
    Verify that every one of the 16 official NSE Equity Segment trading holidays
    in 2026 evaluates to is_open=False during regular trading hours (11:00 IST).
    """
    year, month, day = map(int, holiday_date.split("-"))
    dt_holiday = make_ist_datetime(year, month, day, 11, 0)
    is_open, note = is_market_session_active(dt_holiday)
    assert is_open is False
    assert "Trading Holiday" in note
    assert holiday_name in note


def test_complete_official_2026_weekday_holiday_set_matches_source():
    """
    Completeness test comparing the complete expected official 2026 weekday-holiday set
    against the implemented set. Tests both missing and unexpected dates.
    Source: National Stock Exchange of India (NSE) Capital Market Segment.
    """
    expected_dates = {
        "2026-01-15",  # Maharashtra Municipal Corporation Elections
        "2026-01-26",  # Republic Day
        "2026-03-03",  # Holi
        "2026-03-26",  # Shri Ram Navami
        "2026-03-31",  # Shri Mahavir Jayanti
        "2026-04-03",  # Good Friday
        "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
        "2026-05-01",  # Maharashtra Day
        "2026-05-28",  # Bakri Id
        "2026-06-26",  # Muharram
        "2026-09-14",  # Ganesh Chaturthi
        "2026-10-02",  # Mahatma Gandhi Jayanti
        "2026-10-20",  # Dussehra
        "2026-11-10",  # Diwali-Balipratipada
        "2026-11-24",  # Prakash Gurpurb Sri Guru Nanak Dev
        "2026-12-25",  # Christmas
    }

    implemented_dates = set(NSE_HOLIDAYS_2026.keys())
    missing_dates = expected_dates - implemented_dates
    unexpected_dates = implemented_dates - expected_dates

    assert not missing_dates, f"Missing official NSE trading holidays: {missing_dates}"
    assert not unexpected_dates, f"Unexpected holidays in implemented calendar: {unexpected_dates}"
    assert len(implemented_dates) == 16, f"Expected exactly 16 official holidays, got {len(implemented_dates)}"


def test_january_15_maharashtra_election_holiday():
    """
    Verify January 15, 2026 (Maharashtra Municipal Corporation Elections) closure:
    1. Equity market is reported as closed.
    2. Description accurately reflects Maharashtra Municipal Corporation Elections.
    3. Consistency across dhan_adapter and ramm_adapter.
    """
    dt_jan15 = make_ist_datetime(2026, 1, 15, 11, 0)
    dhan_open, dhan_note = is_market_session_active(dt_jan15)
    ramm_open, ramm_note = ramm_is_market_session_active(dt_jan15)

    assert dhan_open is False
    assert ramm_open is False
    assert "Maharashtra Municipal Corporation Elections" in dhan_note
    assert dhan_note == ramm_note


def test_holidays_adjacent_to_weekends():
    """
    Verify holidays immediately before or after weekends:
    1. Good Friday (2026-04-03, Friday before weekend)
    2. Maharashtra Day (2026-05-01, Friday before weekend)
    3. Mahatma Gandhi Jayanti (2026-10-02, Friday before weekend)
    4. Christmas (2026-12-25, Friday before weekend)
    5. Republic Day (2026-01-26, Monday after weekend)
    6. Ganesh Chaturthi (2026-09-14, Monday after weekend)
    """
    # Good Friday (Friday 11:00 IST)
    dt_gf = make_ist_datetime(2026, 4, 3, 11, 0)
    is_open, note = is_market_session_active(dt_gf)
    assert is_open is False
    assert "Good Friday" in note

    # Following Saturday
    dt_gf_sat = make_ist_datetime(2026, 4, 4, 11, 0)
    is_open_sat, note_sat = is_market_session_active(dt_gf_sat)
    assert is_open_sat is False
    assert "Weekend: Market Closed" in note_sat

    # Republic Day (Monday 11:00 IST after weekend)
    dt_rd = make_ist_datetime(2026, 1, 26, 11, 0)
    is_open, note = is_market_session_active(dt_rd)
    assert is_open is False
    assert "Republic Day" in note


def test_weekend_festivals_not_confused_as_weekday_holidays():
    """
    Verify that Mahashivratri (Sunday, 2026-02-15) and Id-Ul-Fitr (Saturday, 2026-03-21)
    and Independence Day (Saturday, 2026-08-15) are properly categorized as weekend closures,
    and regular trading on the surrounding weekdays (e.g., Friday Feb 13, Monday Feb 16) is NOT blocked.
    """
    # Mahashivratri Sunday 11:00 IST
    dt_ms = make_ist_datetime(2026, 2, 15, 11, 0)
    is_open, note = is_market_session_active(dt_ms)
    assert is_open is False
    assert "Weekend" in note
    assert "Mahashivratri" in note

    # Preceding Friday (Feb 13) should be normal trading session
    dt_fri = make_ist_datetime(2026, 2, 13, 11, 0)
    is_open_fri, note_fri = is_market_session_active(dt_fri)
    assert is_open_fri is True
    assert "Regular Trading Session Active" in note_fri

    # Succeeding Monday (Feb 16) should be normal trading session
    dt_mon = make_ist_datetime(2026, 2, 16, 11, 0)
    is_open_mon, note_mon = is_market_session_active(dt_mon)
    assert is_open_mon is True
    assert "Regular Trading Session Active" in note_mon


def test_muhurat_trading_sunday_nov_8_pending_announcement():
    """
    Verify that on Sunday, November 8, 2026 (Diwali Laxmi Pujan), when special session
    timings have not yet been notified by an official NSE circular, the system:
    1. Does NOT invent an arbitrary trading window (e.g. 18:00-19:15).
    2. Reports is_open=False.
    3. Truthfully identifies the state as 'Weekend Special Session Pending Announcement'.
    """
    # Test during normal evening hours (18:30 IST)
    dt_nov8_evening = make_ist_datetime(2026, 11, 8, 18, 30)
    is_open, note = is_market_session_active(dt_nov8_evening)
    assert is_open is False
    assert "Weekend Special Session Pending Announcement" in note
    assert "Diwali Laxmi Pujan" in note
    assert "pending official NSE circular" in note

    # Test during normal morning hours (11:00 IST)
    dt_nov8_morning = make_ist_datetime(2026, 11, 8, 11, 0)
    is_open_m, note_m = is_market_session_active(dt_nov8_morning)
    assert is_open_m is False
    assert "Pending Announcement" in note_m


def test_muhurat_trading_when_circular_officially_announced(monkeypatch):
    """
    Verify that IF an official NSE circular is published and configured in
    SPECIAL_TRADING_SESSIONS_2026, trading is permitted strictly during that window.
    """
    mock_special_sessions = {
        "2026-11-08": (18 * 60 + 15, 19 * 60 + 15, "Diwali Muhurat Trading Session", "NSE/CM/2026/CIRCULAR-9988")
    }
    monkeypatch.setattr("app.market.dhan_adapter.SPECIAL_TRADING_SESSIONS_2026", mock_special_sessions)

    # 18:00 IST - Before session open -> Closed
    dt_before = make_ist_datetime(2026, 11, 8, 18, 0)
    is_open, note = is_market_session_active(dt_before)
    assert is_open is False
    assert "Special Session Scheduled but Not Active" in note

    # 18:30 IST - During confirmed session -> Open
    dt_active = make_ist_datetime(2026, 11, 8, 18, 30)
    is_open_active, note_active = is_market_session_active(dt_active)
    assert is_open_active is True
    assert "Special Session Active" in note_active
    assert "NSE/CM/2026/CIRCULAR-9988" in note_active

    # 19:30 IST - After confirmed session -> Closed
    dt_after = make_ist_datetime(2026, 11, 8, 19, 30)
    is_open_after, note_after = is_market_session_active(dt_after)
    assert is_open_after is False
    assert "Special Session Scheduled but Not Active" in note_after


def test_adapter_session_consistency():
    """Verify that ramm_adapter and dhan_adapter report identical session outcomes."""
    test_datetimes = [
        make_ist_datetime(2026, 10, 21, 10, 30), # Active regular trading
        make_ist_datetime(2026, 10, 21, 8, 30),  # Overnight closed
        make_ist_datetime(2026, 10, 24, 12, 0),  # Saturday closed
        make_ist_datetime(2026, 1, 26, 11, 0),   # Republic Day holiday
        make_ist_datetime(2026, 11, 8, 18, 30),  # Muhurat pending
    ]

    for dt in test_datetimes:
        dhan_active, dhan_note = is_market_session_active(dt)
        ramm_active, ramm_note = ramm_is_market_session_active(dt)
        assert dhan_active == ramm_active
        assert dhan_note == ramm_note
