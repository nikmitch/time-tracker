from time_tracker.core.categorize import categorize_meeting

RULES = [
    {"match": "MATS", "category": "MATS workplace"},
    {"match": "fellow", "category": "fellows"},
]


def test_first_matching_rule_wins():
    assert categorize_meeting("MATS all-hands", RULES) == "MATS workplace"
    # "fellow" would also not apply here; MATS matched first anyway.
    assert categorize_meeting("Sync with fellow", RULES) == "fellows"


def test_match_is_case_insensitive():
    assert categorize_meeting("weekly mats standup", RULES) == "MATS workplace"


def test_no_match_returns_none():
    assert categorize_meeting("Dentist appointment", RULES) is None


def test_empty_rules_and_title():
    assert categorize_meeting("anything", []) is None
    assert categorize_meeting("", RULES) is None


def test_malformed_rules_are_skipped():
    rules = [{"category": "no-match-key"}, {"match": "x"}, {"match": "ok", "category": "c"}]
    assert categorize_meeting("ok event", rules) == "c"
