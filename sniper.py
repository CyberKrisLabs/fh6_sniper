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
import vision_utils
import window_utils

# disable PyAutoGUI's built-in failsafe (moving mouse to corner raises
# an exception) since we handle focus checks ourselves and the popup
# message wasn't user-friendly in normal operation.
pyautogui.FAILSAFE = False

# Base confidence used for auto-calibrated templates. Other call sites
# already use lower, tuned thresholds (~0.65–0.72); 0.8 was too strict here.
CONFIDENCE = 0.7
SOLD_THRESHOLD = 0.68
CONFIG_FILE = window_utils.get_config_file()

# -------------------------
# CONFIG HELPERS
# -------------------------

DEFAULT_TIMINGS = {
    # interval used for both pre-press pause and menu navigation during buy attempts
    "buy_attempt_interval": 0.4,
    "post_buy_wait": 5.0,
    "reset_interval": 0.8,
}


def load_config():
    """Load config with safe defaults."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"⚠️  Config file missing or empty: {CONFIG_FILE}. Using defaults.")
        data = {}

    # Ensure timings exist
    if "TIMINGS" not in data:
        data["TIMINGS"] = DEFAULT_TIMINGS.copy()

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


def car_available(region, test=False):
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

        # determine which template to use based on the *full* window size.
        # the caller usually passes a cropped region (bottom-left quarter) so
        # using that directly would misclassify the window as "small".  we
        # still keep `region` unchanged for the actual screenshot search.
        win = window_utils.get_fh6_window()
        if win:
            full_window_region = window_utils.get_window_region(win)
        else:
            full_window_region = None

        # use the window region for template decisions; fall back to provided
        # region only when the window can't be located.
        size_region = full_window_region if full_window_region is not None else region

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
        auto_template_info = calibrator.load_auto_template_info()

        # Define base template path for reuse
        base_template = window_utils.resource_path("assets/auction_options_template.png")

        # If we have manual calibration with saved template info, use it directly
        if manual_region:
            if test:
                template_path = base_template
                scale_min = 0.4
                scale_max = 1
                scale_steps = 24
                confidence = 0.68
            else:
                manual_template_info = cfg.get("MANUAL_TEMPLATE_INFO", {})

                template_path = manual_template_info.get("template_path", base_template)
                scale = manual_template_info.get("scale")
                confidence = manual_template_info.get("confidence", 0.68)

                if scale is not None:
                    scale_min = scale
                    scale_max = scale
                    scale_steps = 1
                else:
                    # fallback if config exists but scale missing
                    scale_min = 0.4
                    scale_max = 1
                    scale_steps = 24

            location = vision_utils.locate_on_screen_with_variants(
                template_path,
                region=region,
                confidence=confidence,
                scale_min=scale_min,
                scale_max=scale_max,
                scale_steps=scale_steps,
                test=test,
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
            margin = scale * 0.12
            location = vision_utils.locate_on_screen_scaled(
                template_path,
                region=region,
                confidence=0.65,
                grayscale=True,
                scale_min=max(0.1, scale - margin),
                scale_max=min(1.5, scale + margin),
                scale_steps=7,
                debug=False,
            )
            return location is not None
        else:
            # No calibration - use the full variants approach
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
                hint_margin=0.12,
                debug=False,
            )
            return location is not None
    except Exception as e:
        print(f"Error in car_available: {e}")
        return False


# -------------------------
# ROW SCANNING
# -------------------------


def find_last_available_row(
    row_regions: list,
    badge_params: dict | None,
    sold_template: str,
    log=None,
) -> int:
    """Scan all visible rows and return the 0-based index of the LAST available one.

    Scans purely by screenshot — no key presses.  The caller navigates to the
    returned row with arrow-down presses after this function returns.

    Stops scanning at the first empty row (no car), since rows below it will
    also be empty.  Returns -1 if no available row is found.

    Targeting the last available row gives a competitive edge: most snipers go
    for row 1, so row 3 or 4 has less competition.

    Args:
        row_regions: list of (x, y, w, h) for each visible row.
        badge_params: dict from load_badge_params(), or None to skip sold detection.
        sold_template: absolute path to sold_badge_template.png.
    """
    last_available = -1

    # Capture the full screen once so every row comes from the same GPU frame.
    # Per-row grabs each hit the DXGI pipeline independently and can return
    # different (sometimes wrong) frames; a shared capture means rows are either
    # all-correct or all-wrong — if bad, all appear empty and the scan stops
    # safely instead of producing a false "available" on one row.
    full_img = vision_utils.grab_full_screen()

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

        if badge_params and os.path.isfile(sold_template):
            score = vision_utils.sold_badge_score(
                row_reg, badge_params, sold_template, row_img=row_img
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

    return last_available


# -------------------------
# ACTIONS
# -------------------------


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

        conf = 0.80
        scale_min = 0.5

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

        def _score(tpl_paths: list[str]) -> float:
            best = 0.0
            for tpl_path in tpl_paths:
                tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
                if tpl is None:
                    continue
                th, tw = tpl.shape[:2]
                for scale in np.linspace(1.0, scale_min, 18):
                    rh2 = int(th * scale)
                    rw2 = int(tw * scale)
                    if rh2 <= 0 or rw2 <= 0 or rh2 > sh or rw2 > sw:
                        continue
                    resized = cv2.resize(tpl, (rw2, rh2), interpolation=cv2.INTER_AREA)
                    res = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, _ = cv2.minMaxLoc(res)
                    if max_val > best:
                        best = max_val
            return best

        succ_score = _score(_variants(base_succ))
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
    interval = t.get("buy_attempt_interval", 0.4)
    _sleep(interval)

    pyautogui.typewrite(["down", "\n", "\n"], interval=interval)
    _sleep(t["post_buy_wait"])

    # Single grab shared by both template matches to avoid DXGI frame inconsistency.
    raw = vision_utils.grab_full_screen()
    if raw is None:
        raw = pyautogui.screenshot()

    result = _detect_buy_result(raw, full_region)

    # Retry while undetermined — the success/fail screen can appear late.
    # All retries happen BEFORE the reset keystrokes so we don't navigate away
    # before the screen has had a chance to render.
    retry_wait = t.get("buy_result_retry_wait", 0.8)
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

    pyautogui.typewrite(["\n", "esc", "esc", "\n", "\n"], interval=t["reset_interval"])
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
    pyautogui.typewrite(["esc", "\n", "\n"], interval=t["reset_interval"])


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
            logger_callback(f"✅ Using manual calibrated region: {manual_region}")
        elif auto_region:
            # If auto calibrated, use that region for detection
            bottom_left_region = auto_region
            # ensure buy-detection has a sensible full_region fallback
            if full_region is None:
                full_region = auto_region
            logger_callback(f"✅ Using auto calibrated region: {auto_region}")
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

        logger_callback("🚀 Sniper starting now!")
        successes = 0
        failures = 0
        buy_attempts = 0
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
                if car_available(region=bottom_left_region):
                    # Auction button visible — check rows for sold cars before buying
                    win_now = window_utils.get_fh6_window()
                    row_regions = window_utils.get_row_regions(win_now) if win_now else []

                    if row_regions and badge_params:
                        available = find_last_available_row(
                            row_regions, badge_params, sold_template, log=logger_callback
                        )
                    else:
                        available = 0  # no row data — attempt buy on current row

                    if available < 0:
                        refreshes += 1
                        logger_callback(f"Scan #{i + 1} 🏷️  All visible rows sold — resetting")
                        reset_search(timings, stop_event=stop_event, log=logger_callback)
                    else:
                        buy_attempts += 1
                        logger_callback(
                            f"Scan #{i + 1} ✅ Row {available + 1} (last available) — buying!"
                            f" (Attempt #{buy_attempts})"
                        )

                        # Navigate from row 1 (default) down to the target row
                        if available > 0:
                            nav_delay = max(0.08, timings.get("buy_attempt_interval", 0.4) * 0.2)
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
                        # After a buy attempt the auction list may still show the
                        # purchased car as available (server hasn't updated yet).
                        # reset_search forces a fresh query so the next scan reads
                        # current server state rather than the pre-buy cached results.
                        # The extra wait after reset lets the game finish loading
                        # search results before we scan again — without it the next
                        # car_available() check can catch the game mid-transition
                        # (loading screen / search form) and report False, causing
                        # the sniper to miss cars that are visually available.
                        refreshes += 1
                        reset_search(timings, stop_event=stop_event, log=logger_callback)
                        stop_event.wait(timings.get("reset_interval", 0.8))
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
