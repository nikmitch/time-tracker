"""Domain models for the canonical time-entry timeline.

All capture paths (timer, check-in, backfill, calendar import) produce the same
``TimeEntry`` shape, distinguished by ``source``. Timestamps are stored as
timezone-aware UTC ``datetime`` objects in Python and as ISO-8601 strings in
SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Source(str, Enum):
    """Where a time entry originated."""

    TIMER = "timer"
    CHECKIN = "checkin"
    BACKFILL = "backfill"
    CALENDAR = "calendar"


class WorkdaySource(str, Enum):
    """How a workday's clock in/out times were determined."""

    MANUAL = "manual"
    INFERRED = "inferred"


def utcnow() -> datetime:
    """Timezone-aware current UTC time (avoids naive-datetime ambiguity)."""
    return datetime.now(timezone.utc)


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime to an ISO-8601 string (assumed/forced UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def from_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string back into a timezone-aware UTC datetime."""
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class TimeEntry:
    """A single span on the work timeline.

    ``end_ts`` is ``None`` while a timer is still running.
    """

    start_ts: datetime
    end_ts: Optional[datetime] = None
    category: Optional[str] = None
    description: Optional[str] = None
    source: Source = Source.TIMER
    calendar_event_id: Optional[int] = None
    id: Optional[int] = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    @property
    def is_running(self) -> bool:
        return self.end_ts is None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.end_ts is None:
            return None
        return (self.end_ts - self.start_ts).total_seconds()


@dataclass
class CalendarEvent:
    """A cached Google Calendar event."""

    gcal_id: str
    title: str
    start_ts: datetime
    end_ts: datetime
    attendees_count: int = 0
    color_id: Optional[str] = None
    event_type: Optional[str] = None
    category: Optional[str] = None
    # "rule" (auto-derived, re-applied on sync) or "manual" (never overwritten).
    category_source: Optional[str] = None
    id: Optional[int] = None
    last_synced: datetime = field(default_factory=utcnow)


@dataclass
class Workday:
    """The 'at work' window for a given calendar date (one row per date)."""

    date: str  # ISO date, e.g. "2026-06-28"
    clock_in_ts: Optional[datetime] = None
    clock_out_ts: Optional[datetime] = None
    source: WorkdaySource = WorkdaySource.MANUAL
    id: Optional[int] = None
