from datetime import datetime, timedelta, timezone

import pytest

from time_tracker.config import Config
from time_tracker.core import backfill, checkin, timer
from time_tracker.core.timeline import Interval
from time_tracker.db import Database
from time_tracker.models import CalendarEvent, Source

UTC = timezone.utc


def at(h, m=0):
    return datetime(2026, 6, 28, h, m, tzinfo=UTC)


# ----- timer -------------------------------------------------------------

def test_timer_start_creates_open_entry(db: Database):
    e = timer.start_timer(db, category="dev", start_ts=at(9))
    assert e.is_running
    assert db.get_running_entry().id == e.id


def test_timer_stop_closes_entry(db: Database):
    timer.start_timer(db, start_ts=at(9))
    closed = timer.stop_timer(db, end_ts=at(10))
    assert not closed.is_running
    assert closed.duration_seconds == 3600
    assert db.get_running_entry() is None


def test_cannot_start_two_timers(db: Database):
    timer.start_timer(db, start_ts=at(9))
    with pytest.raises(timer.TimerError):
        timer.start_timer(db, start_ts=at(9, 30))


def test_stop_without_running_errors(db: Database):
    with pytest.raises(timer.TimerError):
        timer.stop_timer(db)


def test_stop_before_start_errors(db: Database):
    timer.start_timer(db, start_ts=at(10))
    with pytest.raises(timer.TimerError):
        timer.stop_timer(db, end_ts=at(9))


# ----- check-in ----------------------------------------------------------

def test_checkin_spans_from_last_activity(db: Database):
    timer.start_timer(db, start_ts=at(9))
    timer.stop_timer(db, end_ts=at(9, 30))
    entry = checkin.record_checkin(db, "emails", now=at(10))
    assert entry.source == Source.CHECKIN
    assert entry.start_ts == at(9, 30)
    assert entry.end_ts == at(10)


def test_checkin_caps_lookback(db: Database):
    # No prior activity: should fall back to the lookback floor, not midnight.
    entry = checkin.record_checkin(db, "reading", now=at(10), max_lookback_minutes=60)
    assert entry.start_ts == at(9)
    assert entry.end_ts == at(10)


# ----- backfill ----------------------------------------------------------

def _cfg():
    return Config(work_hours_start="08:00", work_hours_end="18:00", excluded_color_ids=["4"])


def test_find_day_gaps_excludes_pink_and_entries(db: Database):
    # A real meeting and a pink reminder.
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Sync", start_ts=at(10), end_ts=at(11), color_id="7"))
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="p", title="Reminder", start_ts=at(8), end_ts=at(8, 30), color_id="4"))
    # A logged entry.
    timer.start_timer(db, start_ts=at(13))
    timer.stop_timer(db, end_ts=at(14))

    gaps = backfill.find_day_gaps(db, _cfg(), date=at(12))
    # Pink reminder ignored -> 8-10 is a gap; meeting 10-11 busy; 11-13 gap;
    # entry 13-14 busy; 14-18 gap.
    assert Interval(at(8), at(10)) in gaps
    assert Interval(at(11), at(13)) in gaps
    assert Interval(at(14), at(18)) in gaps


def test_fill_gap_creates_backfill_entry(db: Database):
    e = backfill.fill_gap(db, at(11), at(12), "deep work", category="dev")
    assert e.source == Source.BACKFILL
    assert e.duration_seconds == 3600


def test_fill_gap_rejects_overlap(db: Database):
    backfill.fill_gap(db, at(11), at(12), "a")
    with pytest.raises(backfill.OverlapError):
        backfill.fill_gap(db, at(11, 30), at(12, 30), "b")


def test_fill_gap_rejects_inverted_range(db: Database):
    with pytest.raises(ValueError):
        backfill.fill_gap(db, at(12), at(11), "x")
