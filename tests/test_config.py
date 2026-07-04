from time_tracker.config import Config, load_config, save_config


def test_defaults_present():
    cfg = Config()
    assert cfg.excluded_color_ids == ["4"]
    assert cfg.checkin_interval_minutes == 45


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(checkin_interval_minutes=30, excluded_color_ids=["4", "11"])
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.checkin_interval_minutes == 30
    assert loaded.excluded_color_ids == ["4", "11"]


def test_meeting_category_rules_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(meeting_category_rules=[
        {"match": "MATS", "category": "MATS workplace"},
        {"match": "fellow", "category": "fellows"},
    ])
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.meeting_category_rules == cfg.meeting_category_rules


def test_load_missing_returns_defaults(tmp_path):
    loaded = load_config(tmp_path / "nope.toml")
    assert loaded == Config()


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('checkin_interval_minutes = 20\nbogus_key = "x"\n')
    loaded = load_config(path)
    assert loaded.checkin_interval_minutes == 20
