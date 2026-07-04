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


def _pick_or_type(
    db: Database, prompt: str, column: str, current: str | None
) -> str | None:
    """Pick an existing value for ``column`` (most-used first) or type a new one."""
    NEW = "✏  New…"
    SKIP = "— skip —"
    if current is not None:
        return current or None
    choices = _known_values(db, column) + [NEW, SKIP]
    chosen = questionary.select(prompt, choices=choices).ask()
    if chosen is None or chosen == SKIP:
        return None
    if chosen == NEW:
        typed = questionary.text(f"Enter {prompt.lower().rstrip(':')}:").ask()
        return typed.strip() or None
    return chosen


def _prompt_entry_fields(
    db: Database,
    category: str | None,
    description: str | None,
) -> tuple[str | None, str | None]:
    """Interactively fill in any missing entry fields using questionary.

    Shows existing categories as a pick list (most-used first) plus a "New…"
    option to type a fresh value. Skips prompts when not in a TTY (e.g. tests /
    piped use). Returns (category, description).
    """
    if not _is_interactive():
        return category, description

    category = _pick_or_type(db, "Category:", "category", category)

    if description is None:
        description = questionary.text("Description (optional):").ask()
        description = (description or "").strip() or None

    return category, description


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
    description: str = typer.Option(None, "--desc", "-d"),
    at: str = typer.Option(None, "--at", help="Backdate start to HH:MM or ISO."),
):
    """Start a live timer. With no flags, prompts interactively."""
    db = get_db()
    running = db.get_running_entry()
    if running is not None:
        console.print(f"[red]A timer is already running[/red] (started {_local(running.start_ts)}"
                      + (f" · {running.description}" if running.description else "")
                      + "). Run [bold]tt stop[/bold] first.")
        raise typer.Exit(1)
    if category is None and description is None:
        category, description = _prompt_entry_fields(db, None, None)
    start_ts = _parse_when(at, _today_local()) if at else None
    try:
        e = timer_mod.start_timer(db, category, description, start_ts=start_ts)
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
):
    """Log a check-in covering the time since your last activity. Prompts if no args."""
    db = get_db()
    if description is None and _is_interactive():
        description = questionary.text("What have you been working on?").ask()
        description = (description or "").strip() or None
    description = description or "unspecified"
    if category is None:
        category, _ = _prompt_entry_fields(db, None, "skip")
    e = checkin_mod.record_checkin(db, description, category=category)
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
    config = load_config()
    try:
        creds = gcal.get_credentials()
        service = gcal.build_service(creds)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    now = datetime.now(timezone.utc)
    n = gcal.sync_calendar(db, service, now - timedelta(days=days),
                           now + timedelta(days=days),
                           category_rules=config.meeting_category_rules)
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


def _pick_entry(db: Database, date: datetime | None = None) -> "TimeEntry | None":
    """Show a questionary pick list of logged entries for a day, return chosen one."""
    from .models import TimeEntry
    target = date or _today_local()
    start_utc, end_utc = timeutil.local_day_bounds(target)
    entries = [e for e in db.list_entries(start_utc.isoformat(), end_utc.isoformat())
               if e.end_ts is not None]
    if not entries:
        console.print("[yellow]No completed entries found for that day.[/yellow]")
        return None
    choices = {
        f"{_local(e.start_ts)}-{_local(e.end_ts)}  [{e.category or '—'}]  {e.description or ''}": e
        for e in entries
    }
    chosen_label = questionary.select("Which entry?", choices=list(choices)).ask()
    if chosen_label is None:
        return None
    return choices[chosen_label]


@app.command()
def edit(
    date: str = typer.Option(None, "--date", help="ISO date to pick from (default today)."),
):
    """Edit a logged entry — pick from today's list, then change fields interactively."""
    if not _is_interactive():
        console.print("[red]tt edit requires an interactive terminal.[/red]")
        raise typer.Exit(1)
    db = get_db()
    entry = _pick_entry(db, _resolve_date(date) if date else None)
    if entry is None:
        return

    console.print(f"Editing: [bold]{_local(entry.start_ts)}-{_local(entry.end_ts)}[/bold]  "
                  f"{entry.description or ''}")

    new_start = questionary.text(
        f"Start time (HH:MM, blank = keep {_local(entry.start_ts)}):"
    ).ask()
    new_end = questionary.text(
        f"End time (HH:MM, blank = keep {_local(entry.end_ts)}):"
    ).ask()
    new_desc = questionary.text(
        f"Description (blank = keep '{entry.description or ''}'):"
    ).ask()

    base = entry.start_ts
    if new_start and new_start.strip():
        entry.start_ts = _parse_when(new_start.strip(), base)
    if new_end and new_end.strip():
        entry.end_ts = _parse_when(new_end.strip(), base)
    if entry.end_ts and entry.end_ts <= entry.start_ts:
        console.print("[red]End time must be after start time.[/red]")
        raise typer.Exit(1)
    if new_desc and new_desc.strip():
        entry.description = new_desc.strip()

    # Category via pick list
    entry.category, _ = _prompt_entry_fields(db, entry.category, "skip")

    db.update_entry(entry)
    console.print(f"[green]Updated[/green] {_local(entry.start_ts)}-{_local(entry.end_ts)} "
                  f"({_fmt_dur(entry.duration_seconds)}): {entry.description or ''}")


@app.command()
def delete(
    date: str = typer.Option(None, "--date", help="ISO date to pick from (default today)."),
):
    """Delete a logged entry — pick from today's list, then confirm."""
    if not _is_interactive():
        console.print("[red]tt delete requires an interactive terminal.[/red]")
        raise typer.Exit(1)
    db = get_db()
    entry = _pick_entry(db, _resolve_date(date) if date else None)
    if entry is None:
        return
    confirmed = questionary.confirm(
        f"Delete {_local(entry.start_ts)}-{_local(entry.end_ts)} "
        f"'{entry.description or entry.category or ''}'?"
    ).ask()
    if confirmed:
        db.delete_entry(entry.id)
        console.print("[yellow]Deleted.[/yellow]")
    else:
        console.print("Cancelled.")


@app.command()
def meeting(
    date: str = typer.Option(None, "--date", help="ISO date to pick from (default today)."),
):
    """Categorize a meeting — pick from a day's meetings, then set its category.

    The category is stored as a manual override, so `tt sync` will never
    overwrite it (unlike categories auto-derived from title rules).
    """
    if not _is_interactive():
        console.print("[red]tt meeting requires an interactive terminal.[/red]")
        raise typer.Exit(1)
    db = get_db()
    config = load_config()
    target = _resolve_date(date) if date else _today_local()
    start_utc, end_utc = timeutil.local_day_bounds(target)
    events = db.list_calendar_events(
        start_utc.isoformat(), end_utc.isoformat(),
        excluded_color_ids=config.excluded_color_ids,
        excluded_event_types=config.excluded_event_types,
    )
    if not events:
        console.print("[yellow]No meetings found for that day.[/yellow]")
        return
    choices = {
        f"{_local(ev.start_ts)}-{_local(ev.end_ts)}  [{ev.category or '—'}]  {ev.title}": ev
        for ev in events
    }
    chosen_label = questionary.select("Which meeting?", choices=list(choices)).ask()
    if chosen_label is None:
        return
    ev = choices[chosen_label]
    category = _pick_or_type(db, "Category:", "category", None)
    db.set_calendar_category(ev.id, category)
    console.print(f"[green]Categorized[/green] '{ev.title}' as "
                  f"{category or '(uncategorized)'}")


@app.command()
def log(
    start: str = typer.Argument(..., help="Start time: 'HH:MM' (today) or ISO."),
    end: str = typer.Argument(..., help="End time: 'HH:MM' (today) or ISO."),
    description: str = typer.Argument(None, help="What you were doing."),
    category: str = typer.Option(None, "--category", "-c"),
    date: str = typer.Option(None, "--date", help="ISO date for HH:MM times (default today)."),
):
    """Retrospectively log a past block, e.g. `tt log 09:30 10:30 "wrote spec"`.

    Also works interactively — omit description/category and you'll be prompted.
    """
    db = get_db()
    base = _resolve_date(date)
    start_ts = _parse_when(start, base)
    end_ts = _parse_when(end, base)
    if description is None and _is_interactive():
        description = questionary.text("What were you working on?").ask()
        description = (description or "").strip() or None
    description = description or "unspecified"
    if category is None:
        category, _ = _prompt_entry_fields(db, None, "skip")
    try:
        e = backfill.fill_gap(db, start_ts, end_ts, description, category)
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
            day_end_utc.isoformat(), config).items():
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
