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
    """A datetime anchored on the requested local date (defaults to today).

    Accepts ISO dates plus the relative words ``today``/``yesterday``/``tomorrow``
    and signed day offsets like ``-1`` / ``+2`` (relative to today, local time).
    """
    if not date:
        return _today_local()
    word = date.strip().lower()
    offsets = {"today": 0, "yesterday": -1, "tomorrow": 1}
    if word in offsets:
        return _today_local() + timedelta(days=offsets[word])
    if word.lstrip("+-").isdigit() and word not in ("", "+", "-"):
        return _today_local() + timedelta(days=int(word))
    d = datetime.fromisoformat(date)
    return d.replace(tzinfo=timeutil.local_tz()) if d.tzinfo is None else d


# Pinned category ordering (was most-used-first as of 2026-08-28). Numbers in
# `tt log ... <n>` and the picker stay stable; categories not listed here are
# appended after, most-used first.
CATEGORY_ORDER = [
    "Admin",
    "Org work/projects",
    "Work-related chats",
    "Personal",
    "Reading",
    "Social",
    "Fellow 1:1s",
    "Non-fellow meetings",
    "Team meetings",
]


def _known_values(db: Database, column: str) -> list[str]:
    """Distinct non-null values for a column from time_entry.

    Categories follow the pinned CATEGORY_ORDER (unpinned ones appended,
    most-used first); other columns are most-used first.
    """
    rows = db.conn.execute(
        f"SELECT {column}, COUNT(*) c FROM time_entry "
        f"WHERE {column} IS NOT NULL GROUP BY {column} ORDER BY c DESC"
    ).fetchall()
    values = [r[column] for r in rows]
    if column == "category":
        return CATEGORY_ORDER + [v for v in values if v not in CATEGORY_ORDER]
    return values


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
    known = _known_values(db, column)
    choices = [questionary.Choice(f"{i}: {v}", value=v) for i, v in enumerate(known)]
    choices += [NEW, SKIP]
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
    table.add_column("Category", no_wrap=True, max_width=16, overflow="ellipsis")
    table.add_column("What")

    rows = []
    for ev in db.list_calendar_events(start_iso, end_iso,
                                      excluded_color_ids=config.excluded_color_ids,
                                      excluded_event_types=config.excluded_event_types):
        rows.append((ev.start_ts, f"{_local(ev.start_ts)}-{_local(ev.end_ts)}",
                     "meeting", ev.category or "", ev.title))
    for e in db.list_entries(start_iso, end_iso):
        end = _local(e.end_ts) if e.end_ts else "…"
        rows.append((e.start_ts, f"{_local(e.start_ts)}-{end}",
                     e.source.value, e.category or "", e.description or ""))
    for g in backfill.find_day_gaps(db, config, target):
        rows.append((g.start, f"{_local(g.start)}-{_local(g.end)}",
                     "[yellow]gap[/yellow]", "", _fmt_dur(g.seconds)))

    for _, time_s, typ, cat, what in sorted(rows, key=lambda r: r[0]):
        table.add_row(time_s, typ, cat, what)
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

    # Category via pick list (always prompts, unlike _prompt_entry_fields which
    # short-circuits when a category is already set).
    NEW, KEEP = "✏  New…", f"— keep '{entry.category or '(none)'}' —"
    choices = _known_values(db, "category")
    if entry.category and entry.category not in choices:
        choices = [entry.category] + choices
    chosen = questionary.select("Category:", choices=[KEEP] + choices + [NEW]).ask()
    if chosen == NEW:
        typed = questionary.text("Enter category:").ask()
        entry.category = (typed or "").strip() or entry.category
    elif chosen and chosen != KEEP:
        entry.category = chosen

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
def recat(
    category: str = typer.Argument(..., help="Existing category to recategorize."),
    new: str = typer.Argument(None, help="Rename target. Omit for interactive per-entry reassign."),
):
    """Recategorize entries.

    `tt recat OLD NEW` bulk-renames every entry in OLD to NEW. With just
    `tt recat OLD`, interactively pick which of OLD's entries to move to another
    (or new) category — e.g. splitting "fellows" out of a broader chat category.
    """
    db = get_db()
    if new is not None:
        n = db.rename_category(category, new)
        console.print(f"[green]Renamed[/green] '{category}' → '{new}' ({n} entries)")
        return

    if not _is_interactive():
        console.print("[red]Interactive recat requires a terminal (or pass a rename target).[/red]")
        raise typer.Exit(1)

    entries = [e for e in db.list_entries()
               if (e.category or None) == category and e.end_ts is not None]
    if not entries:
        console.print(f"[yellow]No entries found in category '{category}'.[/yellow]")
        return
    labels = {
        f"{timeutil.local_date_key(e.start_ts)} {_local(e.start_ts)}-{_local(e.end_ts)}  "
        f"{e.description or ''}": e
        for e in entries
    }
    picked = questionary.checkbox("Select entries to move:", choices=list(labels)).ask()
    if not picked:
        console.print("Nothing selected.")
        return
    target = _pick_or_type(db, "Move to category:", "category", None)
    for label in picked:
        db.set_entry_category(labels[label].id, target)
    console.print(f"[green]Moved[/green] {len(picked)} entries to "
                  f"'{target or '(uncategorized)'}'")


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
    category_num: int = typer.Argument(
        None,
        help="Category number (as shown in the picker: 0 = most-used, 1 = next, …).",
    ),
    category: str = typer.Option(None, "--category", "-c"),
    date: str = typer.Option(None, "--date", help="ISO date for HH:MM times (default today)."),
):
    """Retrospectively log a past block, e.g. `tt log 09:30 10:30 "wrote spec" 0`.

    The trailing number is optional and picks a category by its number in the
    interactive pick list (most-used first). Also works interactively — omit
    description/category and you'll be prompted.
    """
    db = get_db()
    base = _resolve_date(date)
    start_ts = _parse_when(start, base)
    end_ts = _parse_when(end, base)
    if description is None and _is_interactive():
        description = questionary.text("What were you working on?").ask()
        description = (description or "").strip() or None
    description = description or "unspecified"
    if category is None and category_num is not None:
        known = _known_values(db, "category")
        if 0 <= category_num < len(known):
            category = known[category_num]
        else:
            console.print(f"[red]No category #{category_num} — known categories:[/red]")
            for i, v in enumerate(known):
                console.print(f"  {i}: {v}")
            raise typer.Exit(1)
    if category is None:
        category, _ = _prompt_entry_fields(db, None, "skip")
    try:
        e = backfill.fill_gap(db, start_ts, end_ts, description, category)
    except (ValueError, backfill.OverlapError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Logged[/green] {_local(start_ts)}-{_local(end_ts)} "
                  f"({_fmt_dur(e.duration_seconds)}) "
                  f"({category or 'uncategorized'}): {description}")


@app.command()
def report(
    period: str = typer.Argument("week", help="'week' (default) or 'day'."),
    text: bool = typer.Option(False, "--text", help="Print plain terminal tables instead of the HTML report."),
):
    """Summarise where time went (meeting vs focus vs idle).

    By default renders an offline HTML report (charts + per-day table) to
    ~/.time_tracker/reports/ and opens it in your browser. Use --text for a
    quick terminal-only summary (handy over SSH / when piping).
    """
    db = get_db()
    config = load_config()
    days = 7 if period == "week" else 1
    start = _today_local() - timedelta(days=days - 1)
    data = reports.gather_report(db, config, start, days)

    if not text:
        _write_html_report(period, data)
        return

    table = Table(title=f"Report — {data.period_label}")
    for col in ("Date", "Workday", "Meetings", "Focus", "Idle", "Frag."):
        table.add_column(col)
    for s in data.summaries:
        table.add_row(s.date, _fmt_dur(s.workday_seconds),
                      _fmt_dur(s.meeting_seconds), _fmt_dur(s.logged_seconds),
                      _fmt_dur(s.idle_seconds), f"{s.fragmentation:.1f}/h")
    console.print(table)
    if data.category_totals:
        cat = Table(title="By category")
        cat.add_column("Category")
        cat.add_column("Time")
        for k, v in sorted(data.category_totals.items(), key=lambda x: -x[1]):
            cat.add_row(k, _fmt_dur(v))
        console.print(cat)


def _write_html_report(period: str, data: "reports.ReportData") -> None:
    """Render an HTML report, save it under the data dir, and open it (if a TTY)."""
    import webbrowser
    from datetime import datetime as _dt

    from .core import charts

    reports_dir = DEFAULT_DB_PATH.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.now().strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"report-{period}-{stamp}.html"
    path.write_text(charts.build_report_html(data, load_config().category_groups))
    console.print(f"[green]Wrote[/green] {path}")
    if _is_interactive():
        webbrowser.open(path.as_uri())


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


# --- Short aliases -----------------------------------------------------------
# Register the same command functions under terse names for day-to-day brevity.
# Hidden so `--help` stays uncluttered; documented in docs/guide.html.
app.command(name="td", hidden=True)(day)
app.command(name="tl", hidden=True)(log)
app.command(name="ci", hidden=True)(checkin)
app.command(name="rc", hidden=True)(recat)


if __name__ == "__main__":
    app()
