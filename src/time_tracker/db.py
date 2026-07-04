"""SQLite storage layer + CRUD for the time-entry timeline.

The store is intentionally front-end-agnostic: the CLI (and a future web/phone
backend) both go through this module. No terminal/UI code lives here.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .models import (
    CalendarEvent,
    Source,
    TimeEntry,
    Workday,
    WorkdaySource,
    from_iso,
    to_iso,
    utcnow,
)

DEFAULT_DB_PATH = Path.home() / ".time_tracker" / "tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS time_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts TEXT NOT NULL,
    end_ts TEXT,
    category TEXT,
    description TEXT,
    source TEXT NOT NULL,
    calendar_event_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (calendar_event_id) REFERENCES calendar_event(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_time_entry_start ON time_entry(start_ts);

CREATE TABLE IF NOT EXISTS calendar_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gcal_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    attendees_count INTEGER NOT NULL DEFAULT 0,
    color_id TEXT,
    event_type TEXT,
    last_synced TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calendar_event_start ON calendar_event(start_ts);

CREATE TABLE IF NOT EXISTS workday (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    clock_in_ts TEXT,
    clock_out_ts TEXT,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
"""


class Database:
    """Thin wrapper over a SQLite connection with typed CRUD helpers."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        self.path = ":memory:" if path == ":memory:" else Path(path)
        if self.path != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Apply idempotent schema tweaks the plain ``CREATE`` above can't express.

        SQLite's ``CREATE TABLE IF NOT EXISTS`` never alters an existing table,
        so column additions/removals for already-created DBs live here. Each step
        is guarded by ``_has_column`` so re-running is a no-op.
        """
        with self._tx() as conn:
            # Legacy DBs predate the removal of the per-entry ``project`` field.
            if self._has_column("time_entry", "project"):
                conn.execute("ALTER TABLE time_entry DROP COLUMN project")
            conn.execute("DROP TABLE IF EXISTS project")

    def _has_column(self, table: str, column: str) -> bool:
        rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ----- TimeEntry CRUD -------------------------------------------------

    def create_entry(self, entry: TimeEntry) -> TimeEntry:
        with self._tx() as conn:
            cur = conn.execute(
                """
                INSERT INTO time_entry
                    (start_ts, end_ts, category, description, source,
                     calendar_event_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    to_iso(entry.start_ts),
                    to_iso(entry.end_ts),
                    entry.category,
                    entry.description,
                    entry.source.value,
                    entry.calendar_event_id,
                    to_iso(entry.created_at),
                    to_iso(entry.updated_at),
                ),
            )
            entry.id = cur.lastrowid
        return entry

    def get_entry(self, entry_id: int) -> Optional[TimeEntry]:
        row = self.conn.execute(
            "SELECT * FROM time_entry WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_entry(row) if row else None

    def list_entries(
        self, start: Optional[str] = None, end: Optional[str] = None
    ) -> list[TimeEntry]:
        """List entries ordered by start time, optionally bounded by ISO range."""
        query = "SELECT * FROM time_entry"
        params: list[str] = []
        clauses = []
        if start is not None:
            clauses.append("start_ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("start_ts < ?")
            params.append(end)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY start_ts ASC"
        rows = self.conn.execute(query, params).fetchall()
        return [_row_to_entry(r) for r in rows]

    def get_running_entry(self) -> Optional[TimeEntry]:
        row = self.conn.execute(
            "SELECT * FROM time_entry WHERE end_ts IS NULL "
            "ORDER BY start_ts DESC LIMIT 1"
        ).fetchone()
        return _row_to_entry(row) if row else None

    def update_entry(self, entry: TimeEntry) -> TimeEntry:
        if entry.id is None:
            raise ValueError("Cannot update an entry without an id")
        entry.updated_at = utcnow()
        with self._tx() as conn:
            conn.execute(
                """
                UPDATE time_entry SET
                    start_ts = ?, end_ts = ?, category = ?,
                    description = ?, source = ?, calendar_event_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    to_iso(entry.start_ts),
                    to_iso(entry.end_ts),
                    entry.category,
                    entry.description,
                    entry.source.value,
                    entry.calendar_event_id,
                    to_iso(entry.updated_at),
                    entry.id,
                ),
            )
        return entry

    def delete_entry(self, entry_id: int) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM time_entry WHERE id = ?", (entry_id,))

    # ----- CalendarEvent --------------------------------------------------

    def upsert_calendar_event(self, event: CalendarEvent) -> CalendarEvent:
        """Insert or update by ``gcal_id`` so re-syncs stay idempotent."""
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO calendar_event
                    (gcal_id, title, start_ts, end_ts, attendees_count,
                     color_id, event_type, last_synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gcal_id) DO UPDATE SET
                    title = excluded.title,
                    start_ts = excluded.start_ts,
                    end_ts = excluded.end_ts,
                    attendees_count = excluded.attendees_count,
                    color_id = excluded.color_id,
                    event_type = excluded.event_type,
                    last_synced = excluded.last_synced
                """,
                (
                    event.gcal_id,
                    event.title,
                    to_iso(event.start_ts),
                    to_iso(event.end_ts),
                    event.attendees_count,
                    event.color_id,
                    event.event_type,
                    to_iso(event.last_synced),
                ),
            )
            row = conn.execute(
                "SELECT id FROM calendar_event WHERE gcal_id = ?", (event.gcal_id,)
            ).fetchone()
            event.id = row["id"]
        return event

    def list_calendar_events(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        excluded_color_ids: Optional[list[str]] = None,
        excluded_event_types: Optional[list[str]] = None,
    ) -> list[CalendarEvent]:
        query = "SELECT * FROM calendar_event"
        params: list[str] = []
        clauses = []
        if start is not None:
            clauses.append("start_ts >= ?")
            params.append(start)
        if end is not None:
            clauses.append("start_ts < ?")
            params.append(end)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY start_ts ASC"
        rows = self.conn.execute(query, params).fetchall()
        events = [_row_to_event(r) for r in rows]
        if excluded_color_ids:
            excluded = set(excluded_color_ids)
            events = [e for e in events if e.color_id not in excluded]
        if excluded_event_types:
            excluded_types = set(excluded_event_types)
            events = [e for e in events if e.event_type not in excluded_types]
        return events

    # ----- Workday --------------------------------------------------------

    def upsert_workday(self, workday: Workday) -> Workday:
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO workday (date, clock_in_ts, clock_out_ts, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    clock_in_ts = excluded.clock_in_ts,
                    clock_out_ts = excluded.clock_out_ts,
                    source = excluded.source
                """,
                (
                    workday.date,
                    to_iso(workday.clock_in_ts),
                    to_iso(workday.clock_out_ts),
                    workday.source.value,
                ),
            )
            row = conn.execute(
                "SELECT id FROM workday WHERE date = ?", (workday.date,)
            ).fetchone()
            workday.id = row["id"]
        return workday

    def get_workday(self, date: str) -> Optional[Workday]:
        row = self.conn.execute(
            "SELECT * FROM workday WHERE date = ?", (date,)
        ).fetchone()
        return _row_to_workday(row) if row else None


def _row_to_entry(row: sqlite3.Row) -> TimeEntry:
    return TimeEntry(
        id=row["id"],
        start_ts=from_iso(row["start_ts"]),
        end_ts=from_iso(row["end_ts"]),
        category=row["category"],
        description=row["description"],
        source=Source(row["source"]),
        calendar_event_id=row["calendar_event_id"],
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )


def _row_to_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=row["id"],
        gcal_id=row["gcal_id"],
        title=row["title"],
        start_ts=from_iso(row["start_ts"]),
        end_ts=from_iso(row["end_ts"]),
        attendees_count=row["attendees_count"],
        color_id=row["color_id"],
        event_type=row["event_type"],
        last_synced=from_iso(row["last_synced"]),
    )


def _row_to_workday(row: sqlite3.Row) -> Workday:
    return Workday(
        id=row["id"],
        date=row["date"],
        clock_in_ts=from_iso(row["clock_in_ts"]),
        clock_out_ts=from_iso(row["clock_out_ts"]),
        source=WorkdaySource(row["source"]),
    )
