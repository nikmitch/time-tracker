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
from typing import Optional

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow use("Agg"))

from .reports import DaySummary, ReportData, grouped_breakdown  # noqa: E402


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


def _shades(base_hex: str, n: int) -> list[str]:
    """``n`` distinguishable shades of ``base_hex`` (same hue, varied lightness)."""
    import colorsys

    base_hex = base_hex.lstrip("#")
    r, g, b = (int(base_hex[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if n == 1:
        lights = [l]
    else:
        lo, hi = max(0.30, l - 0.18), min(0.80, l + 0.20)
        lights = [hi - (hi - lo) * i / (n - 1) for i in range(n)]  # light→dark
    out = []
    for li in lights:
        rr, gg, bb = colorsys.hls_to_rgb(h, li, s)
        out.append(f"#{int(rr*255):02x}{int(gg*255):02x}{int(bb*255):02x}")
    return out


def category_color_map(groups: list[dict]) -> dict[str, str]:
    """Stable colour per fine category: a shade of its group's base hue.

    Keyed on the full configured category list (not just what appears in a given
    period) so a category's colour never shifts week to week.
    """
    cmap: dict[str, str] = {}
    for g in groups:
        cats = g.get("categories", [])
        for cat, shade in zip(cats, _shades(g.get("color", "#888780"), len(cats))):
            cmap[cat] = shade
    return cmap


def render_grouped_category_bar(grouped: list[dict], color_map: dict[str, str]):
    """Horizontal bars grouped by band, each band's subcategories in shades.

    ``grouped`` is the output of :func:`reports.grouped_breakdown`. Bands are
    stacked top-to-bottom in config order; a bold group subtotal label sits to
    the right of each band.
    """
    labels: list[str] = []
    values: list[float] = []
    colors: list[str] = []
    group_spans: list[tuple[str, float, str, int, int]] = []  # name, subtotal, color, lo, hi
    for band in grouped:
        fallback = _shades(band["color"], len(band["items"]))
        lo = len(labels)
        for (cat, secs), shade in zip(band["items"], fallback):
            labels.append(cat)
            values.append(secs / 3600)
            colors.append(color_map.get(cat, shade))
        group_spans.append((band["group"], band["subtotal"], band["color"], lo, len(labels)))

    total = sum(values) or 1.0
    ypos = list(range(len(labels)))[::-1]  # first band at the top
    fig, ax = plt.subplots(figsize=(8.5, max(2.5, 0.46 * len(labels) + 1.2)))
    bars = ax.barh(ypos, values, color=colors)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels)
    ax.set_xlabel("hours")
    ax.set_title("Time by category (grouped)")
    for bar, secs in zip(bars, [v * 3600 for v in values]):
        ax.text(bar.get_width() + total * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{_fmt_dur(secs)}  ({bar.get_width()/total*100:.0f}%)",
                va="center", fontsize=8.5)
    # Group subtotal labels down the right edge, in the band's colour.
    for name, subtotal, color, lo, hi in group_spans:
        y_mid = (ypos[lo] + ypos[hi - 1]) / 2
        ax.text(1.06, y_mid, f"{name}\n{_fmt_dur(subtotal)}",
                transform=ax.get_yaxis_transform(), va="center", ha="left",
                fontsize=9, fontweight="bold", color=color)
    ax.margins(x=0.22)
    fig.subplots_adjust(right=0.78)
    return fig


_IDLE_COLOR = "#c9c7bd"
_LEFTOVER_COLOR = "#b0aea6"


def _ordered_present(daily: list[dict], groups: list[dict]) -> list[str]:
    """Categories in config order, restricted to those present in ``daily``."""
    present: set[str] = set()
    for d in daily:
        present.update(d["categories"].keys())
    ordered = [c for g in groups for c in g.get("categories", []) if c in present]
    leftovers = sorted(c for c in present if c not in ordered)
    return ordered + leftovers


def render_daily_breakdown(daily: list[dict], groups: list[dict], color_map: dict[str, str]):
    """Per-day stacked bar, coloured by the grouped taxonomy + an Idle cap.

    Segments follow config category order (so a group's shades cluster within
    each bar); the legend lists groups by base hue plus Idle.
    """
    from matplotlib.patches import Patch

    dates = [d["date"] for d in daily]
    ordered = _ordered_present(daily, groups)

    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    bottoms = [0.0] * len(dates)
    for cat in ordered:
        vals = [d["categories"].get(cat, 0) / 3600 for d in daily]
        ax.bar(dates, vals, bottom=bottoms, width=0.8,
               color=color_map.get(cat, _LEFTOVER_COLOR))
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    idle = [d["idle"] / 3600 for d in daily]
    ax.bar(dates, idle, bottom=bottoms, width=0.8, color=_IDLE_COLOR)

    ax.set_ylabel("hours")
    ax.set_title("Each day, by category group")
    present = set(ordered)
    handles = [Patch(color=g.get("color", _LEFTOVER_COLOR), label=g["group"])
               for g in groups if any(c in present for c in g.get("categories", []))]
    handles.append(Patch(color=_IDLE_COLOR, label="Idle"))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0),
              fontsize=8.5, frameon=False)
    fig.autofmt_xdate(rotation=30)
    fig.subplots_adjust(right=0.82)
    return fig


def _grouped_table_html(grouped: list[dict], total: float) -> str:
    denom = total or 1.0
    rows = []
    for band in grouped:
        rows.append(
            f'<tr class="grp"><td>{html.escape(band["group"])}</td>'
            f'<td>{_fmt_dur(band["subtotal"])}</td>'
            f'<td>{band["subtotal"] / denom * 100:.0f}%</td></tr>'
        )
        for cat, secs in band["items"]:
            rows.append(
                f'<tr><td class="ind">{html.escape(cat)}</td>'
                f'<td>{_fmt_dur(secs)}</td><td>{secs / denom * 100:.0f}%</td></tr>'
            )
    rows.append(f'<tr class="tot"><td>Total</td><td>{_fmt_dur(total)}</td><td>100%</td></tr>')
    body = "".join(rows) or '<tr><td colspan="3">No categorized time.</td></tr>'
    return ("<table><thead><tr><th>Category</th><th>Time</th><th>Share</th></tr>"
            f"</thead><tbody>{body}</tbody></table>")


def _by_day_table_html(summaries: list[DaySummary]) -> str:
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
h2 { font-weight: 500; font-size: 18px; margin-top: 2rem; }
.sub { color: #666; margin-bottom: 1.5rem; }
figure { margin: 1.5rem 0; }
svg { max-width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin-top: 1rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e5e5e5; }
th { color: #666; font-weight: 500; }
tr.grp td { font-weight: 500; }
td.ind { padding-left: 28px; color: #555; }
tr.tot td { font-weight: 500; border-top: 2px solid #ccc; }
"""


def build_report_html(data: ReportData, groups: Optional[list[dict]] = None) -> str:
    """Assemble a complete, self-contained HTML report for ``data``."""
    groups = groups or []
    total = sum(data.category_totals.values())
    grouped = grouped_breakdown(data.category_totals, groups)
    color_map = category_color_map(groups)

    charts = ""
    if grouped:
        charts += f"<figure>{_fig_to_svg(render_grouped_category_bar(grouped, color_map))}</figure>"
    if data.daily:
        charts += f"<figure>{_fig_to_svg(render_daily_breakdown(data.daily, groups, color_map))}</figure>"
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
        f"<h2>By category</h2>{_grouped_table_html(grouped, total)}"
        f"<h2>By day</h2>{_by_day_table_html(data.summaries)}"
        "</body></html>"
    )
