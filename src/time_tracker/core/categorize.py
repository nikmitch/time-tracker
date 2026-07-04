"""Rule-based auto-categorization of meetings.

A rule maps a case-insensitive keyword found in a meeting title to a category.
Rules are ordered; the first match wins. Kept pure (no DB, no config I/O) so it
is trivially unit-testable and reusable by both sync and any future front-end.
"""

from __future__ import annotations

from typing import Optional


def categorize_meeting(title: str, rules: list[dict]) -> Optional[str]:
    """Return the category for ``title`` from the first matching rule, else None.

    Each rule is ``{"match": <substring>, "category": <name>}``. Matching is
    case-insensitive substring containment. Malformed rules are skipped.
    """
    hay = (title or "").lower()
    for rule in rules:
        needle = str(rule.get("match", "")).lower()
        category = rule.get("category")
        if needle and category and needle in hay:
            return category
    return None
