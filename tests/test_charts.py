from time_tracker.core.charts import build_report_html, category_color_map
from time_tracker.core.reports import DaySummary, ReportData

GROUPS = [
    {"group": "Meetings", "color": "#2a78d6",
     "categories": ["Team meetings", "Fellow 1:1s"]},
    {"group": "Admin", "color": "#eda100", "categories": ["Admin"]},
]


def _summary(date, workday_h, meeting_h, focus_h, idle_h, gaps=2):
    return DaySummary(
        date=date,
        workday_seconds=workday_h * 3600,
        meeting_seconds=meeting_h * 3600,
        logged_seconds=focus_h * 3600,
        idle_seconds=idle_h * 3600,
        gap_count=gaps,
    )


def _data():
    return ReportData(
        period_label="last 7 day(s)",
        summaries=[_summary("2026-06-28", 8, 1, 5, 2)],
        category_totals={"Team meetings": 3600, "Admin": 7200, "Reading": 1800},
        daily=[{"date": "2026-06-28",
                "categories": {"Team meetings": 3600, "Admin": 7200}, "idle": 7200}],
    )


def test_color_map_shades_within_group():
    cmap = category_color_map(GROUPS)
    assert set(cmap) == {"Team meetings", "Fellow 1:1s", "Admin"}
    # Two meeting types get different shades of the same base hue.
    assert cmap["Team meetings"] != cmap["Fellow 1:1s"]


def test_build_report_html_structure():
    out = build_report_html(_data(), GROUPS)
    assert out.startswith("<!DOCTYPE html>")
    assert "<svg" in out                       # charts embedded inline
    assert "Meetings" in out and "Admin" in out  # group subtotals in table
    assert "Team meetings" in out              # fine subcategory rows
    assert "Reading" in out                    # ungrouped → Other band
    assert "2026-06-28" in out                 # by-day table


def test_build_report_html_handles_empty():
    data = ReportData(period_label="last 1 day(s)", summaries=[],
                      category_totals={}, daily=[])
    out = build_report_html(data, GROUPS)
    assert out.startswith("<!DOCTYPE html>")
    assert "No data to chart" in out
