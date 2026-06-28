"""Retrospective backfill: fill the gaps in a day's timeline.

Given a day's existing entries plus (non-excluded) meetings, compute the
uncovered spans and let the user log what they were doing. This is the
lowest-in-the-moment-friction capture path.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from ..config import Config
from ..db import Database
from ..models import Source, TimeEntry, utcnow
from .timeline import Interval, find_gaps, overlaps
from .timeutil import parse_hhmm_on


class OverlapError(RuntimeError):
    """Raised when a backfilled entry would overlap existing tracked time."""


def _day_window(date: datetime, config: Config) -> Interval:
    """The work-hours window (local time) to consider for gaps, as UTC bounds."""
    return Interval(
        parse_hhmm_on(date, config.work_hours_start),
        parse_hhmm_on(date, config.work_hours_end),
    )


def _busy_intervals(
    db: Database, window: Interval, config: Config
) -> list[Interval]:
    start_iso, end_iso = window.start.isoformat(), window.end.isoformat()
    busy = [
        Interval(e.start_ts, e.end_ts)
        for e in db.list_entries(start_iso, end_iso)
        if e.end_ts is not None
    ]
    busy += [
        Interval(ev.start_ts, ev.end_ts)
        for ev in db.list_calendar_events(
            start_iso, end_iso,
            excluded_color_ids=config.excluded_color_ids,
            excluded_event_types=config.excluded_event_types,
        )
    ]
    return busy


def find_day_gaps(
    db: Database,
    config: Config,
    date: Optional[datetime] = None,
    min_minutes: int = 5,
) -> list[Interval]:
    """Uncovered spans in the day's work window (meetings + entries are busy)."""
    window = _day_window(date or utcnow(), config)
    busy = _busy_intervals(db, window, config)
    return find_gaps(window, busy, min_seconds=min_minutes * 60)


def fill_gap(
    db: Database,
    start: datetime,
    end: datetime,
    description: str,
    category: Optional[str] = None,
    project: Optional[str] = None,
) -> TimeEntry:
    """Create a backfill entry, rejecting overlaps with existing tracked time."""
    if end <= start:
        raise ValueError("End time must be after the start time.")
    new = Interval(start, end)
    existing = [
        Interval(e.start_ts, e.end_ts)
        for e in db.list_entries()
        if e.end_ts is not None
    ]
    if any(overlaps(new, e) for e in existing):
        raise OverlapError("Backfill span overlaps an existing entry.")
    entry = TimeEntry(
        start_ts=start,
        end_ts=end,
        category=category,
        project=project,
        description=description,
        source=Source.BACKFILL,
    )
    return db.create_entry(entry)
