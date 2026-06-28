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
                           time_max=datetime(2026, 6, 29, tzinfo=UTC))
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
                           time_max=datetime(2026, 6, 29, tzinfo=UTC))
    assert n == 1


def test_fetch_follows_pagination(db: Database):
    pages = [
        {"items": [_timed_event("a", 9, 10)], "nextPageToken": 1},
        {"items": [_timed_event("b", 11, 12)]},
    ]
    raw = gcal.fetch_events(FakeService(pages),
                            datetime(2026, 6, 28, tzinfo=UTC),
                            datetime(2026, 6, 29, tzinfo=UTC))
    assert [r["id"] for r in raw] == ["a", "b"]
