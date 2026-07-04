from time_tracker.core.charts import build_report_html
from time_tracker.core.reports import DaySummary, ReportData


def _summary(date, workday_h, meeting_h, focus_h, idle_h, gaps=2):
    return DaySummary(
        date=date,
        workday_seconds=workday_h * 3600,
        meeting_seconds=meeting_h * 3600,
        logged_seconds=focus_h * 3600,
        idle_seconds=idle_h * 3600,
        gap_count=gaps,
    )


def test_build_report_html_structure():
    data = ReportData(
        period_label="last 7 day(s)",
        summaries=[_summary("2026-06-28", 8, 1, 5, 2)],
        category_totals={"dev": 7200, "Team meetings": 3600},
    )
    out = build_report_html(data)
    assert out.startswith("<!DOCTYPE html>")
    assert "dev" in out and "Team meetings" in out
    assert "<svg" in out                 # charts embedded inline
    assert "2026-06-28" in out           # per-day table present
    assert "last 7 day(s)" in out


def test_build_report_html_handles_empty():
    data = ReportData(period_label="last 1 day(s)", summaries=[], category_totals={})
    out = build_report_html(data)
    assert out.startswith("<!DOCTYPE html>")
    assert "No data to chart" in out
