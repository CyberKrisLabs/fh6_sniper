"""Core sniper logic for detecting and purchasing cars in Forza Horizon 6.

Functions:
- car_available(): Check if Auction Options button is visible
- buy_sequence(): Execute buy workflow with keyboard simulation
- sniper_loop(): Main scanning loop with focus checks and error handling
- reset_search(): Navigate back to auction search
"""

import json
import os
import time

import pyautogui

import calibrator
import settings
import vision_utils
import window_utils

# disable PyAutoGUI's built-in failsafe (moving mouse to corner raises
# an exception) since we handle focus checks ourselves and the popup
# message wasn't user-friendly in normal operation.
pyautogui.FAILSAFE = False

# PyAutoGUI sleeps PAUSE seconds (default 0.1) after every press/typewrite
# call. All our inter-key timing is explicit via stop_event.wait/config
# intervals, so the implicit pause only adds hidden, untunable latency.
pyautogui.PAUSE = 0

# Re-exported from vision_utils (its authoritative home) for existing
# importers (ui.tabs.calibration, tools).
SOLD_THRESHOLD = vision_utils.SOLD_THRESHOLD
CONFIG_FILE = window_utils.get_config_file()

# -------------------------
# CONFIG HELPERS
# -------------------------

# Single source of truth for timing defaults lives in settings.py; the
# .get() fallbacks throughout this module reference the same dict.
DEFAULT_TIMINGS = settings.DEFAULT_TIMINGS


# Parsed config cached by file mtime — car_available() runs every scan and
# the config only changes when the user saves settings or recalibrates.
_config_cache: dict = {"mtime": None, "data": None}


def load_config():
    """Load config with safe defaults (cached until config.json changes)."""
    try:
        mtime = os.path.getmtime(CONFIG_FILE)
    except OSError:
        mtime = None
    if mtime is not None and _config_cache["mtime"] == mtime:
        return _config_cache["data"]

    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"⚠️  Config file missing or empty: {CONFIG_FILE}. Using defaults.")
        data = {}

    # Ensure timings exist
    if "TIMINGS" not in data:
        data["TIMINGS"] = DEFAULT_TIMINGS.copy()

    _config_cache["mtime"] = mtime
    _config_cache["data"] = data
    return data


def load_region():
    """Load the calibrated auction options region from config."""
    data = load_config()
    return tuple(data["AUCTION_OPTIONS_REGION"])


def load_timings():
    """Load timing configuration from config."""
    data = load_config()
    return data["TIMINGS"]


def load_badge_params(win_w: int | None = None, win_h: int | None = None) -> dict | None:
    """Load sold-badge region percentages, selecting the best profile for the given window size."""
    return window_utils.load_badge_params(win_w, win_h)


# -------------------------
# DETECTION
# -------------------------


def car_available(region, full_img=None):
    """
    Check if the 'Auction Options' button is available using image detection.

    Args:
        region (tuple): Region tuple (left, top, width, height) to search in.
                        It is assumed the caller precomputes this.
    Returns:
        bool: True if button found, False otherwise.
    """
    try:
        if region is None:
            # caller forgot to supply region; try fallback path
            fallback = load_region()
            region = window_utils.get_fh6_region_safe(fallback_region=fallback)
            if region is None:
                print("WARNING: No detection region available")
                return False

        # Check if we have calibrated data that allows us to skip variants.
        # IMPORTANT: manual calibration should always take precedence over auto.
        cfg = load_config()
        manual_region = (
            tuple(cfg["AUCTION_OPTIONS_REGION"]) if "AUCTION_OPTIONS_REGION" in cfg else None
        )
        auto_region = (
            tuple(cfg["AUTO_AUCTION_OPTIONS_REGION"])
            if "AUTO_AUCTION_OPTIONS_REGION" in cfg
            else None
        )
        # Auto-calibrated template path + scale, read from the same cached
        # config (old keys kept for backward compatibility). Previously this
        # was a second config.json disk read on every scan.
        auto_tpl_path = cfg.get("AUTO_AUCTION_OPTIONS_TEMPLATE") or cfg.get("AUTO_TEMPLATE_PATH")
        auto_tpl_scale = cfg.get("AUTO_AUCTION_OPTIONS_SCALE") or cfg.get("AUTO_SCALE")
        auto_template_info = (
            (auto_tpl_path, auto_tpl_scale)
            if auto_tpl_path and auto_tpl_scale is not None
            else None
        )

        # Define base template path for reuse. When FH6's "Moving Backgrounds"
        # accessibility setting is off, the Auction Options button has a plain
        # white background instead of the default animated one, so it needs
        # its own template set.
        auction_tpl_name = (
            "auction_options_template_nomovingbackground.png"
            if cfg.get("MOVING_BACKGROUND_OFF", False)
            else "auction_options_template.png"
        )
        base_template = window_utils.resource_path(f"assets/{auction_tpl_name}")

        # If the caller passed a shared full-screen grab, crop the button region
        # from it so this call and find_available_row() operate on the same
        # GPU frame — avoids the DXGI bad-frame inconsistency between two grabs.
        screenshot = None
        if full_img is not None and region is not None:
            rx, ry, rw, rh = region
            screenshot = full_img.crop((rx, ry, rx + rw, ry + rh))

        # If we have a manually calibrated region, search it with the base
        # template. The first hit caches a scale hint inside vision_utils, so
        # subsequent scans only sweep a narrow window around it.
        if manual_region:
            location = vision_utils.locate_on_screen_with_variants(
                base_template,
                region=region,
                confidence=0.68,
                scale_min=0.4,
                scale_max=1,
                scale_steps=24,
                screenshot=screenshot,
            )
            return location is not None

        # If we have auto calibration with template info, use it directly
        elif auto_region and auto_template_info:
            template_path, scale = auto_template_info
            # Use a ±12 % window around the calibrated scale rather than the exact
            # value: minor window movements or frame-to-frame rendering variance can
            # shift the real scale slightly and miss an exact hit.  Lower confidence
            # (0.65) for the same reason — calibration found it at ≥0.70 so 0.65
            # still avoids false positives while tolerating normal scene variation.
            margin = scale * 0.3
            location = vision_utils.locate_on_screen_scaled(
                template_path,
                region=region,
                confidence=0.65,
                grayscale=True,
                scale_min=max(0.1, scale - margin),
                scale_max=min(1.5, scale + margin),
                scale_steps=7,
                debug=False,
                screenshot=screenshot,
            )
            return location is not None
        else:
            # No calibration - use the full variants approach.
            # Determine which template to use based on the *full* window size:
            # the caller usually passes a cropped region (bottom-left quarter)
            # so using that directly would misclassify the window as "small".
            # Only this uncalibrated branch needs the window lookup, so it
            # happens here rather than on every scan for calibrated users.
            win = window_utils.get_fh6_window()
            full_window_region = window_utils.get_window_region(win) if win else None
            size_region = full_window_region if full_window_region is not None else region

            _, size_cat = vision_utils.choose_template(
                base_template,
                region=size_region,
                debug=False,
            )
            # determine numeric thresholds per category
            if size_cat == "small":
                base_min = 0.7
                conf = 0.65
            elif size_cat == "medium":
                base_min = 0.5
                conf = 0.70
            else:
                base_min = 0.35
                conf = 0.72
            # fixed range, nothing fancy
            scale_min, scale_max = base_min, 1.0

            # starting hint = middle of the permitted interval (caching may override)
            scale_hint_val = (scale_min + scale_max) / 2
            location = vision_utils.locate_on_screen_with_variants(
                base_template,
                region=region,
                confidence=conf,
                grayscale=True,
                scale_min=scale_min,
                scale_max=scale_max,
                scale_hint=scale_hint_val,
                hint_margin=0.3,
                debug=False,
                screenshot=screenshot,
            )
            return location is not None
    except Exception as e:
        print(f"Error in car_available: {e}")
        return False


# -------------------------
# ROW SCANNING
# -------------------------


def find_available_row(
    row_regions: list,
    badge_params: dict | None,
    sold_template: str,
    log=None,
    full_img=None,
    buy_last: bool = True,
) -> tuple[int, bool]:
    """Scan visible rows and return the 0-based index of the row to buy.

    Scans purely by screenshot — no key presses.  The caller navigates to the
    returned row with arrow-down presses after this function returns.

    Stops scanning at the first empty row (no car), since rows below it will
    also be empty.

    With buy_last=True (default), targets the LAST available row: most snipers
    go for row 1, so row 3 or 4 has less competition.  With buy_last=False,
    returns the FIRST available row immediately — a slightly faster attempt
    (rows below it are never checked, fewer arrow-down presses) at the cost of
    competing against the bots that always target the top row.

    Args:
        row_regions: list of (x, y, w, h) for each visible row.
        badge_params: dict from load_badge_params(), or None to skip sold detection.
        sold_template: absolute path to sold_badge_template.png.
        buy_last: target the last available row (True) or the first (False).

    Returns:
        (available_idx, saw_any_car) — saw_any_car is False only when row 1
        never rendered a car at all (still mid-load), which the caller uses to
        avoid mislabeling that case as "all rows sold".
    """
    last_available = -1
    saw_any_car = False

    # Use the caller-supplied frame when available so car_available() and this
    # function share one GPU grab. If not provided, capture one now.
    if full_img is None:
        full_img = vision_utils.grab_full_screen()

    # Hoisted out of the per-row loop: the template existence check and the
    # candidate list (which reads config.json) are identical for every row.
    # active_badge_params is None when badge detection can't run at all.
    active_badge_params = (
        badge_params if badge_params is not None and os.path.isfile(sold_template) else None
    )
    sold_candidates = (
        vision_utils.build_sold_candidates(sold_template, row_regions[0][2])
        if active_badge_params is not None and row_regions
        else None
    )

    for idx, row_reg in enumerate(row_regions):
        rx, ry, rw, rh = row_reg
        row_img = (
            full_img.crop((rx, ry, rx + rw, ry + rh))
            if full_img is not None
            else vision_utils.grab_region(row_reg)
        )
        if not vision_utils.row_has_car(row_reg, row_img=row_img):
            if log:
                log(f"  Row {idx + 1}: empty — stop scanning")
            break

        saw_any_car = True
        if active_badge_params is not None:
            score = vision_utils.sold_badge_score(
                row_reg,
                active_badge_params,
                sold_template,
                row_img=row_img,
                candidates=sold_candidates,
            )
            if score >= SOLD_THRESHOLD:
                if log:
                    log(f"  Row {idx + 1}: sold")
                continue
            if log:
                log(f"  Row {idx + 1}: available")
        else:
            if log:
                log(f"  Row {idx + 1}: available")
        last_available = idx
        if not buy_last:
            # First available row wins — skip checking the rows below it.
            return last_available, saw_any_car

    return last_available, saw_any_car


# -------------------------
# ACTIONS
# -------------------------


# Buy-result detection tuning. HIGH_CONF is the unambiguous bar: a score
# this strong can't be a cross-match of the other template, so scoring stops
# immediately. Last winning (template, scale) is cached so retries and later
# buys do one matchTemplate instead of re-sweeping every scale.
BUY_RESULT_CONF = 0.80
_BUY_RESULT_HIGH_CONF = 0.90
_BUY_RESULT_SCALE_MIN = 0.5
_BUY_RESULT_SCALE_STEPS = 18
_buy_result_scale_hint: dict[str, float] = {}


def _detect_buy_result(raw, full_region=None):
    """Match buyout success/failure templates against a screenshot.

    Returns True (success), False (failure), or None (undetermined).
    Extracted so tests can monkeypatch it without touching OpenCV.
    """
    try:
        import cv2
        import numpy as np

        base_succ = window_utils.resource_path("assets/buyout_successful_template.png")
        base_fail = window_utils.resource_path("assets/buyout_failed_template.png")

        def _variants(base: str) -> list[str]:
            return [p for p in [base, base.replace(".png", "_med.png")] if os.path.isfile(p)]

        conf = BUY_RESULT_CONF

        if full_region is not None:
            rx, ry, rw, rh = full_region
        else:
            rx, ry = 0, 0
            rw, rh = raw.width, raw.height
        cx, cy = rx + rw // 2, ry + rh // 2
        sw2, sh2 = rw * 2 // 3, rh * 2 // 3
        screen_pil = raw.crop((cx - sw2 // 2, cy - sh2 // 2, cx + sw2 // 2, cy + sh2 // 2))

        screen_gray = cv2.cvtColor(np.array(screen_pil), cv2.COLOR_RGB2GRAY)
        sh, sw = screen_gray.shape[:2]

        def _match_at(tpl, scale) -> float:
            rh2 = int(tpl.shape[0] * scale)
            rw2 = int(tpl.shape[1] * scale)
            if rh2 <= 0 or rw2 <= 0 or rh2 > sh or rw2 > sw:
                return 0.0
            resized = cv2.resize(tpl, (rw2, rh2), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return float(max_val)

        def _score(tpl_paths: list[str]) -> float:
            best = 0.0
            for tpl_path in tpl_paths:
                try:
                    tpl = vision_utils._load_template_gray(tpl_path)
                except Exception:
                    continue
                # Cached winning scale first — retries and repeat buys hit
                # this single match instead of the full sweep.
                hint = _buy_result_scale_hint.get(tpl_path)
                scales = np.linspace(1.0, _BUY_RESULT_SCALE_MIN, _BUY_RESULT_SCALE_STEPS)
                if hint is not None:
                    scales = np.concatenate(([hint], scales))
                for scale in scales:
                    val = _match_at(tpl, scale)
                    if val > best:
                        best = val
                    if val >= conf:
                        _buy_result_scale_hint[tpl_path] = scale
                        if val >= _BUY_RESULT_HIGH_CONF:
                            return best
            return best

        # Success first: a high-confidence success match skips fail scoring
        # entirely (the two screens are never shown at once).
        succ_score = _score(_variants(base_succ))
        if succ_score >= _BUY_RESULT_HIGH_CONF:
            print(f"Buy detection: success={succ_score:.3f} (high-confidence)")
            return True
        fail_score = _score(_variants(base_fail))

        print(f"Buy detection: success={succ_score:.3f}  fail={fail_score:.3f}  threshold={conf}")

        if succ_score >= conf and succ_score > fail_score:
            return True
        if fail_score >= conf and fail_score > succ_score:
            return False
    except Exception as e:
        print(f"Error detecting buy result: {e}")
    return None


def buy_sequence(t, full_region=None, stop_event=None, log=None):
    """Perform buy sequence and detect success/failure via screenshots.

    Args:
        t: timing configuration dict
        full_region: optional region to limit post-buy image searches (entire window)
        stop_event: threading.Event — waits can be interrupted instantly on stop
        log: optional callable for status messages

    Returns:
      True if buy succeeded, False if failed, None if undetermined.
    """
    try:
        if not window_utils.is_fh6_focused():
            if log:
                log("🔒 Buy sequence aborted: FH6 not focused")
            return None
    except Exception:
        return None

    _sleep = stop_event.wait if stop_event is not None else time.sleep

    pyautogui.press("y")
    car_available_interval = t.get(
        "car_available_interval", DEFAULT_TIMINGS["car_available_interval"]
    )
    _sleep(car_available_interval)

    nav_interval = t.get("nav_interval", DEFAULT_TIMINGS["nav_interval"])
    pyautogui.press("down")
    _sleep(nav_interval)

    # Explicit press + wait instead of typewrite(interval=...): typewrite also
    # sleeps after the LAST key, silently adding a full interval of dead time,
    # and its sleeps can't be interrupted by stop_event.
    confirm_buy_interval = t.get("confirm_buy_interval", DEFAULT_TIMINGS["confirm_buy_interval"])
    pyautogui.press("\n")
    _sleep(confirm_buy_interval)
    pyautogui.press("\n")
    _sleep(t["post_buy_wait"])

    # Single grab shared by both template matches to avoid DXGI frame inconsistency.
    raw = vision_utils.grab_full_screen()
    if raw is None:
        raw = pyautogui.screenshot()

    result = _detect_buy_result(raw, full_region)

    # Retry while undetermined — the success/fail screen can appear late.
    # All retries happen BEFORE the reset keystrokes so we don't navigate away
    # before the screen has had a chance to render.
    retry_wait = t.get("buy_result_retry_wait", DEFAULT_TIMINGS["buy_result_retry_wait"])
    for _ in range(3):
        if result is not None:
            break
        _sleep(retry_wait)
        raw = vision_utils.grab_full_screen()
        if raw is None:
            raw = pyautogui.screenshot()
        result = _detect_buy_result(raw, full_region)

    if log:
        if result is True:
            log("✅ Buy successful")
        elif result is False:
            log("❌ Buy failed")
        else:
            log("⚠️ Buy result undetermined")

    # Dismiss the buy-result screen (Enter closes the dialog, Esc backs out).
    # Explicit press + wait instead of typewrite so the sleeps are
    # stop_event-interruptible. The wait after esc stays: reset_search presses
    # esc again right away, and back-to-back keys don't register in-game.
    pyautogui.press("\n")
    _sleep(t.get("enter_auction_interval", DEFAULT_TIMINGS["enter_auction_interval"]))
    pyautogui.press("esc")
    _sleep(t.get("exit_auction_interval", DEFAULT_TIMINGS["exit_auction_interval"]))
    reset_search(t, stop_event=stop_event, log=log)
    return result


def reset_search(t, stop_event=None, log=None):
    # Wait for FH6 focus before sending the reset keystrokes; if the user
    # clicks away, this will pause instead of sending Esc to other apps.
    try:
        if not window_utils.wait_for_fh6_focus(stop_event=stop_event):
            return
    except Exception:
        pass
    # final safety check
    try:
        if not window_utils.is_fh6_focused():
            if log:
                log("🔒 Reset aborted: FH6 not focused")
            return
    except Exception:
        return
    _sleep = stop_event.wait if stop_event is not None else time.sleep
    # Esc backs out of the auction screen — the transition out takes longer
    # than the Enters that re-open the search, so it has its own interval.
    pyautogui.press("esc")
    _sleep(t.get("exit_auction_interval", DEFAULT_TIMINGS["exit_auction_interval"]))
    pyautogui.press("\n")
    _sleep(t.get("enter_auction_interval", DEFAULT_TIMINGS["enter_auction_interval"]))
    pyautogui.press("\n")
    _sleep(t.get("load_cars_interval", DEFAULT_TIMINGS["load_cars_interval"]))


# -------------------------
# MAIN LOOP
# -------------------------


def sniper_loop(
    logger_callback,
    region,
    scans,
    timings,
    stop_event,
    status_callback=None,
    buyout_target=None,
):
    """
    Main sniper loop for detecting and buying cars.

    Args:
        logger_callback: Function to log messages
        region: Initial region from config (used as fallback)
        scans: Number of scan iterations (each one may refresh)
        timings: Timing configuration
        stop_event: threading.Event — set() to request stop; waits wake instantly
        status_callback: Optional callback for UI updates
        buyout_target: Optional max number of successful buys to stop at
    """
    try:
        # Prompt the user to focus FH6 before starting, then countdown
        try:
            logger_callback(
                "⚠️ Please focus Forza Horizon 6 now — click inside the FH6 window to allow inputs."
            )
        except Exception:
            pass

        # Pre-start countdown
        for i in range(5, 0, -1):
            if stop_event.is_set():
                logger_callback("🛑 Sniper stopped before starting")
                return
            logger_callback(f"Starting in {i}...")
            stop_event.wait(1)

        # compute regions once before loop
        logger_callback("🔍 Computing detection regions")
        config_region = region  # passed in from caller

        # prefer a manually-saved region from config if present
        cfg = load_config()
        manual_region = (
            tuple(cfg["AUCTION_OPTIONS_REGION"]) if "AUCTION_OPTIONS_REGION" in cfg else None
        )
        auto_region = (
            tuple(cfg["AUTO_AUCTION_OPTIONS_REGION"])
            if "AUTO_AUCTION_OPTIONS_REGION" in cfg
            else None
        )

        window = window_utils.get_fh6_window()
        if window:
            full_region = window_utils.get_window_region(window)
        else:
            full_region = None

        if manual_region:
            # If user manually calibrated, use that region for detection
            bottom_left_region = manual_region
            # ensure buy-detection has a sensible full_region fallback
            if full_region is None:
                full_region = manual_region
            logger_callback("✅ Using manual calibration")
        elif auto_region:
            # If auto calibrated, use that region for detection
            bottom_left_region = auto_region
            # ensure buy-detection has a sensible full_region fallback
            if full_region is None:
                full_region = auto_region
            logger_callback("✅ Using auto calibration")
        elif full_region:
            bottom_left_region = window_utils.bottom_left_quarter(full_region)
            logger_callback(
                f"✅ Using FH6 window bounds: {full_region}, bottom-left quarter: {bottom_left_region}"
            )
        else:
            full_region = config_region
            bottom_left_region = (
                window_utils.bottom_left_quarter(config_region) if config_region else None
            )
            logger_callback("⚠️  FH6 window not found, using configured region for scans")

        # Load sold-badge detection data, picking the best profile for this window size
        badge_params = load_badge_params(
            window.width if window else None, window.height if window else None
        )
        # Prefer the template selected during auto-calibration (pre-chosen for this
        # window size); fall back to the full-size template when not calibrated.
        sold_template = calibrator.load_sold_badge_template() or window_utils.resource_path(
            "assets/sold_badge_template.png"
        )
        if badge_params:
            logger_callback("🏷️  Sold-badge detection enabled")
        else:
            logger_callback("⚠️  docs/sold_badge_region.json missing — sold detection skipped")

        # Buy behavior: last available row (default, less competition) or
        # first available row (slightly faster attempt). Read once per run.
        buy_last = bool(cfg.get("BUY_LAST_AVAILABLE", True))
        target_desc = "last available" if buy_last else "first available"

        logger_callback("🚀 Sniper starting now!")
        successes = 0
        failures = 0
        buy_attempts = 0
        # refreshes = completed scan cycles. Every scan path (no car, all
        # sold, buy attempt) ends by refreshing the auction list, so this
        # increments exactly once per scan — the overlay shows it as
        # "Refreshed: N/total scans".
        refreshes = 0

        for i in range(scans):
            # stop if requested
            if stop_event.is_set():
                logger_callback("🛑 Sniper stopped by user")
                break

            try:
                if not window_utils.is_fh6_focused():
                    logger_callback("🛑 FH6 lost focus - stopping sniper")
                    stop_event.set()
                    break
            except Exception:
                logger_callback("🛑 Focus check error, stopping sniper")
                stop_event.set()
                break

            try:
                # One shared full-screen grab per scan — car_available() and
                # find_available_row() both use this frame, so a bad DXGI
                # capture fails consistently (button not found) rather than
                # car_available seeing the button on one frame and row detection
                # seeing a dark/empty frame from a second independent grab.
                shared_frame = vision_utils.grab_full_screen()

                if car_available(region=bottom_left_region, full_img=shared_frame):
                    # Auction button visible — check rows for sold cars before buying
                    win_now = window_utils.get_fh6_window()
                    row_regions = window_utils.get_row_regions(win_now) if win_now else []

                    if row_regions and badge_params:
                        available, saw_any_car = find_available_row(
                            row_regions,
                            badge_params,
                            sold_template,
                            log=logger_callback,
                            full_img=shared_frame,
                            buy_last=buy_last,
                        )
                    else:
                        available = 0  # no row data — attempt buy on current row
                        saw_any_car = True

                    if available < 0:
                        refreshes += 1
                        if saw_any_car:
                            logger_callback(f"Scan #{i + 1} 🏷️  All visible rows sold — resetting")
                        else:
                            logger_callback(
                                f"Scan #{i + 1} ⏳ Row 1 didn't render in time — resetting"
                            )
                        reset_search(timings, stop_event=stop_event, log=logger_callback)
                    else:
                        buy_attempts += 1
                        logger_callback(
                            f"Scan #{i + 1} ✅ Row {available + 1} ({target_desc}) — buying!"
                            f" (Attempt #{buy_attempts})"
                        )

                        # Navigate from row 1 (default) down to the target row
                        if available > 0:
                            nav_delay = timings.get("nav_interval", DEFAULT_TIMINGS["nav_interval"])
                            for _ in range(available):
                                pyautogui.press("down")
                                stop_event.wait(nav_delay)

                        if status_callback:
                            try:
                                status_callback(buy_attempts, successes, failures, refreshes, i + 1)
                            except Exception:
                                pass

                        result = buy_sequence(
                            timings,
                            full_region=full_region,
                            stop_event=stop_event,
                            log=logger_callback,
                        )
                        refreshes += 1
                        if result is True:
                            successes += 1
                            if buyout_target is not None and successes >= buyout_target:
                                logger_callback(
                                    f"🏁 Buyout target reached ({successes}/{buyout_target}) - stopping sniper"
                                )
                                stop_event.set()
                                break
                        elif result is False:
                            failures += 1

                    if status_callback:
                        try:
                            status_callback(buy_attempts, successes, failures, refreshes, i + 1)
                        except Exception:
                            pass

                else:
                    refreshes += 1
                    logger_callback(f"Scan #{i + 1} ❌ No car — refreshing...")
                    reset_search(timings, stop_event=stop_event)

                    if status_callback:
                        try:
                            status_callback(buy_attempts, successes, failures, refreshes, i + 1)
                        except Exception:
                            pass

            except Exception as scan_err:
                logger_callback(f"❌ Error during scan #{i + 1}: {scan_err}")
                stop_event.set()
                break
    except Exception as overall_err:
        try:
            logger_callback(f"🔴 Unhandled error in sniper loop: {overall_err}")
        except Exception:
            pass
        stop_event.set()

    finally:
        logger_callback("✅ Sniper stopped")
