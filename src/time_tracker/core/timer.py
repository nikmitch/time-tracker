"""Live timer capture: start/stop a running entry.

Mirrors stint-tracker's core interaction, but writes into the shared
``TimeEntry`` timeline so the data is uniform with every other capture path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..db import Database
from ..models import Source, TimeEntry, utcnow


class TimerError(RuntimeError):
    """Raised on invalid timer transitions (e.g. double start)."""


def start_timer(
    db: Database,
    category: Optional[str] = None,
    description: Optional[str] = None,
    start_ts: Optional[datetime] = None,
) -> TimeEntry:
    """Open a new running entry. Errors if one is already running."""
    if db.get_running_entry() is not None:
        raise TimerError("A timer is already running; stop it before starting another.")
    entry = TimeEntry(
        start_ts=start_ts or utcnow(),
        end_ts=None,
        category=category,
        description=description,
        source=Source.TIMER,
    )
    return db.create_entry(entry)


def stop_timer(db: Database, end_ts: Optional[datetime] = None) -> TimeEntry:
    """Close the currently running entry. Errors if none is running."""
    running = db.get_running_entry()
    if running is None:
        raise TimerError("No timer is currently running.")
    end = end_ts or utcnow()
    if end <= running.start_ts:
        raise TimerError("End time must be after the start time.")
    running.end_ts = end
    return db.update_entry(running)
