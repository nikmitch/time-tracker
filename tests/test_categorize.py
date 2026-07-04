from time_tracker.core.categorize import categorize_meeting

# Colour-first taxonomy with a title exception on top and no catch-all.
RULES = [
    {"match": "fellow", "category": "fellows"},
    {"color": "3", "category": "fellow 1:1s"},
    {"color": "6", "category": "non-fellow meetings"},
    {"color": "10", "category": "stream meetings"},
]


def test_matches_by_color():
    assert categorize_meeting("Mike <> Nik", "3", RULES) == "fellow 1:1s"
    assert categorize_meeting("Control chat", "6", RULES) == "non-fellow meetings"
    assert categorize_meeting("MATS Marius stream", "10", RULES) == "stream meetings"


def test_title_rule_wins_over_colour():
    # A colour-6 meeting whose title mentions "fellow" is skimmed out first.
    assert categorize_meeting("fellows research", "6", RULES) == "fellows"


def test_unmatched_colour_stays_untagged():
    assert categorize_meeting("Lunch", "8", RULES) is None
    assert categorize_meeting("Office", None, RULES) is None


def test_case_insensitive_title_match():
    assert categorize_meeting("weekly FELLOW sync", "6", RULES) == "fellows"


def test_catch_all_rule_matches_anything():
    rules = [{"color": "3", "category": "a"}, {"category": "everything else"}]
    assert categorize_meeting("random", None, rules) == "everything else"
    assert categorize_meeting("x", "3", rules) == "a"


def test_combined_color_and_match():
    rules = [{"color": "6", "match": "control", "category": "control-chats"}]
    assert categorize_meeting("Control chat", "6", rules) == "control-chats"
    assert categorize_meeting("Control chat", "3", rules) is None  # colour differs
    assert categorize_meeting("Other", "6", rules) is None  # title differs


def test_no_category_rule_skipped():
    rules = [{"color": "6"}, {"color": "6", "category": "ok"}]
    assert categorize_meeting("x", "6", rules) == "ok"
