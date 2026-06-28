"""Typer CLI — a thin presentation layer over ``time_tracker.core``.

No business logic lives here; every command delegates to the core/db modules so
a future web/phone front-end can reuse them unchanged. The DB path can be
overridden with the ``TIMETRACKER_DB`` env var (used by tests).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import questionary
import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .core import backfill, checkin as checkin_mod, gcal, notify, reminders, reports
from .core import timer as timer_mod
from .core import timeutil
from .core import workday as workday_mod
from .db import DEFAULT_DB_PATH, Database

app = typer.Typer(help="Track and analyse how you spend your work time.")
console = Console()


def get_db() -> Database:
    return Database(os.environ.get("TIMETRACKER_DB", str(DEFAULT_DB_PATH)))


def _fmt_dur(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _local(dt: datetime) -> str:
    return dt.astimezone().strftime("%H:%M")


def _today_local() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_date(date: str | None) -> datetime:
    """A datetime anchored on the requested local date (defaults to today)."""
    if not date:
        return _today_local()
    d = datetime.fromisoformat(date)
    return d.replace(tzinfo=timeutil.local_tz()) if d.tzinfo is None else d


def _known_values(db: Database, column: str) -> list[str]:
    """Distinct non-null values for a column from time_entry, most-used first."""
    rows = db.conn.execute(
        f"SELECT {column}, COUNT(*) c FROM time_entry "
        f"WHERE {column} IS NOT NULL GROUP BY {column} ORDER BY c DESC"
    ).fetchall()
    return [r[column] for r in rows]


def _is_interactive() -> bool:
    """True when running in a real terminal (not piped / CliRunner)."""
    import sys
    return sys.stdin.isatty()


def _prompt_entry_fields(
    db: Database,
    category: str | None,
    project: str | None,
    description: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Interactively fill in any missing entry fields using questionary.

    Shows existing categories/projects as a pick list (most-used first) plus a
    "New…" option to type a fresh value. Skips prompts when not in a TTY (e.g.
    tests / piped use). Returns (category, project, description).
    """
    if not _is_interactive():
        return category, project, description

    NEW = "✏  New…"
    SKIP = "— skip —"

    def _pick_or_type(prompt: str, existing: list[str], current: str | None) -> str | None:
        if current is not None:
            return current or None
        choices = existing + ([NEW] if existing else []) + [SKIP]
        chosen = questionary.select(prompt, choices=choices).ask()
        if chosen is None or chosen == SKIP:
            return None
        if chosen == NEW or not existing:
            typed = questionary.text(f"Enter {prompt.lower().rstrip(':')}:").ask()
            return typed.strip() or None
        return chosen

    category = _pick_or_type("Category:", _known_values(db, "category"), category)
    project = _pick_or_type("Project:", _known_values(db, "project"), project)

    if description is None:
        description = questionary.text("Description (optional):").ask()
        description = (description or "").strip() or None

    return category, project, description


def _parse_when(value: str, base: datetime) -> datetime:
    """Parse a time as either 'HH:MM' (local, on base's date) or full ISO -> UTC."""
    if "T" in value or " " in value:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
        dt = dt.replace(tzinfo=timeutil.local_tz()) if dt.tzinfo is None else dt
        return dt.astimezone(timezone.utc)
    return timeutil.parse_hhmm_on(base, value)


@app.command()
def start(
    category: str = typer.Option(None, "--category", "-c"),
    project: str = typer.Option(None, "--project", "-p"),
    description: str = typer.Option(None, "--desc", "-d"),
    at: str = typer.Option(None, "--at", help="Backdate start to HH:MM or ISO."),
):
    """Start a live timer. With no flags, prompts interactively."""
    db = get_db()
    if category is None and project is None and description is None:
        category, project, description = _prompt_entry_fields(db, None, None, None)
    start_ts = _parse_when(at, _today_local()) if at else None
    try:
        e = timer_mod.start_timer(db, category, project, description, start_ts=start_ts)
    except timer_mod.TimerError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Started[/green] timer at {_local(e.start_ts)} "
                  f"({category or 'uncategorized'})")


@app.command()
def stop():
    """Stop the running timer."""
    db = get_db()
    try:
        e = timer_mod.stop_timer(db)
    except timer_mod.TimerError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Stopped[/green] — logged {_fmt_dur(e.duration_seconds)}")


@app.command()
def checkin(
    description: str = typer.Argument(None, help="What are you working on?"),
    category: str = typer.Option(None, "--category", "-c"),
    project: str = typer.Option(None, "--project", "-p"),
):
    """Log a check-in covering the time since your last activity. Prompts if no args."""
    db = get_db()
    if description is None and _is_interactive():
        description = questionary.text("What have you been working on?").ask()
        description = (description or "").strip() or None
    description = description or "unspecified"
    if category is None and project is None:
        category, project, _ = _prompt_entry_fields(db, None, None, "skip")
    e = checkin_mod.record_checkin(db, description, category=category, project=project)
    console.print(f"[green]Checked in[/green]: {description} "
                  f"({_fmt_dur(e.duration_seconds)})")


@app.command(name="in")
def clock_in():
    """Clock in for the day."""
    db = get_db()
    wd = workday_mod.clock_in(db)
    console.print(f"[green]Clocked in[/green] at {_local(wd.clock_in_ts)}")


@app.command(name="out")
def clock_out():
    """Clock out for the day."""
    db = get_db()
    wd = workday_mod.clock_out(db)
    console.print(f"[green]Clocked out[/green] at {_local(wd.clock_out_ts)}")


@app.command()
def sync(days: int = typer.Option(7, help="Days forward/back to sync.")):
    """Sync meetings from Google Calendar."""
    db = get_db()
    try:
        creds = gcal.get_credentials()
        service = gcal.build_service(creds)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    now = datetime.now(timezone.utc)
    n = gcal.sync_calendar(db, service, now - timedelta(days=days),
                           now + timedelta(days=days))
    console.print(f"[green]Synced[/green] {n} events.")


@app.command()
def day(date: str = typer.Argument(None, help="ISO date, defaults to today.")):
    """Show today's timeline: meetings, logged entries, and open gaps."""
    db = get_db()
    config = load_config()
    target = _resolve_date(date)
    start_utc, end_utc = timeutil.local_day_bounds(target)
    start_iso, end_iso = start_utc.isoformat(), end_utc.isoformat()

    table = Table(title=f"Timeline — {timeutil.local_date_key(target)}")
    table.add_column("Time")
    table.add_column("Type")
    table.add_column("What")

    rows = []
    for ev in db.list_calendar_events(start_iso, end_iso,
                                      excluded_color_ids=config.excluded_color_ids,
                                      excluded_event_types=config.excluded_event_types):
        rows.append((ev.start_ts, f"{_local(ev.start_ts)}-{_local(ev.end_ts)}",
                     "meeting", ev.title))
    for e in db.list_entries(start_iso, end_iso):
        end = _local(e.end_ts) if e.end_ts else "…"
        rows.append((e.start_ts, f"{_local(e.start_ts)}-{end}",
                     e.source.value, e.description or e.category or ""))
    for g in backfill.find_day_gaps(db, config, target):
        rows.append((g.start, f"{_local(g.start)}-{_local(g.end)}",
                     "[yellow]gap[/yellow]", _fmt_dur(g.seconds)))

    for _, time_s, typ, what in sorted(rows, key=lambda r: r[0]):
        table.add_row(time_s, typ, what)
    console.print(table)


@app.command()
def log(
    start: str = typer.Argument(..., help="Start time: 'HH:MM' (today) or ISO."),
    end: str = typer.Argument(..., help="End time: 'HH:MM' (today) or ISO."),
    description: str = typer.Argument(None, help="What you were doing."),
    category: str = typer.Option(None, "--category", "-c"),
    project: str = typer.Option(None, "--project", "-p"),
    date: str = typer.Option(None, "--date", help="ISO date for HH:MM times (default today)."),
):
    """Retrospectively log a past block, e.g. `tt log 09:30 10:30 "wrote spec"`.

    Also works interactively — omit description/category/project and you'll be prompted.
    """
    db = get_db()
    base = _resolve_date(date)
    start_ts = _parse_when(start, base)
    end_ts = _parse_when(end, base)
    if description is None and _is_interactive():
        description = questionary.text("What were you working on?").ask()
        description = (description or "").strip() or None
    description = description or "unspecified"
    if category is None and project is None:
        category, project, _ = _prompt_entry_fields(db, None, None, "skip")
    try:
        e = backfill.fill_gap(db, start_ts, end_ts, description, category, project)
    except (ValueError, backfill.OverlapError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Logged[/green] {_local(start_ts)}-{_local(end_ts)} "
                  f"({_fmt_dur(e.duration_seconds)}): {description}")


@app.command()
def report(period: str = typer.Argument("day", help="'day' or 'week'.")):
    """Summarise where time went (meeting vs focus vs idle)."""
    db = get_db()
    config = load_config()
    today = _today_local()
    days = 7 if period == "week" else 1
    start = today - timedelta(days=days - 1)

    table = Table(title=f"Report — last {days} day(s)")
    for col in ("Date", "Workday", "Meetings", "Focus", "Idle", "Frag."):
        table.add_column(col)
    cat_totals: dict[str, float] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        day_start_utc, day_end_utc = timeutil.local_day_bounds(d)
        s = reports.day_summary(db, config, d)
        if s is not None:
            table.add_row(s.date, _fmt_dur(s.workday_seconds),
                          _fmt_dur(s.meeting_seconds), _fmt_dur(s.logged_seconds),
                          _fmt_dur(s.idle_seconds), f"{s.fragmentation:.1f}/h")
        for k, v in reports.category_breakdown(
            db, day_start_utc.isoformat(),
            day_end_utc.isoformat()).items():
            cat_totals[k] = cat_totals.get(k, 0) + v
    console.print(table)
    if cat_totals:
        cat = Table(title="By category")
        cat.add_column("Category")
        cat.add_column("Time")
        for k, v in sorted(cat_totals.items(), key=lambda x: -x[1]):
            cat.add_row(k, _fmt_dur(v))
        console.print(cat)


@app.command(name="install-reminders")
def install_reminders():
    """Install macOS clock-in + check-in reminder notifications."""
    config = load_config()
    written = reminders.install_reminders(config)
    for p in written:
        console.print(f"[green]Installed[/green] {p}")


@app.command(name="uninstall-reminders")
def uninstall_reminders():
    """Remove the reminder notifications."""
    removed = reminders.uninstall_reminders()
    for p in removed:
        console.print(f"[yellow]Removed[/yellow] {p}")
    if not removed:
        console.print("Nothing to remove.")


@app.command(name="remind-clock-in", hidden=True)
def remind_clock_in():
    """(launchd) Fire the clock-in reminder banner."""
    notify.notify("Time Tracker", "Did you clock in? Run `tt in` (set your time).")


@app.command(name="remind-checkin", hidden=True)
def remind_checkin():
    """(launchd) Fire the periodic check-in banner."""
    notify.notify("Time Tracker", "What are you working on? Run `tt checkin`.")


if __name__ == "__main__":
    app()
