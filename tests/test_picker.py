"""The category pick list: pressing a number picks that option immediately."""

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from time_tracker.cli import _NEW, _SKIP, _shortcut_select, _value_options

VALUES = ["Admin", "Org work/projects", "Work-related chats", "Personal"]

DOWN, ENTER = "\x1b[B", "\r"


def press(keys, options):
    with create_pipe_input() as inp:
        inp.send_text(keys)
        with create_app_session(input=inp, output=DummyOutput()):
            return _shortcut_select("Category:", options)


def test_number_key_selects_without_enter():
    assert press("3", _value_options(VALUES)) == "Personal"
    assert press("0", _value_options(VALUES)) == "Admin"


def test_arrow_keys_and_enter_still_work():
    assert press(ENTER, _value_options(VALUES)) == "Admin"
    assert press(DOWN + ENTER, _value_options(VALUES)) == "Org work/projects"


def test_new_and_skip_have_letter_keys():
    assert press("n", _value_options(VALUES)) is _NEW
    assert press("s", _value_options(VALUES)) is _SKIP


def test_numbers_track_value_index_not_row_position():
    options = _value_options(VALUES)
    keys = [key for key, _title, _value in options]
    assert keys == ["0", "1", "2", "3", "n", "s"]


def test_values_past_ten_are_arrow_only():
    options = _value_options([f"cat{i}" for i in range(12)])
    keys = [key for key, _title, _value in options]
    assert keys[:10] == [str(i) for i in range(10)]
    assert keys[10:12] == [None, None]


def test_pick_or_type_takes_a_number_key(tmp_path, monkeypatch):
    """End to end: the number keys reach the real category picker."""
    from time_tracker.cli import CATEGORY_ORDER, _pick_or_type, get_db
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "test.db"))
    db = get_db()
    with create_pipe_input() as inp:
        inp.send_text("3")
        with create_app_session(input=inp, output=DummyOutput()):
            assert _pick_or_type(db, "Category:", "category", None) == CATEGORY_ORDER[3]


def test_falls_back_to_plain_select_when_too_many_choices():
    """questionary caps shortcuts at 36 options; more must still be pickable."""
    options = _value_options([f"cat{i}" for i in range(40)])
    assert press(ENTER, options) == "cat0"
