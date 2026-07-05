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
from .timeutil import local_date_key, local_day_bounds


@dataclass
class ReportData:
    """Everything a report view needs for a period, rendering-agnostic.

    Produced by :func:`gather_report` so the CLI tables, the matplotlib charts,
    and any future front-end all consume the same aggregated numbers.
    """

    period_label: str
    summaries: list["DaySummary"]        # one per day that has a workday
    category_totals: dict[str, float]    # seconds, entries + categorized meetings
    daily: list[dict]                    # per day: {date, categories:{..}, idle}


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
    db: Database,
    start_iso: str,
    end_iso: str,
    config: Optional[Config] = None,
) -> dict[str, float]:
    """Total seconds per category in the range.

    Counts completed time entries and, when ``config`` is given, categorized
    meetings (non-excluded). Meetings without a category are ignored here so the
    breakdown stays about *how* time was categorized, not raw meeting volume.

    Entries win over meetings: where a logged entry overlaps a meeting, that
    time is attributed to the entry's category only and clipped out of the
    meeting, so no interval is counted twice.
    """
    totals: dict[str, float] = defaultdict(float)
    entries = [e for e in db.list_entries(start_iso, end_iso) if e.end_ts is not None]
    for e in entries:
        totals[e.category or "(uncategorized)"] += e.duration_seconds
    if config is not None:
        entry_intervals = [Interval(e.start_ts, e.end_ts) for e in entries]
        for ev in db.list_calendar_events(
            start_iso, end_iso,
            excluded_color_ids=config.excluded_color_ids,
            excluded_event_types=config.excluded_event_types,
        ):
            if ev.category:
                totals[ev.category] += _seconds_minus(
                    Interval(ev.start_ts, ev.end_ts), entry_intervals
                )
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
            start_iso, end_iso,
            excluded_color_ids=config.excluded_color_ids,
            excluded_event_types=config.excluded_event_types,
        )
    ]
    entries = [
        Interval(e.start_ts, e.end_ts)
        for e in db.list_entries(start_iso, end_iso)
        if e.end_ts is not None
    ]

    # Entries win: a logged entry clips the meeting time it overlaps, so
    # meetings + focus + idle partition the workday instead of overlapping.
    logged_seconds = _clipped_seconds(entries, window)
    meeting_seconds = sum(
        _seconds_minus(m, entries)
        for m in _clip_to_window(meetings, window)
    )
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


OTHER_GROUP = "Other"
OTHER_COLOR = "#888780"


def grouped_breakdown(
    category_totals: dict[str, float], groups: list[dict]
) -> list[dict]:
    """Roll fine category totals into the configured two-level taxonomy.

    Returns an ordered list of
    ``{"group", "color", "subtotal", "items": [(category, seconds), ...]}``,
    groups in config order, subcategories within each sorted by time descending.
    Any category not claimed by a group falls into a trailing ``Other`` band.
    """
    claimed: set[str] = set()
    out: list[dict] = []
    for g in groups:
        items = [
            (c, category_totals[c])
            for c in g.get("categories", [])
            if category_totals.get(c)
        ]
        claimed.update(g.get("categories", []))
        if not items:
            continue
        # items already follow the config order of g["categories"].
        out.append({
            "group": g["group"],
            "color": g.get("color", OTHER_COLOR),
            "subtotal": sum(v for _, v in items),
            "items": items,
        })
    leftover = [(c, v) for c, v in category_totals.items() if c not in claimed]
    if leftover:
        leftover.sort(key=lambda kv: -kv[1])
        out.append({
            "group": OTHER_GROUP,
            "color": OTHER_COLOR,
            "subtotal": sum(v for _, v in leftover),
            "items": leftover,
        })
    return out


def gather_report(
    db: Database, config: Config, start: datetime, days: int
) -> ReportData:
    """Aggregate per-day summaries and category totals for ``days`` from ``start``.

    Matplotlib-free and pure so the numbers are testable independently of any
    chart layer. Mirrors what the CLI ``report`` command previously computed
    inline: ``day_summary`` per day plus ``category_breakdown`` accumulated
    across the period.
    """
    summaries: list[DaySummary] = []
    category_totals: dict[str, float] = defaultdict(float)
    daily: list[dict] = []
    for i in range(days):
        d = start + timedelta(days=i)
        day_start, day_end = local_day_bounds(d)
        s = day_summary(db, config, d)
        day_cats = category_breakdown(
            db, day_start.isoformat(), day_end.isoformat(), config
        )
        for k, v in day_cats.items():
            category_totals[k] += v
        if s is not None:
            summaries.append(s)
            daily.append({"date": s.date, "categories": day_cats, "idle": s.idle_seconds})
    return ReportData(
        period_label=f"last {days} day(s)",
        summaries=summaries,
        category_totals=dict(category_totals),
        daily=daily,
    )


def _clipped_seconds(intervals: list[Interval], window: Interval) -> float:
    """Total seconds of intervals inside window, double-counting removed."""
    total = 0.0
    for span in merge_intervals(intervals):
        s = max(span.start, window.start)
        e = min(span.end, window.end)
        if e > s:
            total += (e - s).total_seconds()
    return total


def _clip_to_window(intervals: list[Interval], window: Interval) -> list[Interval]:
    """Merged intervals clipped to ``window`` (drops anything fully outside)."""
    out: list[Interval] = []
    for span in merge_intervals(intervals):
        s = max(span.start, window.start)
        e = min(span.end, window.end)
        if e > s:
            out.append(Interval(s, e))
    return out


def _seconds_minus(base: Interval, minus: list[Interval]) -> float:
    """Seconds of ``base`` not covered by any ``minus`` interval.

    Reuses ``find_gaps`` (which merges + clips ``minus`` to ``base``) so the
    'entries win over meetings' clipping shares one interval implementation.
    """
    return sum(g.seconds for g in find_gaps(base, minus, min_seconds=0))
