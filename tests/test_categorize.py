from time_tracker.core.categorize import categorize_meeting

# Colour taxonomy with a headcount catch-all for team meetings at the bottom.
RULES = [
    {"match": "fellow", "category": "fellows"},
    {"color": "3", "category": "Fellow 1:1s"},
    {"color": "6", "category": "Non-fellow meetings"},
    {"color": "10", "category": "Stream meetings"},
    {"min_attendees": 3, "category": "Team meetings"},
]


def test_matches_by_color():
    assert categorize_meeting("Mike <> Nik", "3", 2, RULES) == "Fellow 1:1s"
    assert categorize_meeting("Control chat", "6", 2, RULES) == "Non-fellow meetings"
    assert categorize_meeting("MATS stream", "10", 15, RULES) == "Stream meetings"


def test_title_rule_wins_over_colour():
    assert categorize_meeting("fellows research", "6", 2, RULES) == "fellows"


def test_headcount_catch_all_tags_team_meetings():
    # Uncoloured big meeting → Team meetings via min_attendees.
    assert categorize_meeting("MATS Full Team Meeting", None, 68, RULES) == "Team meetings"
    assert categorize_meeting("London Standup", None, 7, RULES) == "Team meetings"


def test_small_uncoloured_stays_untagged():
    assert categorize_meeting("Fellow status", None, 0, RULES) == "fellows"  # title rule
    assert categorize_meeting("Solo block", None, 0, RULES) is None
    assert categorize_meeting("Quick sync", None, 2, RULES) is None


def test_colour_wins_over_headcount_for_large_streams():
    # A 15-person stream keeps its colour category, not "Team meetings".
    assert categorize_meeting("MATS stream", "10", 15, RULES) == "Stream meetings"


def test_min_and_max_attendees_bounds():
    rules = [{"min_attendees": 2, "max_attendees": 4, "category": "small group"}]
    assert categorize_meeting("x", None, 1, rules) is None
    assert categorize_meeting("x", None, 3, rules) == "small group"
    assert categorize_meeting("x", None, 5, rules) is None


def test_case_insensitive_title_match():
    assert categorize_meeting("weekly FELLOW sync", "6", 2, RULES) == "fellows"


def test_catch_all_rule_matches_anything():
    rules = [{"color": "3", "category": "a"}, {"category": "everything else"}]
    assert categorize_meeting("random", None, 0, rules) == "everything else"
    assert categorize_meeting("x", "3", 2, rules) == "a"


def test_no_category_rule_skipped():
    rules = [{"color": "6"}, {"color": "6", "category": "ok"}]
    assert categorize_meeting("x", "6", 2, rules) == "ok"
