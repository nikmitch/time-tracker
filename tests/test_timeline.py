from datetime import datetime, timezone

from time_tracker.core.timeline import (
    Interval,
    find_gaps,
    merge_intervals,
    overlaps,
)

UTC = timezone.utc


def iv(h1, h2):
    return Interval(datetime(2026, 6, 28, h1, tzinfo=UTC), datetime(2026, 6, 28, h2, tzinfo=UTC))


def test_overlaps():
    assert overlaps(iv(9, 11), iv(10, 12))
    assert not overlaps(iv(9, 10), iv(10, 11))  # half-open, touching != overlap


def test_merge():
    merged = merge_intervals([iv(9, 10), iv(10, 11), iv(13, 14)])
    assert merged == [iv(9, 11), iv(13, 14)]


def test_find_gaps_basic():
    gaps = find_gaps(iv(8, 18), [iv(9, 10), iv(13, 14)])
    assert gaps == [iv(8, 9), iv(10, 13), iv(14, 18)]


def test_find_gaps_full_coverage():
    assert find_gaps(iv(8, 18), [iv(8, 18)]) == []


def test_find_gaps_min_seconds_filters_small():
    gaps = find_gaps(iv(8, 10), [iv(8, 9), iv(9, 10)])
    assert gaps == []


def test_find_gaps_clips_busy_outside_window():
    gaps = find_gaps(iv(9, 12), [iv(7, 10), iv(11, 13)])
    assert gaps == [iv(10, 11)]
