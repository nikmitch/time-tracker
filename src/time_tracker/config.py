"""User configuration, persisted as TOML at ``~/.time_tracker/config.toml``.

Kept separate from the SQLite store: config is small, human-editable, and not
something we query over time.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".time_tracker" / "config.toml"


def _render_toml(value) -> str:
    """Serialize a Python value to a TOML fragment (recursive; inline tables)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_render_toml(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_render_toml(v) for v in value) + "]"
    raise TypeError(f"Cannot render {type(value)!r} to TOML")


@dataclass
class Config:
    """User-tunable settings with sensible defaults."""

    # Daily clock-in reminder time (24h "HH:MM"), local time.
    clock_in_reminder_time: str = "09:00"
    # Periodic check-in interval, in minutes (0 disables).
    checkin_interval_minutes: int = 45
    # Google Calendar colorIds to treat as non-meetings (4 = pink/Flamingo).
    excluded_color_ids: list[str] = field(default_factory=lambda: ["4"])
    # Google Calendar eventTypes to exclude (workingLocation = "Office/WFH" markers).
    excluded_event_types: list[str] = field(default_factory=lambda: ["workingLocation", "focusTime"])
    # Soft work-hours window for views/inference fallback (local "HH:MM").
    work_hours_start: str = "08:00"
    work_hours_end: str = "18:00"
    # Rules that auto-tag meetings on sync (first match wins). Each rule is
    # {"color": <colorId>, "match": <title substring>, "min_attendees": <int>,
    # "max_attendees": <int>, "category": <name>} where every key except category
    # is optional; a rule with no matchers is a catch-all.
    meeting_category_rules: list[dict] = field(default_factory=list)
    # Two-level taxonomy: broad groups that roll up fine categories for report
    # subtotals + shaded colouring. Each entry is
    # {"group": <name>, "color": <hex>, "categories": [<category>, ...]}.
    # Categories not listed in any group fall into an "Other" band.
    category_groups: list[dict] = field(default_factory=list)

    def to_toml(self) -> str:
        lines = ["# Time Tracker configuration", ""]
        for key, value in asdict(self).items():
            lines.append(f"{key} = {_render_toml(value)}")
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
