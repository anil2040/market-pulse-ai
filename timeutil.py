# ============================================================
# timeutil.py -- Boise (Mountain) time that follows daylight saving
# Mean Reversion Macro Insights
# ============================================================
#
# WHY THIS EXISTS:
#   main.py and html_builder.py used a hard-coded UTC-6 offset, which
#   is only right in summer. This module returns the correct Boise
#   time all year, switching to UTC-7 on the first Sunday of November
#   and back to UTC-6 on the second Sunday of March by itself.
#
# PUBLIC FUNCTIONS:
#   now_mt()        -> timezone-aware datetime in Boise time
#   to_mt(dt)       -> convert any aware datetime to Boise time
#   mt_label(dt)    -> "MDT" or "MST" for that moment
#
# HOW IT WORKS:
#   1. Uses Python's built-in zoneinfo "America/Boise" when available
#      (always on GitHub Actions).
#   2. On a Windows PC without the tzdata package, falls back to the
#      US daylight saving rule written out below, so local test runs
#      never crash.
# ============================================================

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _ZONE = ZoneInfo("America/Boise")
except Exception:          # tzdata missing (typical on Windows)
    _ZONE = None


def _nth_sunday(year, month, n):
    """Date of the nth Sunday of a month (n=1 is the first Sunday)."""
    first = datetime(year, month, 1)
    offset = (6 - first.weekday()) % 7          # days until first Sunday
    return first + timedelta(days=offset + 7 * (n - 1))


def _fallback_offset_hours(dt_utc):
    """US rule: DST from 2nd Sunday of March 09:00 UTC to 1st Sunday of Nov 08:00 UTC."""
    y = dt_utc.year
    start = _nth_sunday(y, 3, 2).replace(hour=9, tzinfo=timezone.utc)
    end   = _nth_sunday(y, 11, 1).replace(hour=8, tzinfo=timezone.utc)
    return -6 if start <= dt_utc < end else -7


def to_mt(dt):
    """Convert an aware datetime to Boise time (naive input is treated as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if _ZONE is not None:
        return dt.astimezone(_ZONE)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.astimezone(timezone(timedelta(hours=_fallback_offset_hours(dt_utc))))


def now_mt():
    """Current time in Boise, aware of daylight saving."""
    return to_mt(datetime.now(timezone.utc))


def mt_label(dt):
    """'MDT' in summer, 'MST' in winter."""
    off = to_mt(dt).utcoffset()
    return "MDT" if off == timedelta(hours=-6) else "MST"
