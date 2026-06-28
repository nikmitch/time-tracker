"""User configuration, persisted as TOML at ``~/.time_tracker/config.toml``.

Kept separate from the SQLite store: config is small, human-editable, and not
something we query over time.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".time_tracker" / "config.toml"


@dataclass
class Config:
    """User-tunable settings with sensible defaults."""

    # Daily clock-in reminder time (24h "HH:MM"), local time.
    clock_in_reminder_time: str = "09:00"
    # Periodic check-in interval, in minutes (0 disables).
    checkin_interval_minutes: int = 45
    # Google Calendar colorIds to treat as non-meetings (4 = pink/Flamingo).
    excluded_color_ids: list[str] = field(default_factory=lambda: ["4"])
    # Soft work-hours window for views/inference fallback (local "HH:MM").
    work_hours_start: str = "08:00"
    work_hours_end: str = "18:00"

    def to_toml(self) -> str:
        lines = ["# Time Tracker configuration", ""]
        for key, value in asdict(self).items():
            if isinstance(value, list):
                rendered = "[" + ", ".join(f'"{v}"' for v in value) + "]"
            elif isinstance(value, str):
                rendered = f'"{value}"'
            else:
                rendered = str(value)
            lines.append(f"{key} = {rendered}")
        return "\n".join(lines) + "\n"


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Load config from TOML, falling back to defaults for missing keys."""
    path = Path(path)
    if not path.exists():
        return Config()
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    known = {f for f in Config().__dataclass_fields__}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in data.items() if k in known}
    return Config(**filtered)


def save_config(config: Config, path: Path | str = DEFAULT_CONFIG_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.to_toml())
