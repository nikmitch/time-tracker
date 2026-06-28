"""Interval arithmetic shared by the capture and analysis layers.

An ``Interval`` is a half-open ``[start, end)`` span of timezone-aware
datetimes. These helpers underpin gap detection (backfill), overlap checks,
and idle/fragmentation reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple


class Interval(NamedTuple):
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def overlaps(a: Interval, b: Interval) -> bool:
    """True if two half-open intervals share any time."""
    return a.start < b.end and b.start < a.end


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    """Sort and coalesce overlapping/adjacent intervals."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda i: i.start)
    merged = [ordered[0]]
    for cur in ordered[1:]:
        last = merged[-1]
        if cur.start <= last.end:  # overlapping or touching
            merged[-1] = Interval(last.start, max(last.end, cur.end))
        else:
            merged.append(cur)
    return merged


def find_gaps(
    window: Interval, busy: list[Interval], min_seconds: float = 0
) -> list[Interval]:
    """Return uncovered spans within ``window`` given ``busy`` intervals.

    Busy intervals are merged first; gaps shorter than ``min_seconds`` are
    dropped. Busy time outside the window is clipped.
    """
    gaps: list[Interval] = []
    cursor = window.start
    for span in merge_intervals(busy):
        if span.end <= window.start or span.start >= window.end:
            continue
        s = max(span.start, window.start)
        if s > cursor:
            gaps.append(Interval(cursor, s))
        cursor = max(cursor, min(span.end, window.end))
    if cursor < window.end:
        gaps.append(Interval(cursor, window.end))
    return [g for g in gaps if g.seconds >= min_seconds]
