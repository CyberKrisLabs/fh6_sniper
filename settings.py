"""Configuration management for FH6 Sniper.

Functions:
- load_timings(): Get timing settings from config
- save_timings(): Validate and save timing settings
- get_scans(): Get number of scans to perform
- reset_to_defaults(): Reset all settings to defaults
"""

import json

import window_utils

CONFIG_FILE = window_utils.get_config_file()

# Validation limits
MIN_INTERVAL = 0.1  # minimum delay between keystrokes
MAX_INTERVAL = 20.0  # maximum interval to prevent unbearably slow execution
MIN_SCANS = 0  # 0 means infinite
MAX_SCANS = 1000000

# reset_interval needs a higher floor than MIN_INTERVAL — below this, the game
# won't reliably register the keystroke, regardless of how fast the PC is.
MIN_INTERVAL_OVERRIDES: dict[str, float] = {
    "reset_interval": 0.5,
}

DEFAULT_TIMINGS: dict[str, float] = {
    "car_available_interval": 0.6,
    "nav_interval": 0.3,
    "confirm_buy_interval": 0.35,
    "post_buy_wait": 5.0,
    "reset_interval": 0.9,
    "load_cars_interval": 0.9,
}

# All default values
DEFAULT_CONFIG: dict[str, object] = {
    "scans": 1000,  # previously 'attempts'
    "buyout_target": None,
    "TIMINGS": DEFAULT_TIMINGS,
    # whether to skip the popup warning about missing manual calibration
    "SKIP_CALIBRATION_WARNING": False,
    # whether to skip the recalibration reminder on first sniper start
    "SKIP_RECALIBRATION_REMINDER": False,
    # whether FH6's "Moving Backgrounds" accessibility setting is turned off —
    # the Auction Options button gets a plain white background instead of the
    # default animated one, so a different template set is needed
    "MOVING_BACKGROUND_OFF": False,
    # AUCTION_OPTIONS_REGION is optional (only set via manual calibration)
}


def validate_settings(timings_dict, scans_value, buyout_target=None):
    """Validate timing, scans, and buyout target settings.

    Returns:
        (is_valid, error_message, corrected_values_dict)
    """
    errors = []
    corrected = {
        "timings": timings_dict.copy(),
        "scans": scans_value,
        "buyout_target": buyout_target,
    }

    # Validate scans
    if scans_value < MIN_SCANS:
        errors.append(f"Number of Scans must be at least {MIN_SCANS}")
        corrected["scans"] = MIN_SCANS
    elif scans_value > MAX_SCANS:
        errors.append(f"Number of Scans cannot exceed {MAX_SCANS}")
        corrected["scans"] = MAX_SCANS

    # Validate buyout target
    if buyout_target is None:
        corrected["buyout_target"] = None
    elif isinstance(buyout_target, int):
        if buyout_target < 1 or buyout_target > 100:
            errors.append("Buyout target must be Infinite or between 1 and 100")
            corrected["buyout_target"] = None
    else:
        errors.append("Buyout target must be Infinite or a number between 1 and 100")
        corrected["buyout_target"] = None

    # Validate intervals
    interval_names = {
        "car_available_interval": "Car Available Interval",
        "nav_interval": "Nav Interval",
        "confirm_buy_interval": "Confirm Buy Interval",
        "post_buy_wait": "Post Buy Wait",
        "reset_interval": "Reset Interval",
        "load_cars_interval": "Load Cars Interval",
    }

    for key, display_name in interval_names.items():
        min_val = MIN_INTERVAL_OVERRIDES.get(key, MIN_INTERVAL)
        val = timings_dict.get(key, 0)
        if val < min_val:
            errors.append(f"{display_name} must be at least {min_val}")
            corrected["timings"][key] = min_val
        elif val > MAX_INTERVAL:
            errors.append(f"{display_name} cannot exceed {MAX_INTERVAL}")
            corrected["timings"][key] = MAX_INTERVAL

    return (len(errors) == 0, "; ".join(errors) if errors else "", corrected)


def load_config():
    """Load full config with defaults merged."""
    try:
        with open(CONFIG_FILE) as f:
            user_config = json.load(f)
        # Merge: user config overrides defaults
        config = DEFAULT_CONFIG.copy()
        config.update(user_config)
        # migration from old key name
        if "attempts" in config:
            config["scans"] = config.pop("attempts")
            save_config(config)

        # MIGRATION FIRST: handle deprecated keys before validation
        if "TIMINGS" in user_config:
            # merge only known timing keys, ignore deprecated ones
            old_timings = user_config.get("TIMINGS", {})
            user_times = {k: v for k, v in old_timings.items() if k in DEFAULT_TIMINGS}
            # migrate old buy_attempt_interval (renamed to car_available_interval)
            if "buy_attempt_interval" in old_timings:
                user_times.setdefault("car_available_interval", old_timings["buy_attempt_interval"])
            config["TIMINGS"] = {**DEFAULT_TIMINGS, **user_times}
            # if there were deprecated keys in the original user_config, clean them from file
            deprecated = [k for k in old_timings if k not in DEFAULT_TIMINGS]
            if deprecated:
                # rewrite to remove them
                save_config(config)

        # Validate and fix scans value
        if config["scans"] < MIN_SCANS or config["scans"] > MAX_SCANS:
            config["scans"] = max(MIN_SCANS, min(MAX_SCANS, config["scans"]))
            save_config(config)

        # Validate and fix buyout target
        if config.get("buyout_target") is not None:
            try:
                target = int(config["buyout_target"])
                if target < 1 or target > 100:
                    raise ValueError
            except Exception:
                config["buyout_target"] = None
                save_config(config)

        # Validate and fix timing intervals
        if "TIMINGS" in config:
            needs_save = False
            for key in [
                "car_available_interval",
                "nav_interval",
                "confirm_buy_interval",
                "post_buy_wait",
                "reset_interval",
                "load_cars_interval",
            ]:
                min_val = MIN_INTERVAL_OVERRIDES.get(key, MIN_INTERVAL)
                val = config["TIMINGS"].get(key, 0)
                if val < min_val:
                    config["TIMINGS"][key] = min_val
                    needs_save = True
                elif val > MAX_INTERVAL:
                    config["TIMINGS"][key] = MAX_INTERVAL
                    needs_save = True
            if needs_save:
                save_config(config)

        return config
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save config to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_timings():
    """Load timings for runtime use (sniper)."""
    config = load_config()
    return config["TIMINGS"]


def load_timings_ui():
    """Load timings for UI fields."""
    return load_timings()


def save_timings_ui(timings_dict, scans_value, buyout_target):
    """Save timings, buyout target, and total scans from UI with validation.

    Returns:
        (success, error_message, corrected_values)
    """
    is_valid, error_msg, corrected = validate_settings(timings_dict, scans_value, buyout_target)

    # Save corrected values even if there were errors
    config = load_config()
    config["TIMINGS"] = corrected["timings"]
    config["scans"] = corrected["scans"]
    config["buyout_target"] = corrected["buyout_target"]
    save_config(config)

    return (is_valid, error_msg, corrected)


def get_scans():
    """Get number of scans from config."""
    config = load_config()
    return config.get("scans", 1000)


def get_buyout_target():
    """Get buyout target from config. None means infinite."""
    config = load_config()
    return config.get("buyout_target", None)


def get_skip_calibration_warning():
    """Return True if the user opted out of the calibration popup."""
    config = load_config()
    return config.get("SKIP_CALIBRATION_WARNING", False)


def set_skip_calibration_warning(value: bool):
    """Persist the user's choice about the calibration popup."""
    config = load_config()
    config["SKIP_CALIBRATION_WARNING"] = bool(value)
    save_config(config)


def get_skip_recalibration_reminder():
    """Return True if the user opted out of the recalibration reminder."""
    config = load_config()
    return config.get("SKIP_RECALIBRATION_REMINDER", False)


def set_skip_recalibration_reminder(value: bool):
    """Persist the user's choice about the recalibration reminder."""
    config = load_config()
    config["SKIP_RECALIBRATION_REMINDER"] = bool(value)
    save_config(config)


def get_moving_background_off():
    """Return True if FH6's Moving Backgrounds accessibility setting is off."""
    config = load_config()
    return config.get("MOVING_BACKGROUND_OFF", False)


def set_moving_background_off(value: bool):
    """Persist whether FH6's Moving Backgrounds accessibility setting is off."""
    config = load_config()
    config["MOVING_BACKGROUND_OFF"] = bool(value)
    save_config(config)
