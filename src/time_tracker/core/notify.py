"""Native macOS notifications.

Command construction is separated from execution so it can be unit-tested
without popping real banners.
"""

from __future__ import annotations

import shutil
import subprocess


def build_notify_command(title: str, message: str, has_terminal_notifier: bool) -> list[str]:
    """Build the shell command for a banner.

    Prefers ``terminal-notifier`` (nicer, clickable); falls back to
    ``osascript`` which is always present on macOS.
    """
    if has_terminal_notifier:
        return ["terminal-notifier", "-title", title, "-message", message]
    script = f'display notification {message!r} with title {title!r}'
    return ["osascript", "-e", script]


def notify(title: str, message: str) -> None:
    has_tn = shutil.which("terminal-notifier") is not None
    cmd = build_notify_command(title, message, has_tn)
    subprocess.run(cmd, check=False)
