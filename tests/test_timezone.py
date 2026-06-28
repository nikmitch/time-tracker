"""Verify day grouping / windows use *local* time, not UTC."""

import os
import time
from datetime import datetime, timezone

import pytest

from time_tracker.config import Config
from time_tracker.core import backfill, timeutil, workday
from time_tracker.db import Database


@pytest.fixture
def ny_tz():
    """Pin local zone to America/New_York (UTC-4 in summer) for this test."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def test_local_date_key_uses_local_zone(ny_tz):
    # 2026-06-28 01:00 UTC is still 2026-06-27 21:00 in New York.
    dt = datetime(2026, 6, 28, 1, 0, tzinfo=timezone.utc)
    assert timeutil.local_date_key(dt) == "2026-06-27"


def test_local_day_bounds_offset(ny_tz):
    dt = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    start, end = timeutil.local_day_bounds(dt)
    # Local midnight 2026-06-28 EDT == 04:00 UTC.
    assert start == datetime(2026, 6, 28, 4, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 29, 4, 0, tzinfo=timezone.utc)


def test_parse_hhmm_on_is_local(ny_tz):
    base = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    # 09:30 local (EDT) == 13:30 UTC.
    assert timeutil.parse_hhmm_on(base, "09:30") == datetime(
        2026, 6, 28, 13, 30, tzinfo=timezone.utc)


def test_workday_grouped_by_local_date(ny_tz):
    db = Database(":memory:")
    # An entry at 02:00 UTC on the 28th is 22:00 on the 27th locally.
    from time_tracker.core import timer
    timer.start_timer(db, start_ts=datetime(2026, 6, 28, 2, 0, tzinfo=timezone.utc))
    timer.stop_timer(db, end_ts=datetime(2026, 6, 28, 3, 0, tzinfo=timezone.utc))
    wd = workday.get_workday(db, Config(), datetime(2026, 6, 27, 23, 0, tzinfo=timezone.utc))
    assert wd is not None
    assert wd.date == "2026-06-27"
    db.close()


def test_backfill_window_local(ny_tz):
    db = Database(":memory:")
    cfg = Config(work_hours_start="08:00", work_hours_end="18:00")
    # No activity -> the whole local work window is one gap.
    gaps = backfill.find_day_gaps(db, cfg, datetime(2026, 6, 28, 15, 0, tzinfo=timezone.utc))
    assert len(gaps) == 1
    # Window starts at 08:00 EDT == 12:00 UTC.
    assert gaps[0].start == datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    db.close()
