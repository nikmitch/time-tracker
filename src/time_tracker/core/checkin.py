"""Periodic check-in capture.

A check-in answers "what are you working on right now?" and logs the span from
the end of your last logged activity (today) up to now. This samples your time
with very low effort and naturally backfills the interval since the previous
check-in.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from ..db import Database
from ..models import Source, TimeEntry, utcnow


def _day_bounds_iso(now: datetime) -> tuple[str, str]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start.isoformat(), (day_start + timedelta(days=1)).isoformat()


def last_activity_end(db: Database, now: datetime) -> Optional[datetime]:
    """End of the most recent completed entry earlier today, if any."""
    start_iso, end_iso = _day_bounds_iso(now)
    today = [e for e in db.list_entries(start_iso, end_iso) if e.end_ts is not None]
    if not today:
        return None
    return max(e.end_ts for e in today)


def record_checkin(
    db: Database,
    description: str,
    category: Optional[str] = None,
    project: Optional[str] = None,
    now: Optional[datetime] = None,
    max_lookback_minutes: int = 120,
) -> TimeEntry:
    """Log an entry spanning [since, now].

    ``since`` is the end of the last activity today, capped to
    ``max_lookback_minutes`` so a check-in after a long break doesn't claim
    hours of untracked time.
    """
    now = now or utcnow()
    since = last_activity_end(db, now)
    floor = now - timedelta(minutes=max_lookback_minutes)
    if since is None or since < floor:
        since = floor
    if since >= now:
        since = now - timedelta(minutes=1)
    entry = TimeEntry(
        start_ts=since,
        end_ts=now,
        category=category,
        project=project,
        description=description,
        source=Source.CHECKIN,
    )
    return db.create_entry(entry)
