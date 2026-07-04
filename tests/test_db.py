from datetime import datetime, timedelta, timezone

import pytest

from time_tracker.db import Database
from time_tracker.models import (
    CalendarEvent,
    Source,
    TimeEntry,
    Workday,
    WorkdaySource,
)

UTC = timezone.utc


def _entry(hour: int, dur_min: int | None = 30, **kw) -> TimeEntry:
    start = datetime(2026, 6, 28, hour, 0, tzinfo=UTC)
    end = start + timedelta(minutes=dur_min) if dur_min is not None else None
    return TimeEntry(start_ts=start, end_ts=end, source=Source.TIMER, **kw)


def test_schema_creates_tables(db: Database):
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert {"time_entry", "calendar_event", "workday", "category"} <= names
    assert "project" not in names


def test_has_column_and_migrate_is_idempotent(db: Database):
    assert db._has_column("time_entry", "category")
    assert not db._has_column("time_entry", "nonexistent")
    # Re-running the migration must be a harmless no-op.
    db._migrate()
    db.init_schema()


def test_migration_drops_legacy_project(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE time_entry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts TEXT NOT NULL, end_ts TEXT, category TEXT,
            project TEXT, description TEXT, source TEXT NOT NULL,
            calendar_event_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE project (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO time_entry (start_ts, source, created_at, updated_at, project)
        VALUES ('2026-06-28T09:00:00+00:00', 'timer', '2026-06-28T09:00:00+00:00',
                '2026-06-28T09:00:00+00:00', 'legacy');
        """
    )
    conn.commit()
    conn.close()

    database = Database(path)
    try:
        assert not database._has_column("time_entry", "project")
        names = {
            r["name"]
            for r in database.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "project" not in names
        # Existing row survives the column drop.
        assert database.list_entries()[0].category is None
    finally:
        database.close()


def test_create_and_get_entry(db: Database):
    created = db.create_entry(_entry(9, category="dev", description="work"))
    assert created.id is not None
    fetched = db.get_entry(created.id)
    assert fetched.category == "dev"
    assert fetched.description == "work"
    assert fetched.duration_seconds == 1800


def test_update_entry(db: Database):
    e = db.create_entry(_entry(9))
    e.category = "meetings"
    db.update_entry(e)
    assert db.get_entry(e.id).category == "meetings"


def test_delete_entry(db: Database):
    e = db.create_entry(_entry(9))
    db.delete_entry(e.id)
    assert db.get_entry(e.id) is None


def test_running_entry_has_null_end(db: Database):
    running = db.create_entry(_entry(9, dur_min=None))
    assert running.is_running
    assert running.duration_seconds is None
    found = db.get_running_entry()
    assert found.id == running.id


def test_list_entries_ordered_and_ranged(db: Database):
    db.create_entry(_entry(11))
    db.create_entry(_entry(9))
    db.create_entry(_entry(15))
    listed = db.list_entries()
    starts = [e.start_ts.hour for e in listed]
    assert starts == [9, 11, 15]
    ranged = db.list_entries(
        start="2026-06-28T10:00:00+00:00", end="2026-06-28T14:00:00+00:00"
    )
    assert [e.start_ts.hour for e in ranged] == [11]


def test_timestamps_are_utc_aware_after_roundtrip(db: Database):
    e = db.create_entry(_entry(9))
    fetched = db.get_entry(e.id)
    assert fetched.start_ts.tzinfo is not None
    assert fetched.start_ts == datetime(2026, 6, 28, 9, 0, tzinfo=UTC)


def test_naive_datetime_coerced_to_utc(db: Database):
    naive = TimeEntry(start_ts=datetime(2026, 6, 28, 9, 0), source=Source.BACKFILL)
    created = db.create_entry(naive)
    fetched = db.get_entry(created.id)
    assert fetched.start_ts == datetime(2026, 6, 28, 9, 0, tzinfo=UTC)


def test_calendar_event_upsert_is_idempotent(db: Database):
    ev = CalendarEvent(
        gcal_id="abc",
        title="Standup",
        start_ts=datetime(2026, 6, 28, 10, 0, tzinfo=UTC),
        end_ts=datetime(2026, 6, 28, 10, 15, tzinfo=UTC),
        color_id="7",
    )
    db.upsert_calendar_event(ev)
    ev.title = "Standup (renamed)"
    db.upsert_calendar_event(ev)
    events = db.list_calendar_events()
    assert len(events) == 1
    assert events[0].title == "Standup (renamed)"


def test_calendar_excluded_color_filtering(db: Database):
    db.upsert_calendar_event(
        CalendarEvent(
            gcal_id="meet",
            title="Real meeting",
            start_ts=datetime(2026, 6, 28, 10, 0, tzinfo=UTC),
            end_ts=datetime(2026, 6, 28, 11, 0, tzinfo=UTC),
            color_id="7",
        )
    )
    db.upsert_calendar_event(
        CalendarEvent(
            gcal_id="rem",
            title="Pink reminder",
            start_ts=datetime(2026, 6, 28, 8, 0, tzinfo=UTC),
            end_ts=datetime(2026, 6, 28, 8, 5, tzinfo=UTC),
            color_id="4",
        )
    )
    visible = db.list_calendar_events(excluded_color_ids=["4"])
    assert [e.gcal_id for e in visible] == ["meet"]


def test_workday_upsert_one_row_per_date(db: Database):
    wd = Workday(
        date="2026-06-28",
        clock_in_ts=datetime(2026, 6, 28, 8, 0, tzinfo=UTC),
        source=WorkdaySource.MANUAL,
    )
    db.upsert_workday(wd)
    wd.clock_out_ts = datetime(2026, 6, 28, 17, 0, tzinfo=UTC)
    db.upsert_workday(wd)
    fetched = db.get_workday("2026-06-28")
    assert fetched.clock_out_ts.hour == 17
    count = db.conn.execute("SELECT COUNT(*) AS c FROM workday").fetchone()["c"]
    assert count == 1
