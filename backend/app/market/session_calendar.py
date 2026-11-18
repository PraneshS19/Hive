"""
SYNQ — NSE Market Session Calendar & Trading Schedule Service
Authoritative exchange session determination for Indian National Stock Exchange (NSE).
Timezone: Asia/Kolkata (IST = UTC + 5:30).

Handles:
- Regular continuous trading hours (Monday-Friday, 09:15 to 15:30 IST).
- Pre-open session (09:00 to 09:15 IST).
- Market transition (15:30 to 15:40 IST).
- Post-closing session (15:40 to 16:00 IST).
- Overnight sessions (before 09:00 or after 16:00 IST).
- Weekends (Saturday & Sunday).
- Official declared NSE trading holidays (Calendar Year 2026).
- Special announced sessions (e.g. Muhurat Trading).
- Calculation of last completed trading session date.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

# Indian Standard Time (IST) Offset: UTC + 5:30
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

# Official 16 Weekday Trading Holidays for Equity Segment in 2026
# (15 Annual Gazetted Holidays + Maharashtra Municipal Corporation Election Holiday on Jan 15)
# Reference: National Stock Exchange of India (NSE) Capital Market / Equity Segment
NSE_HOLIDAYS_2026: dict[str, str] = {
    "2026-01-15": "Maharashtra Municipal Corporation Elections",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}

# Recognized holidays/festivals that fall on Saturdays or Sundays in 2026
NSE_WEEKEND_HOLIDAYS_2026: dict[str, str] = {
    "2026-02-15": "Mahashivratri (Sunday)",
    "2026-03-21": "Id-Ul-Fitr (Ramadan Eid) (Saturday)",
    "2026-08-15": "Independence Day (Saturday)",
    "2026-11-08": "Diwali Laxmi Pujan (Sunday, Muhurat Trading)",
}

# Officially announced special trading sessions with confirmed circular timings
# Format: date_str -> (start_minute_ist, end_minute_ist, session_label, circular_reference)
SPECIAL_TRADING_SESSIONS_2026: dict[str, tuple[int, int, str, str]] = {}


def _get_special_trading_sessions() -> dict[str, tuple[int, int, str, str]]:
    try:
        import sys
        da = sys.modules.get("app.market.dhan_adapter")
        if da and hasattr(da, "SPECIAL_TRADING_SESSIONS_2026") and da.SPECIAL_TRADING_SESSIONS_2026:
            return da.SPECIAL_TRADING_SESSIONS_2026
    except (AttributeError, ImportError):
        pass
    return SPECIAL_TRADING_SESSIONS_2026


def _format_session_info(info: dict[str, Any]) -> dict[str, Any]:
    info["session_start_ist"] = info.get("session_start_ist", "09:15:00")
    info["session_end_ist"] = info.get("session_end_ist", "15:30:00")
    info["trading_day_status"] = info.get("trading_day_status", info.get("market_status", "CLOSED"))
    return info


def get_market_session_info(dt: datetime | None = None) -> dict[str, Any]:
    """
    Returns structured, comprehensive market status and session details in Asia/Kolkata (IST).
    Accounts for regular trading sessions, pre-open, post-closing, weekends, declared holidays,
    and special trading sessions.
    """
    check_time = dt or datetime.now(UTC)
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=UTC)
    ist_time = check_time.astimezone(IST_OFFSET)
    date_str = ist_time.strftime("%Y-%m-%d")
    current_minute = ist_time.hour * 60 + ist_time.minute
    day_name = ist_time.strftime("%A")

    active_special_sessions = _get_special_trading_sessions()

    # 1. Special Trading Sessions check (officially confirmed timings)
    if date_str in active_special_sessions:
        start_m, end_m, session_label, circular_ref = active_special_sessions[date_str]
        if start_m <= current_minute <= end_m:
            return _format_session_info({
                "is_open": True,
                "market_status": "SPECIAL_SESSION",
                "session_note": f"Special Session Active: {session_label} ({ist_time.strftime('%H:%M')} IST, Ref: {circular_ref})",
                "exchange": "NSE",
                "timezone": "Asia/Kolkata",
                "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
                "date_str": date_str,
                "is_weekend": ist_time.weekday() in (5, 6),
                "is_holiday": False,
                "holiday_name": None,
                "session_phase": "CONTINUOUS",
            })
        else:
            return _format_session_info({
                "is_open": False,
                "market_status": "CLOSED",
                "session_note": f"Special Session Scheduled but Not Active: {session_label} (Hours: {start_m//60:02d}:{start_m%60:02d}-{end_m//60:02d}:{end_m%60:02d} IST; Current: {ist_time.strftime('%H:%M')} IST)",
                "exchange": "NSE",
                "timezone": "Asia/Kolkata",
                "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
                "date_str": date_str,
                "is_weekend": ist_time.weekday() in (5, 6),
                "is_holiday": False,
                "holiday_name": None,
                "session_phase": "OUTSIDE_HOURS",
            })

    # 2. Designated Special Session Dates pending official circular notification
    if date_str == "2026-11-08":
        return _format_session_info({
            "is_open": False,
            "market_status": "CLOSED",
            "session_note": (
                f"Weekend Special Session Pending Announcement: Diwali Laxmi Pujan "
                f"(Sunday; Muhurat Trading timings pending official NSE circular notification; exchange currently closed; Current: {ist_time.strftime('%H:%M')} IST)"
            ),
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": True,
            "is_holiday": True,
            "holiday_name": "Diwali Laxmi Pujan (Sunday, Muhurat Trading)",
            "session_phase": "PENDING_SPECIAL_ANNOUNCEMENT",
        })

    # 3. Official Declared Weekday Trading Holiday check
    if date_str in NSE_HOLIDAYS_2026:
        holiday_name = NSE_HOLIDAYS_2026[date_str]
        return _format_session_info({
            "is_open": False,
            "market_status": "HOLIDAY",
            "session_note": f"Trading Holiday: Market Closed for {holiday_name}",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": True,
            "holiday_name": holiday_name,
            "session_phase": "HOLIDAY",
        })

    # 4. Weekend check (0 = Monday, 4 = Friday, 5 = Saturday, 6 = Sunday)
    if ist_time.weekday() in (5, 6):
        wknd_holiday = NSE_WEEKEND_HOLIDAYS_2026.get(date_str)
        if wknd_holiday:
            note = f"Weekend: Market Closed ({day_name}, {wknd_holiday})"
        else:
            note = f"Weekend: Market Closed ({day_name})"
        return _format_session_info({
            "is_open": False,
            "market_status": "WEEKEND",
            "session_note": note,
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": True,
            "is_holiday": bool(wknd_holiday),
            "holiday_name": wknd_holiday,
            "session_phase": "WEEKEND",
        })

    # 5. Regular trading day session breakdown according to official NSE schedule (IST)
    current_sec = ist_time.hour * 3600 + ist_time.minute * 60 + ist_time.second
    pre_open_start_sec = 9 * 3600             # 09:00:00 IST
    regular_open_sec = 9 * 3600 + 15 * 60     # 09:15:00 IST
    regular_close_sec = 15 * 3600 + 30 * 60   # 15:30:00 IST
    post_close_start_sec = 15 * 3600 + 40 * 60 # 15:40:00 IST
    post_close_end_sec = 16 * 3600            # 16:00:00 IST

    if current_sec < pre_open_start_sec:
        return _format_session_info({
            "is_open": False,
            "market_status": "CLOSED",
            "session_note": f"Overnight: Market Closed (Pre-Open starts at 09:00 IST, Regular at 09:15 IST; Current: {ist_time.strftime('%H:%M')} IST)",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": None,
            "session_phase": "OVERNIGHT_PRE",
        })
    elif pre_open_start_sec <= current_sec < regular_open_sec:
        return _format_session_info({
            "is_open": False,
            "market_status": "PRE_OPEN",
            "session_note": f"Pre-Open Session Active (09:00-09:15 IST; Order collection & price discovery; Regular trading opens at 09:15 IST; Current: {ist_time.strftime('%H:%M')} IST)",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": None,
            "session_phase": "PRE_OPEN",
        })
    elif regular_open_sec <= current_sec < regular_close_sec:
        return _format_session_info({
            "is_open": True,
            "market_status": "OPEN",
            "session_note": f"Regular Trading Session Active ({ist_time.strftime('%H:%M')} IST)",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": None,
            "session_phase": "REGULAR",
        })
    elif regular_close_sec <= current_sec < post_close_start_sec:
        return _format_session_info({
            "is_open": False,
            "market_status": "CLOSED",
            "session_note": f"Market Transition: Regular Trading Ended at 15:30 IST (Post-closing session starts at 15:40 IST; Current: {ist_time.strftime('%H:%M')} IST)",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": None,
            "session_phase": "TRANSITION",
        })
    elif post_close_start_sec <= current_sec <= post_close_end_sec:
        return _format_session_info({
            "is_open": False,
            "market_status": "POST_CLOSE",
            "session_note": f"Post-Closing Session Active (15:40-16:00 IST; Regular trading closed; Current: {ist_time.strftime('%H:%M')} IST)",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": None,
            "session_phase": "POST_CLOSE",
        })
    else:
        return _format_session_info({
            "is_open": False,
            "market_status": "CLOSED",
            "session_note": f"Overnight: Market Closed (Closed at 16:00 IST; Next session pre-open at 09:00 IST; Current: {ist_time.strftime('%H:%M')} IST)",
            "exchange": "NSE",
            "timezone": "Asia/Kolkata",
            "current_time_ist": ist_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "date_str": date_str,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": None,
            "session_phase": "OVERNIGHT_POST",
        })


def is_market_session_active(dt: datetime | None = None) -> tuple[bool, str]:
    """
    Evaluates whether the NSE regular or special trading session is active in Asia/Kolkata (IST).
    Returns (is_open: bool, session_note: str) matching existing contract and test assertions.
    Respects test monkeypatching if app.market.dhan_adapter is monkeypatched.
    """
    try:
        import sys
        da = sys.modules.get("app.market.dhan_adapter")
        if da and hasattr(da, "is_market_session_active") and da.is_market_session_active is not is_market_session_active:
            res = da.is_market_session_active(dt)
            if isinstance(res, tuple):
                return res
            return bool(res), "Simulated session"
    except (TypeError, ValueError):
        pass
    info = get_market_session_info(dt)
    return info["is_open"], info["session_note"]


def get_last_completed_trading_session_date(dt: datetime | None = None) -> str:
    """
    Determines the YYYY-MM-DD date of the most recent completed regular trading session.
    - If currently on a trading day after regular close (>= 15:30 IST): today.
    - If currently on a trading day before or during regular session (< 15:30 IST): previous trading day.
    - If on a weekend or holiday: previous completed trading day.
    """
    check_time = dt or datetime.now(UTC)
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=UTC)
    ist_time = check_time.astimezone(IST_OFFSET)
    current_minute = ist_time.hour * 60 + ist_time.minute

    # If it's a weekday and past 15:30 IST, and today is not a holiday, today is completed!
    curr_date_str = ist_time.strftime("%Y-%m-%d")
    is_today_holiday = curr_date_str in NSE_HOLIDAYS_2026
    is_today_weekend = ist_time.weekday() in (5, 6)

    if not is_today_weekend and not is_today_holiday and current_minute >= 15 * 60 + 30:
        return curr_date_str

    # Otherwise step backwards day by day to find the most recent non-weekend, non-holiday trading day
    candidate = ist_time - timedelta(days=1)
    while True:
        cand_str = candidate.strftime("%Y-%m-%d")
        if candidate.weekday() not in (5, 6) and cand_str not in NSE_HOLIDAYS_2026:
            return cand_str
        candidate -= timedelta(days=1)
