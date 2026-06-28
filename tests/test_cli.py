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


def test_end_to_end_all_capture_modes(env):
    # timer
    runner.invoke(app, ["start", "-c", "dev", "-d", "coding"])
    runner.invoke(app, ["stop"])
    # check-in
    assert runner.invoke(app, ["checkin", "review"]).exit_code == 0
    # day view shows entries
    r = runner.invoke(app, ["day"])
    assert r.exit_code == 0
