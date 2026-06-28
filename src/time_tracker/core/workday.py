"""Workday bounds: explicit clock in/out, with activity inference as fallback.

The user is often in well before their first meeting, so explicit clock-in
(reminder-prompted) is the source of truth; inference is only used when no
manual time was recorded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..config import Config
from ..db import Database
from ..models import Workday, WorkdaySource, utcnow
from .timeutil import local_date_key, local_day_bounds


def _date_key(ts: datetime) -> str:
    return local_date_key(ts)


def clock_in(db: Database, ts: Optional[datetime] = None) -> Workday:
    ts = ts or utcnow()
    wd = db.get_workday(_date_key(ts)) or Workday(date=_date_key(ts))
    wd.clock_in_ts = ts
    wd.source = WorkdaySource.MANUAL
    return db.upsert_workday(wd)


def clock_out(db: Database, ts: Optional[datetime] = None) -> Workday:
    ts = ts or utcnow()
    wd = db.get_workday(_date_key(ts)) or Workday(date=_date_key(ts))
    wd.clock_out_ts = ts
    wd.source = WorkdaySource.MANUAL
    return db.upsert_workday(wd)


def infer_workday(db: Database, config: Config, date: datetime) -> Optional[Workday]:
    """Infer bounds from first/last activity that day (entries + meetings).

    Excluded-color meetings (pink reminders) do not count. Returns ``None`` if
    there was no activity at all.
    """
    day_start_utc, day_end_utc = local_day_bounds(date)
    start_iso = day_start_utc.isoformat()
    end_iso = day_end_utc.isoformat()

    starts: list[datetime] = []
    ends: list[datetime] = []
    for e in db.list_entries(start_iso, end_iso):
        starts.append(e.start_ts)
        ends.append(e.end_ts or e.start_ts)
    for ev in db.list_calendar_events(
        start_iso, end_iso, excluded_color_ids=config.excluded_color_ids
    ):
        starts.append(ev.start_ts)
        ends.append(ev.end_ts)

    if not starts:
        return None
    return Workday(
        date=_date_key(date),
        clock_in_ts=min(starts),
        clock_out_ts=max(ends),
        source=WorkdaySource.INFERRED,
    )


def get_workday(db: Database, config: Config, date: datetime) -> Optional[Workday]:
    """Return the workday, preferring manual times.

    Manual clock in/out wins, but any missing bound (e.g. clocked in but not yet
    out) is supplemented from inferred activity so reports still work mid-day.
    """
    existing = db.get_workday(_date_key(date))
    inferred = infer_workday(db, config, date)
    if existing and (existing.clock_in_ts or existing.clock_out_ts):
        existing.clock_in_ts = existing.clock_in_ts or (
            inferred.clock_in_ts if inferred else None)
        existing.clock_out_ts = existing.clock_out_ts or (
            inferred.clock_out_ts if inferred else None)
        return existing
    return inferred
