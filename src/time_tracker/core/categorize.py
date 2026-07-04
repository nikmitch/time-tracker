"""Rule-based auto-categorization of meetings.

A rule assigns a ``category`` to a meeting when its matchers all match. Two
matchers are supported and may be combined:

  * ``color``  — the Google Calendar ``colorId`` (exact match; the user's
                 primary organising signal).
  * ``match``  — a case-insensitive substring of the meeting title.

A rule with **neither** matcher is a catch-all that applies to anything (put it
last). Rules are evaluated in order; the first match wins. Kept pure (no DB, no
config I/O) so it is trivially unit-testable and reusable by any front-end.
"""

from __future__ import annotations

from typing import Optional


def categorize_meeting(
    title: str, color_id: Optional[str], rules: list[dict]
) -> Optional[str]:
    """Return the category from the first matching rule, else ``None``.

    Each rule is ``{"color": <id>, "match": <substring>, "category": <name>}``
    where ``color`` and/or ``match`` are optional. A rule without a category is
    skipped.
    """
    hay = (title or "").lower()
    for rule in rules:
        category = rule.get("category")
        if not category:
            continue
        color = rule.get("color")
        if color is not None and str(color) != str(color_id):
            continue
        needle = str(rule.get("match", "")).lower()
        if needle and needle not in hay:
            continue
        return category
    return None
