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


def test_category_breakdown_folds_meeting_categories(db: Database):
    backfill.fill_gap(db, at(9), at(10), "a", category="dev")  # 1h entry
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="MATS sync", start_ts=at(10), end_ts=at(11),
        color_id="7", category="MATS workplace", category_source="rule"))  # 1h meeting
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="u", title="Uncat", start_ts=at(11), end_ts=at(12), color_id="7"))  # no cat
    totals = reports.category_breakdown(
        db, at(0).isoformat(), at(23).isoformat(), _cfg())
    assert totals["dev"] == 3600
    assert totals["MATS workplace"] == 3600
    assert "Uncat" not in totals  # uncategorized meetings are not counted here


def test_category_breakdown_entries_win_over_meetings(db: Database):
    # A 1h meeting with a 30m entry logged over its second half.
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Stream", start_ts=at(10), end_ts=at(11),
        color_id="7", category="Stream meetings", category_source="rule"))
    backfill.fill_gap(db, at(10, 30), at(11), "did my own thing", category="Personal")
    totals = reports.category_breakdown(
        db, at(0).isoformat(), at(23).isoformat(), _cfg())
    # Entry counts fully; meeting is clipped to the non-overlapping 30m.
    assert totals["Personal"] == 1800
    assert totals["Stream meetings"] == 1800  # not 3600


def test_day_summary_entries_win_partitions_workday(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(17))  # 8h
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Sync", start_ts=at(10), end_ts=at(12), color_id="7"))  # 2h
    backfill.fill_gap(db, at(11), at(13), "focus over the meeting", category="dev")  # 2h, 1h overlaps
    s = reports.day_summary(db, _cfg(), at(12))
    # meeting clipped to 10-11 (1h); focus full 2h; the three partition the workday.
    assert s.meeting_seconds == 3600
    assert s.logged_seconds == 2 * 3600
    assert s.meeting_seconds + s.logged_seconds + s.idle_seconds == s.workday_seconds


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


def test_gather_report_aggregates_day(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(17))
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Sync", start_ts=at(10), end_ts=at(11),
        color_id="7", category="Team meetings", category_source="rule"))
    backfill.fill_gap(db, at(13), at(15), "deep work", category="dev")
    data = reports.gather_report(db, _cfg(), at(12), days=1)
    assert len(data.summaries) == 1
    assert data.summaries[0].workday_seconds == 8 * 3600
    assert data.category_totals["dev"] == 2 * 3600
    assert data.category_totals["Team meetings"] == 3600
    assert "day(s)" in data.period_label


def test_grouped_breakdown_rolls_up_in_config_order():
    groups = [
        {"group": "Meetings", "color": "#2a78d6",
         "categories": ["Team meetings", "Fellow 1:1s"]},
        {"group": "Admin", "color": "#eda100", "categories": ["Admin"]},
    ]
    totals = {"Fellow 1:1s": 3600, "Team meetings": 7200, "Admin": 1800, "Reading": 900}
    grouped = reports.grouped_breakdown(totals, groups)
    assert [b["group"] for b in grouped] == ["Meetings", "Admin", "Other"]
    meetings = grouped[0]
    assert meetings["subtotal"] == 10800
    # Config order preserved (Team meetings before Fellow 1:1s), not by size.
    assert [c for c, _ in meetings["items"]] == ["Team meetings", "Fellow 1:1s"]
    # Unlisted category lands in the trailing Other band.
    assert grouped[-1]["items"] == [("Reading", 900)]


def test_gather_report_week_skips_empty_days(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(17))
    backfill.fill_gap(db, at(10), at(11), "x", category="dev")
    data = reports.gather_report(db, _cfg(), at(0), days=7)
    # Only the one day with a workday produces a summary.
    assert len(data.summaries) == 1
    assert data.category_totals["dev"] == 3600


def test_workday_lengths_trend(db: Database):
    workday.clock_in(db, ts=at(9))
    workday.clock_out(db, ts=at(17))
    lengths = reports.workday_lengths(db, _cfg(), at(0), days=2)
    assert lengths[0] == ("2026-06-28", 8 * 3600)
    assert lengths[1][1] == 0.0  # next day, no data
