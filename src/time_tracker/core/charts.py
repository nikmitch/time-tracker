"""Matplotlib rendering of a report into a self-contained HTML page.

Kept separate from the pure aggregation in :mod:`reports` so the numbers are
verifiable without importing matplotlib, and the chart layer stays swappable.
Figures are embedded as inline SVG so the report is a single offline file — no
image sidecars, no CDN.

The Agg backend is selected on import so rendering works headless and
deterministically (no display server needed).
"""

from __future__ import annotations

import html
import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow use("Agg"))

from .reports import DaySummary, ReportData  # noqa: E402


def _fmt_dur(seconds: float) -> str:
    """Human duration like ``2h05m`` / ``45m`` (mirrors the CLI formatter)."""
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fig_to_svg(fig) -> str:
    """Serialize a figure to an inline ``<svg>`` string and close it."""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    svg = buf.getvalue()
    # Drop the XML/doctype preamble so the <svg> embeds cleanly inside HTML.
    return svg[svg.index("<svg"):]


def render_category_bar(category_totals: dict[str, float]):
    """Horizontal bar chart of hours per category, largest at the top."""
    items = sorted(category_totals.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    hours = [v / 3600 for _, v in items]
    total = sum(hours) or 1.0

    fig, ax = plt.subplots(figsize=(8, max(2.0, 0.5 * len(labels) + 1)))
    bars = ax.barh(labels, hours, color="#2a78d6")
    ax.set_xlabel("hours")
    ax.set_title("Time by category")
    for bar, secs in zip(bars, [v for _, v in items]):
        pct = bar.get_width() / total * 100
        ax.text(bar.get_width() + total * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{_fmt_dur(secs)}  ({pct:.0f}%)", va="center", fontsize=9)
    ax.margins(x=0.18)
    fig.tight_layout()
    return fig


def render_daily_breakdown(summaries: list[DaySummary]):
    """Per-day stacked bar: meetings / focus / idle hours."""
    dates = [s.date for s in summaries]
    meetings = [s.meeting_seconds / 3600 for s in summaries]
    focus = [s.logged_seconds / 3600 for s in summaries]
    idle = [s.idle_seconds / 3600 for s in summaries]

    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(dates, meetings, label="Meetings", color="#2a78d6")
    ax.bar(dates, focus, bottom=meetings, label="Focus", color="#1baf7a")
    bottom2 = [m + f for m, f in zip(meetings, focus)]
    ax.bar(dates, idle, bottom=bottom2, label="Idle", color="#c9c7bd")
    ax.set_ylabel("hours")
    ax.set_title("Each day: meetings vs focus vs idle")
    ax.legend(loc="upper right", fontsize=9, frameon=False)
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    return fig


def _table_html(summaries: list[DaySummary]) -> str:
    cols = ("Date", "Workday", "Meetings", "Focus", "Idle", "Frag.")
    head = "".join(f"<th>{c}</th>" for c in cols)
    rows = []
    for s in summaries:
        cells = (
            s.date, _fmt_dur(s.workday_seconds), _fmt_dur(s.meeting_seconds),
            _fmt_dur(s.logged_seconds), _fmt_dur(s.idle_seconds),
            f"{s.fragmentation:.1f}/h",
        )
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in cells) + "</tr>")
    body = "".join(rows) or '<tr><td colspan="6">No framed days in this period.</td></tr>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


_CSS = """
body { font-family: system-ui, -apple-system, sans-serif; margin: 2rem auto;
       max-width: 900px; color: #1a1a1a; }
h1 { font-weight: 500; font-size: 22px; }
.sub { color: #666; margin-bottom: 1.5rem; }
figure { margin: 1.5rem 0; }
svg { max-width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin-top: 1rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e5e5; }
th { color: #666; font-weight: 500; }
"""


def build_report_html(data: ReportData) -> str:
    """Assemble a complete, self-contained HTML report for ``data``."""
    total = sum(data.category_totals.values())
    charts = ""
    if data.category_totals:
        charts += f"<figure>{_fig_to_svg(render_category_bar(data.category_totals))}</figure>"
    if data.summaries:
        charts += f"<figure>{_fig_to_svg(render_daily_breakdown(data.summaries))}</figure>"
    if not charts:
        charts = "<p>No data to chart for this period.</p>"
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>Time report — {html.escape(data.period_label)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<h1>Time report</h1>"
        f"<div class=\"sub\">{html.escape(data.period_label)} · "
        f"{_fmt_dur(total)} tracked across {len(data.category_totals)} categories</div>"
        f"{charts}"
        f"<h2 style=\"font-weight:500;font-size:18px\">By day</h2>"
        f"{_table_html(data.summaries)}"
        "</body></html>"
    )
