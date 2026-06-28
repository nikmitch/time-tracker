"""Analysis over the timeline: where time goes, and how fragmented it is.

All reports derive idle/gaps rather than storing them:
    idle = workday window − meetings − logged entries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ..config import Config
from ..db import Database
from . import workday
from .timeline import Interval, find_gaps, merge_intervals
from .timeutil import local_date_key


@dataclass
class DaySummary:
    date: str
    workday_seconds: float
    meeting_seconds: float
    logged_seconds: float
    idle_seconds: float
    gap_count: int

    @property
    def fragmentation(self) -> float:
        """Gaps per hour of workday — higher means more scattered free time."""
        hours = self.workday_seconds / 3600
        return self.gap_count / hours if hours else 0.0


def category_breakdown(
    db: Database, start_iso: str, end_iso: str
) -> dict[str, float]:
    """Total seconds per category for completed entries in the range."""
    totals: dict[str, float] = defaultdict(float)
    for e in db.list_entries(start_iso, end_iso):
        if e.end_ts is None:
            continue
        totals[e.category or "(uncategorized)"] += e.duration_seconds
    return dict(totals)


def day_summary(
    db: Database,
    config: Config,
    date: datetime,
    min_gap_minutes: int = 5,
) -> Optional[DaySummary]:
    """Meeting vs focus vs idle breakdown for a single day."""
    wd = workday.get_workday(db, config, date)
    if wd is None or wd.clock_in_ts is None:
        return None
    end = wd.clock_out_ts or wd.clock_in_ts
    window = Interval(wd.clock_in_ts, end)
    if window.seconds <= 0:
        return None

    start_iso, end_iso = window.start.isoformat(), window.end.isoformat()
    meetings = [
        Interval(ev.start_ts, ev.end_ts)
        for ev in db.list_calendar_events(
            start_iso, end_iso, excluded_color_ids=config.excluded_color_ids
        )
    ]
    entries = [
        Interval(e.start_ts, e.end_ts)
        for e in db.list_entries(start_iso, end_iso)
        if e.end_ts is not None
    ]

    meeting_seconds = _clipped_seconds(meetings, window)
    logged_seconds = _clipped_seconds(entries, window)
    gaps = find_gaps(window, meetings + entries, min_seconds=min_gap_minutes * 60)
    idle_seconds = sum(g.seconds for g in gaps)

    return DaySummary(
        date=wd.date,
        workday_seconds=window.seconds,
        meeting_seconds=meeting_seconds,
        logged_seconds=logged_seconds,
        idle_seconds=idle_seconds,
        gap_count=len(gaps),
    )


def workday_lengths(
    db: Database, config: Config, start: datetime, days: int
) -> list[tuple[str, float]]:
    """(date, workday_seconds) for ``days`` consecutive days from ``start``."""
    out: list[tuple[str, float]] = []
    for i in range(days):
        d = start + timedelta(days=i)
        wd = workday.get_workday(db, config, d)
        if wd and wd.clock_in_ts and wd.clock_out_ts:
            out.append((wd.date, (wd.clock_out_ts - wd.clock_in_ts).total_seconds()))
        else:
            out.append((local_date_key(d), 0.0))
    return out


def _clipped_seconds(intervals: list[Interval], window: Interval) -> float:
    """Total seconds of intervals inside window, double-counting removed."""
    total = 0.0
    for span in merge_intervals(intervals):
        s = max(span.start, window.start)
        e = min(span.end, window.end)
        if e > s:
            total += (e - s).total_seconds()
    return total
