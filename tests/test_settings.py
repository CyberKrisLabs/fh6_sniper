import json
import os

import pytest

import settings


def make_temp_config(tmp_path, data=None):
    path = tmp_path / "config.json"
    if data is None:
        data = {}
    with open(path, "w") as f:
        json.dump(data, f)
    return str(path)


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    # point module to a temporary config file for each test
    temp = make_temp_config(tmp_path)
    monkeypatch.setattr(settings, "CONFIG_FILE", temp)
    yield


def test_default_config_created():
    cfg = settings.load_config()
    assert cfg["scans"] == settings.DEFAULT_CONFIG["scans"]
    assert "TIMINGS" in cfg
    # file should now exist
    assert os.path.isfile(settings.CONFIG_FILE)


def test_skip_calibration_warning_flag():
    assert not settings.get_skip_calibration_warning()
    settings.set_skip_calibration_warning(True)
    assert settings.get_skip_calibration_warning()
    # check persistence
    cfg = settings.load_config()
    assert cfg["SKIP_CALIBRATION_WARNING"] is True


def test_migration_attempts():
    # write old config with 'attempts' key
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump({"attempts": 42}, f)
    cfg = settings.load_config()
    assert cfg.get("scans") == 42
    # original file should have been rewritten without 'attempts'
    with open(settings.CONFIG_FILE) as f:
        data = json.load(f)
    assert "attempts" not in data


def test_migration_menu_interval():
    old = {"TIMINGS": {"menu_interval": 0.7}}
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(old, f)
    cfg = settings.load_config()
    assert "buy_attempt_interval" in cfg["TIMINGS"]
    assert cfg["TIMINGS"]["buy_attempt_interval"] == 0.7


def test_validate_interval_too_low():
    """Test that intervals below MIN_INTERVAL are caught."""
    timings = {
        "buy_attempt_interval": -0.5,
        "post_buy_wait": 5.0,
        "reset_interval": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Buy Interval" in error_msg
    assert corrected["timings"]["buy_attempt_interval"] == settings.MIN_INTERVAL


def test_validate_interval_too_high():
    """Test that intervals above MAX_INTERVAL are caught."""
    timings = {
        "buy_attempt_interval": 25.0,
        "post_buy_wait": 5.0,
        "reset_interval": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Buy Interval" in error_msg
    assert corrected["timings"]["buy_attempt_interval"] == settings.MAX_INTERVAL


def test_validate_multiple_interval_errors():
    """Test multiple interval violations are all reported."""
    timings = {
        "buy_attempt_interval": -0.5,
        "post_buy_wait": 25.0,
        "reset_interval": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Buy Interval" in error_msg
    assert "Post Buy Wait" in error_msg
    assert corrected["timings"]["buy_attempt_interval"] == settings.MIN_INTERVAL
    assert corrected["timings"]["post_buy_wait"] == settings.MAX_INTERVAL


def test_validate_scans_too_low():
    """Test that scans below MIN_SCANS are caught."""
    timings = {"buy_attempt_interval": 0.4, "post_buy_wait": 5.0, "reset_interval": 0.8}
    is_valid, error_msg, corrected = settings.validate_settings(timings, -100)
    assert not is_valid
    assert "Number of Scans" in error_msg
    assert corrected["scans"] == settings.MIN_SCANS


def test_validate_scans_too_high():
    """Test that scans above MAX_SCANS are caught."""
    timings = {"buy_attempt_interval": 0.4, "post_buy_wait": 5.0, "reset_interval": 0.8}
    is_valid, error_msg, corrected = settings.validate_settings(timings, 1_100_000)
    assert not is_valid
    assert "Number of Scans" in error_msg
    assert corrected["scans"] == settings.MAX_SCANS


def test_load_config_auto_fixes_bad_intervals():
    """Test that load_config auto-corrects intervals outside bounds."""
    bad_config = {
        "scans": 500,
        "TIMINGS": {
            "buy_attempt_interval": 50.0,  # too high
            "post_buy_wait": 0.01,  # too low
            "reset_interval": 0.8,
        },
    }
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(bad_config, f)

    cfg = settings.load_config()
    # Values should be corrected
    assert cfg["TIMINGS"]["buy_attempt_interval"] == settings.MAX_INTERVAL
    assert cfg["TIMINGS"]["post_buy_wait"] == settings.MIN_INTERVAL
    # File should be rewritten with corrections
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved["TIMINGS"]["buy_attempt_interval"] == settings.MAX_INTERVAL
    assert saved["TIMINGS"]["post_buy_wait"] == settings.MIN_INTERVAL


def test_load_config_auto_fixes_bad_scans():
    """Test that load_config auto-corrects scans outside bounds."""
    bad_config = {"scans": -50}
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(bad_config, f)

    cfg = settings.load_config()
    assert cfg["scans"] == settings.MIN_SCANS
    # File should be rewritten
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved["scans"] == settings.MIN_SCANS
