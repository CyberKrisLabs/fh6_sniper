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
    assert cfg["TIMINGS"]["nav_interval"] == settings.DEFAULT_TIMINGS["nav_interval"]
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


def test_migration_buy_attempt_interval():
    old = {"TIMINGS": {"buy_attempt_interval": 0.55}}
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(old, f)
    cfg = settings.load_config()
    assert "car_available_interval" in cfg["TIMINGS"]
    assert cfg["TIMINGS"]["car_available_interval"] == 0.55
    # deprecated key should have been dropped from the saved file
    with open(settings.CONFIG_FILE) as f:
        data = json.load(f)
    assert "buy_attempt_interval" not in data["TIMINGS"]


def test_validate_interval_too_low():
    """Test that intervals below MIN_INTERVAL are caught."""
    timings = {
        "car_available_interval": -0.5,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Car Available Interval" in error_msg
    assert corrected["timings"]["car_available_interval"] == settings.MIN_INTERVAL


def test_validate_interval_too_high():
    """Test that intervals above MAX_INTERVAL are caught."""
    timings = {
        "car_available_interval": 25.0,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Car Available Interval" in error_msg
    assert corrected["timings"]["car_available_interval"] == settings.MAX_INTERVAL


def test_validate_nav_interval_too_low():
    """Test that nav_interval below MIN_INTERVAL is caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": -0.5,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Nav Interval" in error_msg
    assert corrected["timings"]["nav_interval"] == settings.MIN_INTERVAL


def test_validate_nav_interval_too_high():
    """Test that nav_interval above MAX_INTERVAL is caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 25.0,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Nav Interval" in error_msg
    assert corrected["timings"]["nav_interval"] == settings.MAX_INTERVAL


def test_validate_confirm_buy_interval_too_low():
    """Test that confirm_buy_interval below MIN_INTERVAL is caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": -0.5,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Confirm Buy Interval" in error_msg
    assert corrected["timings"]["confirm_buy_interval"] == settings.MIN_INTERVAL


def test_validate_confirm_buy_interval_too_high():
    """Test that confirm_buy_interval above MAX_INTERVAL is caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": 25.0,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Confirm Buy Interval" in error_msg
    assert corrected["timings"]["confirm_buy_interval"] == settings.MAX_INTERVAL


def test_validate_load_cars_interval_too_low():
    """Test that load_cars_interval below MIN_INTERVAL is caught (same floor as most fields)."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": -0.5,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Load Cars Interval" in error_msg
    assert corrected["timings"]["load_cars_interval"] == settings.MIN_INTERVAL


def test_validate_exit_auction_below_floor():
    """Exit Auction has a 0.5s floor; Enter Auction's is temporarily lifted for testing."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.3,
        "enter_auction_interval": 0.3,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Exit Auction Interval" in error_msg
    assert "Enter Auction Interval" not in error_msg
    assert corrected["timings"]["exit_auction_interval"] == 0.5
    assert corrected["timings"]["enter_auction_interval"] == 0.3


def test_migration_reset_interval_split():
    """Old reset_interval migrates into both exit/enter auction intervals."""
    old = {"TIMINGS": {"reset_interval": 0.77}}
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(old, f)
    cfg = settings.load_config()
    assert cfg["TIMINGS"]["exit_auction_interval"] == 0.77
    assert cfg["TIMINGS"]["enter_auction_interval"] == 0.77
    # deprecated key should have been dropped from the saved file
    with open(settings.CONFIG_FILE) as f:
        data = json.load(f)
    assert "reset_interval" not in data["TIMINGS"]


def test_validate_load_cars_interval_too_high():
    """Test that load_cars_interval above MAX_INTERVAL is caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 25.0,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Load Cars Interval" in error_msg
    assert corrected["timings"]["load_cars_interval"] == settings.MAX_INTERVAL


def test_validate_multiple_interval_errors():
    """Test multiple interval violations are all reported."""
    timings = {
        "car_available_interval": -0.5,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 25.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 100)
    assert not is_valid
    assert "Car Available Interval" in error_msg
    assert "Post Buy Wait" in error_msg
    assert corrected["timings"]["car_available_interval"] == settings.MIN_INTERVAL
    assert corrected["timings"]["post_buy_wait"] == settings.MAX_INTERVAL


def test_validate_scans_too_low():
    """Test that scans below MIN_SCANS are caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, -100)
    assert not is_valid
    assert "Number of Scans" in error_msg
    assert corrected["scans"] == settings.MIN_SCANS


def test_validate_scans_too_high():
    """Test that scans above MAX_SCANS are caught."""
    timings = {
        "car_available_interval": 0.4,
        "nav_interval": 0.1,
        "confirm_buy_interval": 0.1,
        "post_buy_wait": 5.0,
        "exit_auction_interval": 0.8,
        "enter_auction_interval": 0.8,
        "load_cars_interval": 0.8,
        "buy_result_retry_wait": 0.8,
    }
    is_valid, error_msg, corrected = settings.validate_settings(timings, 1_100_000)
    assert not is_valid
    assert "Number of Scans" in error_msg
    assert corrected["scans"] == settings.MAX_SCANS


def test_load_config_auto_fixes_bad_intervals():
    """Test that load_config auto-corrects intervals outside bounds."""
    bad_config = {
        "scans": 500,
        "TIMINGS": {
            "car_available_interval": 50.0,  # too high
            "nav_interval": 0.1,
            "confirm_buy_interval": 0.1,
            "post_buy_wait": 0.01,  # too low
            "exit_auction_interval": 0.8,
            "enter_auction_interval": 0.8,
            "load_cars_interval": 0.8,
        },
    }
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(bad_config, f)

    cfg = settings.load_config()
    # Values should be corrected
    assert cfg["TIMINGS"]["car_available_interval"] == settings.MAX_INTERVAL
    assert cfg["TIMINGS"]["post_buy_wait"] == settings.MIN_INTERVAL
    # File should be rewritten with corrections
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved["TIMINGS"]["car_available_interval"] == settings.MAX_INTERVAL
    assert saved["TIMINGS"]["post_buy_wait"] == settings.MIN_INTERVAL


def test_load_config_auto_fixes_reset_below_floor_but_not_load_cars():
    """load_config enforces the exit/enter 0.5s floors but load_cars_interval has none."""
    bad_config = {
        "scans": 500,
        "TIMINGS": {
            "car_available_interval": 0.4,
            "nav_interval": 0.1,
            "confirm_buy_interval": 0.1,
            "post_buy_wait": 5.0,
            "exit_auction_interval": 0.2,  # above MIN_INTERVAL but below the 0.5s floor
            "enter_auction_interval": 0.2,  # valid while its floor is lifted for testing
            "load_cars_interval": 0.2,  # valid as-is, no floor to enforce
        },
    }
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(bad_config, f)

    cfg = settings.load_config()
    assert cfg["TIMINGS"]["exit_auction_interval"] == 0.5
    assert cfg["TIMINGS"]["enter_auction_interval"] == 0.2
    assert cfg["TIMINGS"]["load_cars_interval"] == 0.2


def test_buy_last_available_round_trip():
    """BUY_LAST_AVAILABLE defaults to True and persists when toggled."""
    assert settings.get_buy_last_available() is True
    settings.set_buy_last_available(False)
    assert settings.get_buy_last_available() is False
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved["BUY_LAST_AVAILABLE"] is False


def test_auction_button_ocr_round_trip():
    """AUCTION_BUTTON_OCR defaults to False and persists when toggled."""
    assert settings.get_auction_button_ocr() is False
    settings.set_auction_button_ocr(True)
    assert settings.get_auction_button_ocr() is True
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved["AUCTION_BUTTON_OCR"] is True


def test_show_ingame_overlay_round_trip():
    """SHOW_INGAME_OVERLAY defaults to False and persists when toggled."""
    assert settings.get_show_ingame_overlay() is False
    settings.set_show_ingame_overlay(True)
    assert settings.get_show_ingame_overlay() is True
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved["SHOW_INGAME_OVERLAY"] is True


def test_buy_result_retry_wait_survives_load_config():
    """buy_result_retry_wait is a known timing key — it must not be stripped as deprecated."""
    cfg_in = {
        "scans": 500,
        "TIMINGS": {**settings.DEFAULT_TIMINGS, "buy_result_retry_wait": 1.5},
    }
    with open(settings.CONFIG_FILE, "w") as f:
        json.dump(cfg_in, f)

    cfg = settings.load_config()
    assert cfg["TIMINGS"]["buy_result_retry_wait"] == 1.5
    # and it must still be in the file (not rewritten away)
    with open(settings.CONFIG_FILE) as f:
        saved = json.load(f)
    assert saved.get("TIMINGS", {}).get("buy_result_retry_wait", 1.5) == 1.5


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
