import pytest
from typer.testing import CliRunner

from time_tracker.cli import app

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point the CLI at a temp DB."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("TIMETRACKER_DB", str(db_path))
    return db_path


def test_start_and_stop(env):
    r = runner.invoke(app, ["start", "-c", "dev"])
    assert r.exit_code == 0
    assert "Started" in r.stdout
    r = runner.invoke(app, ["stop"])
    assert r.exit_code == 0
    assert "logged" in r.stdout


def test_double_start_errors(env):
    runner.invoke(app, ["start"])
    r = runner.invoke(app, ["start"])
    assert r.exit_code == 1


def test_stop_without_timer_errors(env):
    r = runner.invoke(app, ["stop"])
    assert r.exit_code == 1


def test_checkin(env):
    r = runner.invoke(app, ["checkin", "emails"])
    assert r.exit_code == 0
    assert "Checked in" in r.stdout


def test_clock_in_out(env):
    assert runner.invoke(app, ["in"]).exit_code == 0
    assert runner.invoke(app, ["out"]).exit_code == 0


def test_day_view(env):
    runner.invoke(app, ["start", "-d", "writing"])
    runner.invoke(app, ["stop"])
    r = runner.invoke(app, ["day"])
    assert r.exit_code == 0
    assert "Timeline" in r.stdout


def test_report_text_mode(env):
    runner.invoke(app, ["in"])
    runner.invoke(app, ["start", "-c", "dev"])
    runner.invoke(app, ["stop"])
    r = runner.invoke(app, ["report", "day", "--text"])
    assert r.exit_code == 0
    assert "Report" in r.stdout


def test_report_defaults_to_html(env, monkeypatch):
    import time_tracker.cli as cli
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    # Point the reports dir at the temp DB's parent (env fixture's tmp dir).
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", env)
    runner.invoke(app, ["in"])
    runner.invoke(app, ["log", "09:00", "10:00", "spec", "-c", "dev"])
    runner.invoke(app, ["out"])
    r = runner.invoke(app, ["report", "week"])  # no flag → HTML by default
    assert r.exit_code == 0
    assert "Wrote" in r.stdout
    reports_dir = env.parent / "reports"
    files = list(reports_dir.glob("report-week-*.html"))
    assert files, "no HTML report written"
    content = files[0].read_text()
    assert content.startswith("<!DOCTYPE html>")
    assert "dev" in content
    assert opened == []  # non-TTY under CliRunner: file written, browser not opened


def test_help(env):
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "checkin" in r.stdout


def test_log_retrospective(env):
    r = runner.invoke(app, ["log", "09:30", "10:30", "wrote spec", "-c", "dev"])
    assert r.exit_code == 0
    assert "Logged" in r.stdout


def test_log_category_number(env):
    # 0 maps to the first pinned category regardless of DB contents.
    r = runner.invoke(app, ["log", "09:00", "09:30", "emails", "0"])
    assert r.exit_code == 0
    assert "(Admin)" in r.stdout


def test_log_category_number_out_of_range(env):
    r = runner.invoke(app, ["log", "09:00", "09:30", "emails", "42"])
    assert r.exit_code == 1
    assert "0: Admin" in r.stdout


def test_unpinned_categories_appended_after_pinned(env):
    from time_tracker.cli import CATEGORY_ORDER, _known_values, get_db
    runner.invoke(app, ["log", "09:00", "10:00", "x", "-c", "zzz-new"])
    known = _known_values(get_db(), "category")
    assert known[: len(CATEGORY_ORDER)] == CATEGORY_ORDER
    assert known[len(CATEGORY_ORDER)] == "zzz-new"


def test_log_prints_category(env):
    r = runner.invoke(app, ["log", "09:30", "10:30", "wrote spec", "-c", "dev"])
    assert "(dev)" in r.stdout


def test_log_infers_start_from_last_entry(env):
    runner.invoke(app, ["log", "09:00", "10:00", "first", "-c", "dev"])
    r = runner.invoke(app, ["log", "10:30", "second", "-c", "dev"])
    assert r.exit_code == 0
    assert "Start inferred as 10:00" in r.stdout
    assert "10:00-10:30" in r.stdout


def test_log_infers_start_with_category_number(env):
    runner.invoke(app, ["log", "09:00", "10:00", "first", "-c", "dev"])
    r = runner.invoke(app, ["log", "10:30", "second", "3"])
    assert r.exit_code == 0
    assert "(Personal)" in r.stdout
    assert "10:00-10:30" in r.stdout


def test_log_infers_start_without_description(env):
    runner.invoke(app, ["log", "09:00", "10:00", "first", "-c", "dev"])
    r = runner.invoke(app, ["log", "10:30", "3"])
    assert r.exit_code == 0
    assert "(Personal)" in r.stdout
    assert "unspecified" in r.stdout


def test_log_infers_start_from_last_meeting(env):
    """A synced meeting counts as 'the last thing I had', not just entries."""
    from time_tracker.cli import get_db, _resolve_date, _parse_when
    from time_tracker.models import CalendarEvent
    db = get_db()
    base = _resolve_date(None)
    runner.invoke(app, ["log", "09:00", "09:30", "first", "-c", "dev"])
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="evt1", title="standup",
        start_ts=_parse_when("09:30", base), end_ts=_parse_when("10:15", base),
    ))
    r = runner.invoke(app, ["log", "11:00", "after the meeting", "-c", "dev"])
    assert r.exit_code == 0
    assert "Start inferred as 10:15" in r.stdout


def test_log_end_only_skips_anchor_ending_exactly_at_end(env):
    """A meeting ending exactly at END leaves no gap — anchor further back."""
    from time_tracker.cli import get_db, _resolve_date, _parse_when
    from time_tracker.models import CalendarEvent
    db = get_db()
    base = _resolve_date(None)
    runner.invoke(app, ["log", "11:30", "12:00", "admin", "-c", "dev"])
    db.upsert_calendar_event(CalendarEvent(
        gcal_id="fred", title="Nik / Fred",
        start_ts=_parse_when("11:30", base), end_ts=_parse_when("12:15", base),
    ))
    r = runner.invoke(app, ["log", "12:15", "chats with Katie", "-c", "dev"])
    assert r.exit_code == 0
    assert "Start inferred as 12:00" in r.stdout
    assert "12:00-12:15" in r.stdout


def test_log_end_only_errors_when_nothing_earlier(env):
    r = runner.invoke(app, ["log", "10:30", "nothing before this", "-c", "dev"])
    assert r.exit_code == 1
    assert "Nothing logged earlier today" in r.stdout


@pytest.fixture
def now_1100(monkeypatch):
    """Freeze `tt log`'s notion of now at 11:00 local today."""
    import time_tracker.cli as cli
    frozen = cli._parse_when("11:00", cli._resolve_date(None))
    monkeypatch.setattr(cli, "_now", lambda: frozen)
    return frozen


def test_log_no_times_ends_now(env, now_1100):
    runner.invoke(app, ["log", "09:00", "10:00", "first", "-c", "dev"])
    r = runner.invoke(app, ["log", "wrote spec", "-c", "dev"])
    assert r.exit_code == 0
    assert "End set to now (11:00)" in r.stdout
    assert "Start inferred as 10:00" in r.stdout
    assert "10:00-11:00" in r.stdout


def test_log_no_times_with_category_number(env, now_1100):
    runner.invoke(app, ["log", "09:00", "10:00", "first", "-c", "dev"])
    r = runner.invoke(app, ["log", "wrote spec", "3"])
    assert r.exit_code == 0
    assert "10:00-11:00" in r.stdout
    assert "(Personal)" in r.stdout


def test_log_only_category_number(env, now_1100):
    runner.invoke(app, ["log", "09:00", "10:00", "first", "-c", "dev"])
    r = runner.invoke(app, ["log", "3"])
    assert r.exit_code == 0
    assert "(Personal)" in r.stdout
    assert "unspecified" in r.stdout


def test_log_no_times_with_date_errors(env, now_1100):
    r = runner.invoke(app, ["log", "spec", "--date", "yesterday"])
    assert r.exit_code == 1
    assert "--date needs explicit times" in r.stdout


def test_log_rejects_too_many_args(env):
    r = runner.invoke(app, ["log", "09:00", "10:00", "wrote", "spec"])
    assert r.exit_code == 1
    assert "Too many arguments" in r.stdout


def test_split_log_args_forms():
    from time_tracker.cli import _split_log_args, _resolve_date
    base = _resolve_date(None)
    assert _split_log_args(["09:30", "10:30", "spec", "3"], base) == (
        "09:30", "10:30", "spec", 3)
    assert _split_log_args(["09:30", "10:30", "spec"], base) == (
        "09:30", "10:30", "spec", None)
    assert _split_log_args(["09:30", "10:30"], base) == ("09:30", "10:30", None, None)
    assert _split_log_args(["10:30", "spec"], base) == (None, "10:30", "spec", None)
    assert _split_log_args(["10:30", "spec", "3"], base) == (None, "10:30", "spec", 3)
    assert _split_log_args(["10:30", "3"], base) == (None, "10:30", None, 3)
    assert _split_log_args(["10:30"], base) == (None, "10:30", None, None)
    assert _split_log_args(["spec"], base) == (None, None, "spec", None)
    assert _split_log_args(["spec", "3"], base) == (None, None, "spec", 3)
    assert _split_log_args(["3"], base) == (None, None, None, 3)
    assert _split_log_args([], base) == (None, None, None, None)


def test_log_rejects_overlap(env):
    runner.invoke(app, ["log", "09:00", "10:00", "a"])
    r = runner.invoke(app, ["log", "09:30", "10:30", "b"])
    assert r.exit_code == 1


def test_log_rejects_inverted(env):
    r = runner.invoke(app, ["log", "10:00", "09:00", "x"])
    assert r.exit_code == 1


def test_edit_refuses_non_interactive(env):
    r = runner.invoke(app, ["edit"])
    assert r.exit_code == 1
    assert "interactive" in r.stdout


def test_delete_refuses_non_interactive(env):
    r = runner.invoke(app, ["delete"])
    assert r.exit_code == 1
    assert "interactive" in r.stdout


def test_recat_bulk_rename(env):
    runner.invoke(app, ["log", "09:00", "10:00", "a", "-c", "MATS chats"])
    runner.invoke(app, ["log", "10:00", "11:00", "b", "-c", "MATS chats"])
    r = runner.invoke(app, ["recat", "MATS chats", "MATS workplace"])
    assert r.exit_code == 0
    assert "2 entries" in r.stdout
    day = runner.invoke(app, ["report", "day", "--text"])
    assert "MATS workplace" in day.stdout


def test_recat_interactive_refuses_non_interactive(env):
    runner.invoke(app, ["log", "09:00", "10:00", "a", "-c", "chats"])
    r = runner.invoke(app, ["recat", "chats"])
    assert r.exit_code == 1
    assert "terminal" in r.stdout


def test_resolve_date_relative_words():
    from time_tracker.cli import _resolve_date, _today_local
    from time_tracker.core import timeutil
    today = timeutil.local_date_key(_today_local())
    yday = timeutil.local_date_key(_resolve_date("yesterday"))
    tmrw = timeutil.local_date_key(_resolve_date("tomorrow"))
    assert yday < today < tmrw
    assert timeutil.local_date_key(_resolve_date("-2")) < yday


def test_day_accepts_relative_date(env):
    r = runner.invoke(app, ["day", "yesterday"])
    assert r.exit_code == 0
    assert "Timeline" in r.stdout


def test_day_has_category_column(env):
    runner.invoke(app, ["log", "09:00", "10:00", "spec", "-c", "dev"])
    r = runner.invoke(app, ["day"])
    assert r.exit_code == 0
    assert "Category" in r.stdout


def test_aliases_match_targets(env):
    # `td` behaves like `day`
    assert runner.invoke(app, ["td"]).exit_code == 0
    assert "Timeline" in runner.invoke(app, ["td"]).stdout
    # `tl` behaves like `log`
    r = runner.invoke(app, ["tl", "09:00", "10:00", "x", "-c", "dev"])
    assert r.exit_code == 0
    assert "Logged" in r.stdout


def test_end_to_end_all_capture_modes(env):
    # timer
    runner.invoke(app, ["start", "-c", "dev", "-d", "coding"])
    runner.invoke(app, ["stop"])
    # check-in
    assert runner.invoke(app, ["checkin", "review"]).exit_code == 0
    # day view shows entries
    r = runner.invoke(app, ["day"])
    assert r.exit_code == 0
