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


def test_report_runs(env):
    runner.invoke(app, ["in"])
    runner.invoke(app, ["start", "-c", "dev"])
    runner.invoke(app, ["stop"])
    r = runner.invoke(app, ["report", "day"])
    assert r.exit_code == 0
    assert "Report" in r.stdout


def test_report_html_writes_file(env, monkeypatch):
    import time_tracker.cli as cli
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    # Point the reports dir at the temp DB's parent (env fixture's tmp dir).
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", env)
    runner.invoke(app, ["in"])
    runner.invoke(app, ["log", "09:00", "10:00", "spec", "-c", "dev"])
    runner.invoke(app, ["out"])
    r = runner.invoke(app, ["report", "week", "--html"])
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
    day = runner.invoke(app, ["report", "day"])
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
