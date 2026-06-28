import plistlib
from datetime import datetime, timezone

from time_tracker.config import Config
from time_tracker.core import notify, reminders, timer, workday
from time_tracker.db import Database
from time_tracker.models import CalendarEvent, WorkdaySource

UTC = timezone.utc


def at(h, m=0):
    return datetime(2026, 6, 28, h, m, tzinfo=UTC)


def _cfg():
    return Config(excluded_color_ids=["4"])


# ----- clock in/out ------------------------------------------------------

def test_clock_in_out_single_row(db: Database):
    workday.clock_in(db, ts=at(8))
    workday.clock_out(db, ts=at(17))
    wd = db.get_workday("2026-06-28")
    assert wd.clock_in_ts == at(8)
    assert wd.clock_out_ts == at(17)
    assert wd.source == WorkdaySource.MANUAL
    count = db.conn.execute("SELECT COUNT(*) c FROM workday").fetchone()["c"]
    assert count == 1


# ----- inference ---------------------------------------------------------

def test_infer_from_first_and_last_activity(db: Database):
    timer.start_timer(db, start_ts=at(9))
    timer.stop_timer(db, end_ts=at(9, 30))
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="m", title="Sync", start_ts=at(14), end_ts=at(15), color_id="7"))
    inferred = workday.infer_workday(db, _cfg(), at(12))
    assert inferred.clock_in_ts == at(9)
    assert inferred.clock_out_ts == at(15)
    assert inferred.source == WorkdaySource.INFERRED


def test_infer_ignores_pink(db: Database):
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="p", title="Reminder", start_ts=at(6), end_ts=at(6, 5), color_id="4"))
    timer.start_timer(db, start_ts=at(9))
    timer.stop_timer(db, end_ts=at(10))
    inferred = workday.infer_workday(db, _cfg(), at(12))
    assert inferred.clock_in_ts == at(9)  # pink 6am ignored


def test_infer_returns_none_when_empty(db: Database):
    assert workday.infer_workday(db, _cfg(), at(12)) is None


def test_get_workday_prefers_manual(db: Database):
    workday.clock_in(db, ts=at(7))
    timer.start_timer(db, start_ts=at(9))
    timer.stop_timer(db, end_ts=at(10))
    wd = workday.get_workday(db, _cfg(), at(12))
    assert wd.source == WorkdaySource.MANUAL
    assert wd.clock_in_ts == at(7)


def test_get_workday_falls_back_to_inferred(db: Database):
    timer.start_timer(db, start_ts=at(9))
    timer.stop_timer(db, end_ts=at(10))
    wd = workday.get_workday(db, _cfg(), at(12))
    assert wd.source == WorkdaySource.INFERRED


# ----- notify ------------------------------------------------------------

def test_notify_command_terminal_notifier():
    cmd = notify.build_notify_command("T", "M", has_terminal_notifier=True)
    assert cmd[0] == "terminal-notifier"
    assert "T" in cmd and "M" in cmd


def test_notify_command_osascript_fallback():
    cmd = notify.build_notify_command("T", "M", has_terminal_notifier=False)
    assert cmd[0] == "osascript"
    assert "display notification" in cmd[2]


# ----- reminders / plists ------------------------------------------------

def test_clock_in_plist_schedule():
    p = reminders.clock_in_plist(9, 30)
    assert p["StartCalendarInterval"] == {"Hour": 9, "Minute": 30}
    assert p["Label"] == reminders.CLOCK_IN_LABEL


def test_checkin_plist_interval():
    p = reminders.checkin_plist(45)
    assert p["StartInterval"] == 45 * 60


def test_plist_xml_roundtrips():
    p = reminders.clock_in_plist(9, 0)
    parsed = plistlib.loads(reminders.plist_to_xml(p))
    assert parsed["Label"] == reminders.CLOCK_IN_LABEL


def test_install_reminders_writes_files(tmp_path, monkeypatch):
    # Avoid touching launchctl during tests.
    monkeypatch.setattr(reminders.subprocess, "run", lambda *a, **k: None)
    cfg = Config(clock_in_reminder_time="09:15", checkin_interval_minutes=30)
    written = reminders.install_reminders(cfg, agents_dir=tmp_path)
    assert len(written) == 2
    assert all(p.exists() for p in written)
    parsed = plistlib.loads((tmp_path / f"{reminders.CLOCK_IN_LABEL}.plist").read_bytes())
    assert parsed["StartCalendarInterval"] == {"Hour": 9, "Minute": 15}


def test_install_reminders_skips_checkin_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders.subprocess, "run", lambda *a, **k: None)
    cfg = Config(checkin_interval_minutes=0)
    written = reminders.install_reminders(cfg, agents_dir=tmp_path)
    assert len(written) == 1
