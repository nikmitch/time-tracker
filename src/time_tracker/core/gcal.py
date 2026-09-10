"""Google Calendar sync.

The OAuth/credential plumbing is isolated from the pure parsing + sync logic so
the latter can be unit-tested with a fake service object (no network, no
credentials). Tests exercise ``parse_event`` and ``sync_calendar`` directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional, Protocol

from ..db import Database
from ..models import CalendarEvent, to_iso, utcnow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CONFIG_DIR = Path.home() / ".time_tracker"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"


class CalendarService(Protocol):
    """The slice of the Google client we depend on (eases mocking)."""

    def events(self) -> Any: ...


# ----- credentials / client (network; not unit-tested) -------------------

def get_credentials(
    credentials_path: Path = CREDENTIALS_PATH, token_path: Path = TOKEN_PATH
):
    """Run/refresh the OAuth flow, returning Google credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Missing OAuth client file at {credentials_path}. "
                    "See docs/design.html section 6 for setup."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
    return creds


def build_service(creds) -> CalendarService:
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds)


# ----- pure logic (unit-tested) ------------------------------------------

def _parse_gtime(node: dict) -> tuple[datetime, bool]:
    """Parse a Google start/end node. Returns (utc_datetime, is_all_day)."""
    if "dateTime" in node:
        dt = datetime.fromisoformat(node["dateTime"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), False
    # All-day event: "date" is a plain YYYY-MM-DD (end is exclusive).
    d = datetime.fromisoformat(node["date"]).replace(tzinfo=timezone.utc)
    return d, True


def parse_event(raw: dict) -> CalendarEvent:
    """Convert a raw Google Calendar event into our ``CalendarEvent``."""
    start, _ = _parse_gtime(raw["start"])
    end, all_day = _parse_gtime(raw["end"])
    attendees = raw.get("attendees", [])
    return CalendarEvent(
        gcal_id=raw["id"],
        title=raw.get("summary", "(no title)"),
        start_ts=start,
        end_ts=end,
        attendees_count=len(attendees),
        color_id=raw.get("colorId"),
        event_type=raw.get("eventType", "default"),
        last_synced=utcnow(),
    )


def fetch_events(
    service: CalendarService,
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = "primary",
) -> list[dict]:
    """Fetch raw events in [time_min, time_max), following pagination."""
    raw: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.astimezone(timezone.utc).isoformat(),
                timeMax=time_max.astimezone(timezone.utc).isoformat(),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        raw.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return raw


class SyncResult(NamedTuple):
    """What a sync did: how many events it wrote, and what it removed."""

    synced: int
    pruned: list[CalendarEvent]


def sync_calendar(
    db: Database,
    service: CalendarService,
    time_min: Optional[datetime] = None,
    time_max: Optional[datetime] = None,
    calendar_id: str = "primary",
    category_rules: Optional[list[dict]] = None,
    prune: bool = True,
) -> SyncResult:
    """Reconcile the local cache with Google for the given window.

    Cancelled events (status == "cancelled") are skipped. When ``category_rules``
    are given, a rule-derived category is attached to each event; the DB layer
    preserves any manual override so re-syncs never clobber a user's edit.

    With ``prune`` (the default), cached meetings in the window that Google no
    longer returns are deleted, so cancelled and moved meetings actually go away
    instead of lingering beside their replacement. As a safety net, a window
    that comes back completely empty prunes nothing: a legitimately empty week
    is rare, while wrongly emptying one would silently delete real meetings.
    """
    from .categorize import categorize_meeting

    rules = category_rules or []
    now = utcnow()
    time_min = time_min or (now - timedelta(days=7))
    time_max = time_max or (now + timedelta(days=7))
    count = 0
    seen: set[str] = set()
    for raw in fetch_events(service, time_min, time_max, calendar_id):
        if raw.get("status") == "cancelled":
            continue
        if "start" not in raw or "end" not in raw:
            continue
        event = parse_event(raw)
        cat = categorize_meeting(
            event.title, event.color_id, event.attendees_count, rules
        )
        if cat is not None:
            event.category = cat
            event.category_source = "rule"
        db.upsert_calendar_event(event)
        seen.add(event.gcal_id)
        count += 1
    pruned: list[CalendarEvent] = []
    if prune and seen:
        pruned = db.prune_calendar_events(
            to_iso(time_min), to_iso(time_max), seen
        )
    return SyncResult(count, pruned)
