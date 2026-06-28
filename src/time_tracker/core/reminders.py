"""macOS launchd LaunchAgents for clock-in and check-in reminders.

Plist generation is pure (returns the dict/XML) so it can be unit-tested; the
install/uninstall helpers write the files and (un)load them via launchctl.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

from ..config import Config

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
CLOCK_IN_LABEL = "com.nikmitchell.timetracker.clockin"
CHECKIN_LABEL = "com.nikmitchell.timetracker.checkin"


def _tt_command(subcommand: str) -> list[str]:
    """Invoke our CLI via the current interpreter so the env is correct."""
    return [sys.executable, "-m", "time_tracker.cli", subcommand]


def clock_in_plist(hour: int, minute: int, program_args: list[str] | None = None) -> dict:
    """Daily reminder at a fixed wall-clock time."""
    return {
        "Label": CLOCK_IN_LABEL,
        "ProgramArguments": program_args or _tt_command("remind-clock-in"),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": False,
    }


def checkin_plist(interval_minutes: int, program_args: list[str] | None = None) -> dict:
    """Periodic reminder every N minutes."""
    return {
        "Label": CHECKIN_LABEL,
        "ProgramArguments": program_args or _tt_command("remind-checkin"),
        "StartInterval": interval_minutes * 60,
        "RunAtLoad": False,
    }


def plist_to_xml(plist: dict) -> bytes:
    return plistlib.dumps(plist)


def install_reminders(config: Config, agents_dir: Path = LAUNCH_AGENTS_DIR) -> list[Path]:
    """Write (and load) the LaunchAgent plists. Returns the paths written."""
    agents_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    hour, minute = (int(x) for x in config.clock_in_reminder_time.split(":"))
    plans = [(CLOCK_IN_LABEL, clock_in_plist(hour, minute))]
    if config.checkin_interval_minutes > 0:
        plans.append((CHECKIN_LABEL, checkin_plist(config.checkin_interval_minutes)))

    for label, plist in plans:
        path = agents_dir / f"{label}.plist"
        path.write_bytes(plist_to_xml(plist))
        subprocess.run(["launchctl", "unload", str(path)], check=False,
                       capture_output=True)
        subprocess.run(["launchctl", "load", str(path)], check=False,
                       capture_output=True)
        written.append(path)
    return written


def uninstall_reminders(agents_dir: Path = LAUNCH_AGENTS_DIR) -> list[Path]:
    removed: list[Path] = []
    for label in (CLOCK_IN_LABEL, CHECKIN_LABEL):
        path = agents_dir / f"{label}.plist"
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], check=False,
                           capture_output=True)
            path.unlink()
            removed.append(path)
    return removed
