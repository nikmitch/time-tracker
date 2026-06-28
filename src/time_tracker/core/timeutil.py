"""Local-timezone helpers.

Everything is stored in UTC, but "what day is it" and "the work-hours window"
are human concepts that must be computed in the user's *local* time. These
helpers convert between the two in one place so the rest of the code never does
ad-hoc timezone math.

The local zone is the system local zone (respects the ``TZ`` env var on Unix),
so tests can pin it deterministically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def local_tz():
    """The system's current local timezone."""
    return datetime.now(timezone.utc).astimezone().tzinfo


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(local_tz())


def local_date_key(dt: datetime) -> str:
    """ISO date (YYYY-MM-DD) of ``dt`` *in local time*."""
    return dt.astimezone(local_tz()).date().isoformat()


def local_day_bounds(dt: datetime) -> tuple[datetime, datetime]:
    """UTC [start, end) covering the local calendar day containing ``dt``."""
    loc = dt.astimezone(local_tz())
    start = loc.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def local_time_on(dt: datetime, hour: int, minute: int) -> datetime:
    """UTC instant for ``hour:minute`` local time on ``dt``'s local date."""
    loc = dt.astimezone(local_tz())
    return loc.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ).astimezone(timezone.utc)


def parse_hhmm_on(dt: datetime, hhmm: str) -> datetime:
    """Parse ``"HH:MM"`` local time on ``dt``'s local date -> UTC instant."""
    hour, minute = (int(x) for x in hhmm.split(":"))
    return local_time_on(dt, hour, minute)
