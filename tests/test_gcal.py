from datetime import datetime, timezone

from time_tracker.core import gcal
from time_tracker.db import Database

UTC = timezone.utc


class FakeEvents:
    """Mimics service.events().list(...).execute() with optional paging."""

    def __init__(self, pages: list[dict]):
        self._pages = pages
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        token = kwargs.get("pageToken") or 0
        self._idx = token
        return self

    def execute(self):
        return self._pages[self._idx]


class FakeService:
    def __init__(self, pages):
        self._events = FakeEvents(pages)

    def events(self):
        return self._events


def _timed_event(eid, h1, h2, color=None, attendees=0, etype="default"):
    return {
        "id": eid,
        "summary": f"Event {eid}",
        "start": {"dateTime": f"2026-06-28T{h1:02d}:00:00+00:00"},
        "end": {"dateTime": f"2026-06-28T{h2:02d}:00:00+00:00"},
        "colorId": color,
        "attendees": [{"email": f"a{i}@x.com"} for i in range(attendees)],
        "eventType": etype,
        "status": "confirmed",
    }


def test_parse_timed_event():
    ev = gcal.parse_event(_timed_event("a", 10, 11, color="7", attendees=3))
    assert ev.title == "Event a"
    assert ev.start_ts == datetime(2026, 6, 28, 10, tzinfo=UTC)
    assert ev.attendees_count == 3
    assert ev.color_id == "7"


def test_parse_all_day_event():
    raw = {
        "id": "ad",
        "summary": "Holiday",
        "start": {"date": "2026-06-28"},
        "end": {"date": "2026-06-29"},
    }
    ev = gcal.parse_event(raw)
    assert ev.start_ts == datetime(2026, 6, 28, tzinfo=UTC)
    assert ev.end_ts == datetime(2026, 6, 29, tzinfo=UTC)
    assert ev.event_type == "default"


def test_parse_naive_datetime_coerced_utc():
    raw = {
        "id": "n",
        "summary": "x",
        "start": {"dateTime": "2026-06-28T10:00:00"},
        "end": {"dateTime": "2026-06-28T11:00:00"},
    }
    ev = gcal.parse_event(raw)
    assert ev.start_ts.tzinfo is not None


def test_sync_inserts_events(db: Database):
    pages = [{"items": [_timed_event("a", 9, 10), _timed_event("b", 11, 12)]}]
    n = gcal.sync_calendar(db, FakeService(pages),
                           time_min=datetime(2026, 6, 28, tzinfo=UTC),
                           time_max=datetime(2026, 6, 29, tzinfo=UTC)).synced
    assert n == 2
    assert len(db.list_calendar_events()) == 2


def test_sync_is_idempotent(db: Database):
    pages = [{"items": [_timed_event("a", 9, 10)]}]
    args = dict(time_min=datetime(2026, 6, 28, tzinfo=UTC),
                time_max=datetime(2026, 6, 29, tzinfo=UTC))
    gcal.sync_calendar(db, FakeService(pages), **args)
    gcal.sync_calendar(db, FakeService(pages), **args)
    assert len(db.list_calendar_events()) == 1


def test_sync_skips_cancelled(db: Database):
    ev = _timed_event("c", 9, 10)
    ev["status"] = "cancelled"
    pages = [{"items": [ev, _timed_event("ok", 11, 12)]}]
    n = gcal.sync_calendar(db, FakeService(pages),
                           time_min=datetime(2026, 6, 28, tzinfo=UTC),
                           time_max=datetime(2026, 6, 29, tzinfo=UTC)).synced
    assert n == 1


def _named_event(eid, summary, h1=9, h2=10):
    ev = _timed_event(eid, h1, h2)
    ev["summary"] = summary
    return ev


def test_sync_applies_category_rules(db: Database):
    rules = [{"match": "MATS", "category": "MATS workplace"}]
    pages = [{"items": [_named_event("m", "MATS standup"),
                        _named_event("x", "Dentist")]}]
    gcal.sync_calendar(db, FakeService(pages),
                       time_min=datetime(2026, 6, 28, tzinfo=UTC),
                       time_max=datetime(2026, 6, 29, tzinfo=UTC),
                       category_rules=rules)
    by_id = {e.gcal_id: e for e in db.list_calendar_events()}
    assert by_id["m"].category == "MATS workplace"
    assert by_id["m"].category_source == "rule"
    assert by_id["x"].category is None


def test_manual_category_survives_resync_but_rule_refreshes(db: Database):
    rules = [{"match": "MATS", "category": "MATS workplace"}]
    args = dict(time_min=datetime(2026, 6, 28, tzinfo=UTC),
                time_max=datetime(2026, 6, 29, tzinfo=UTC),
                category_rules=rules)
    pages = [{"items": [_named_event("m", "MATS standup"),
                        _named_event("r", "MATS retro")]}]
    gcal.sync_calendar(db, FakeService(pages), **args)

    # User manually overrides one meeting's category.
    m = {e.gcal_id: e for e in db.list_calendar_events()}["m"]
    db.set_calendar_category(m.id, "fellows")

    # Re-sync: manual override is preserved, rule-derived one still present.
    gcal.sync_calendar(db, FakeService(pages), **args)
    by_id = {e.gcal_id: e for e in db.list_calendar_events()}
    assert by_id["m"].category == "fellows"
    assert by_id["m"].category_source == "manual"
    assert by_id["r"].category == "MATS workplace"
    assert by_id["r"].category_source == "rule"


def test_fetch_follows_pagination(db: Database):
    pages = [
        {"items": [_timed_event("a", 9, 10)], "nextPageToken": 1},
        {"items": [_timed_event("b", 11, 12)]},
    ]
    raw = gcal.fetch_events(FakeService(pages),
                            datetime(2026, 6, 28, tzinfo=UTC),
                            datetime(2026, 6, 29, tzinfo=UTC))
    assert [r["id"] for r in raw] == ["a", "b"]


# ----- reconciliation: meetings Google no longer returns ------------------

WINDOW = dict(time_min=datetime(2026, 6, 28, tzinfo=UTC),
              time_max=datetime(2026, 6, 29, tzinfo=UTC))


def test_sync_prunes_cancelled_meeting(db: Database):
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("a", 9, 10),
                                                   _timed_event("b", 11, 12)]}]), **WINDOW)
    # "b" disappears from Google (cancelled).
    result = gcal.sync_calendar(db, FakeService([{"items": [_timed_event("a", 9, 10)]}]), **WINDOW)
    assert [e.gcal_id for e in result.pruned] == ["b"]
    assert [e.gcal_id for e in db.list_calendar_events()] == ["a"]


def test_sync_prunes_the_old_slot_when_a_meeting_moves(db: Database):
    """The real bug: a moved meeting must not linger beside its new time."""
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("fred_1130", 11, 12)]}]), **WINDOW)
    result = gcal.sync_calendar(
        db, FakeService([{"items": [_timed_event("fred_1515", 15, 16)]}]), **WINDOW)
    assert [e.gcal_id for e in result.pruned] == ["fred_1130"]
    assert [e.gcal_id for e in db.list_calendar_events()] == ["fred_1515"]


def test_prune_leaves_events_outside_the_window_alone(db: Database):
    """Syncing one day must not delete meetings cached for other days."""
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("a", 9, 10)]}]), **WINDOW)
    other = dict(time_min=datetime(2026, 7, 5, tzinfo=UTC),
                 time_max=datetime(2026, 7, 6, tzinfo=UTC))
    july = _timed_event("july", 9, 10)
    july["start"] = {"dateTime": "2026-07-05T09:00:00+00:00"}
    july["end"] = {"dateTime": "2026-07-05T10:00:00+00:00"}
    result = gcal.sync_calendar(db, FakeService([{"items": [july]}]), **other)
    assert result.pruned == []
    assert {e.gcal_id for e in db.list_calendar_events()} == {"a", "july"}


def test_empty_window_prunes_nothing(db: Database):
    """A window that comes back empty must not wipe real cached meetings."""
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("a", 9, 10)]}]), **WINDOW)
    result = gcal.sync_calendar(db, FakeService([{"items": []}]), **WINDOW)
    assert result.pruned == []
    assert len(db.list_calendar_events()) == 1


def test_no_prune_flag_keeps_stale_rows(db: Database):
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("a", 9, 10),
                                                   _timed_event("b", 11, 12)]}]), **WINDOW)
    result = gcal.sync_calendar(
        db, FakeService([{"items": [_timed_event("a", 9, 10)]}]), prune=False, **WINDOW)
    assert result.pruned == []
    assert len(db.list_calendar_events()) == 2


def test_pruning_keeps_the_logged_time_entry(db: Database):
    """Deleting a meeting must never delete time you logged against it."""
    from time_tracker.models import Source, TimeEntry
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("a", 9, 10)]}]), **WINDOW)
    ev = db.list_calendar_events()[0]
    entry = db.create_entry(TimeEntry(
        start_ts=datetime(2026, 6, 28, 9, tzinfo=UTC),
        end_ts=datetime(2026, 6, 28, 10, tzinfo=UTC),
        description="that meeting", source=Source.BACKFILL,
        calendar_event_id=ev.id,
    ))
    gcal.sync_calendar(db, FakeService([{"items": [_timed_event("z", 13, 14)]}]), **WINDOW)
    kept = db.get_entry(entry.id)
    assert kept is not None and kept.description == "that meeting"
    assert kept.calendar_event_id is None  # link cleared, time preserved
