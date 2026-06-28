from datetime import datetime, timezone

from time_tracker.config import Config
from time_tracker.core import backfill, reports, timer, workday
from time_tracker.db import Database
from time_tracker.models import CalendarEvent

UTC = timezone.utc


def at(h, m=0):
    return datetime(2026, 6, 28, h, m, tzinfo=UTC)


def _cfg():
    return Config(excluded_color_ids=["4"])


def test_category_breakdown(db: Database):
    backfill.fill_gap(db, at(9), at(10), "a", category="dev")
    backfill.fill_gap(db, at(10), at(11), "b", category="dev")
    backfill.fill_gap(db, at(11), at(12), "c", category="email")
    totals = reports.category_breakdown(db, at(0).isoformat(), at(23).isoformat())
    assert totals["dev"] == 7200
    assert totals["email"] == 3600


def test_uncategorized_bucket(db: Database):
    backfill.fill_gap(db, at(9), at(10), "x")
    totals = reports.category_breakdown(db, at(0).isoformat(), at(23).isoformat())
    assert totals["(uncategorized)"] == 3600


def test_day_summary_meeting_focus_idle(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(17))  # 8h workday
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Sync", start_ts=at(10), end_ts=at(11), color_id="7"))  # 1h
    backfill.fill_gap(db, at(13), at(15), "deep work", category="dev")  # 2h logged

    s = reports.day_summary(db, _cfg(), at(12))
    assert s.workday_seconds == 8 * 3600
    assert s.meeting_seconds == 3600
    assert s.logged_seconds == 2 * 3600
    # idle = 8h - 1h meeting - 2h logged = 5h
    assert s.idle_seconds == 5 * 3600


def test_day_summary_pink_meeting_excluded(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(11))
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="p", title="Reminder", start_ts=at(9), end_ts=at(10), color_id="4"))
    s = reports.day_summary(db, _cfg(), at(10))
    assert s.meeting_seconds == 0
    assert s.idle_seconds == 2 * 3600


def test_day_summary_none_without_workday(db: Database):
    assert reports.day_summary(db, _cfg(), at(12)) is None


def test_fragmentation_metric(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(11))  # 2h
    # one meeting splits the day into two gaps
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Sync", start_ts=at(10), end_ts=at(10, 30), color_id="7"))
    s = reports.day_summary(db, _cfg(), at(10))
    assert s.gap_count == 2  # 9-10 and 10:30-11
    assert s.fragmentation == 1.0  # 2 gaps / 2 hours


def test_workday_lengths_trend(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(17))
    lengths = reports.workday_lengths(db, _cfg(), at(0), days=2)
    assert lengths[0] == ("2026-06-28", 8 * 3600)
    assert lengths[1][1] == 0.0  # next day, no data
