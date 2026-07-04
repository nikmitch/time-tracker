"""Rule-based auto-categorization of meetings.

A rule assigns a ``category`` to a meeting when its matchers all match. The
supported matchers may be combined within a rule:

  * ``color``          — the Google Calendar ``colorId`` (exact match; the
                         user's primary organising signal).
  * ``match``          — a case-insensitive substring of the meeting title.
  * ``min_attendees``  — the meeting has at least this many attendees.
  * ``max_attendees``  — the meeting has at most this many attendees.

A rule with **no** matchers is a catch-all that applies to anything (put it
last). Rules are evaluated in order; the first match wins. Kept pure (no DB, no
config I/O) so it is trivially unit-testable and reusable by any front-end.
"""

from __future__ import annotations

from typing import Optional


def categorize_meeting(
    title: str,
    color_id: Optional[str],
    attendees_count: int,
    rules: list[dict],
) -> Optional[str]:
    """Return the category from the first matching rule, else ``None``.

    Each rule is ``{"color", "match", "min_attendees", "max_attendees",
    "category"}`` where every key except ``category`` is optional. A rule
    without a category is skipped.
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
        lo = rule.get("min_attendees")
        if lo is not None and attendees_count < int(lo):
            continue
        hi = rule.get("max_attendees")
        if hi is not None and attendees_count > int(hi):
            continue
        return category
    return None
