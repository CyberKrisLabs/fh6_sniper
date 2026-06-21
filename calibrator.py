"""Calibration utilities for Forza Horizon 6 sniper.

Functions:
- calibrate(): Manual calibration with mouse position capture
- auto_calibrate(): Automatic calibration using image recognition
- load_region(): Get calibration region from config
"""

import json
import os
import time

import pyautogui

import window_utils

CONFIG_FILE = window_utils.get_config_file()

# Padding in pixels
PADDING_LEFT = 20
PADDING_TOP = 20
PADDING_RIGHT = 20
PADDING_BOTTOM = 20


def calibrate(status_label=None, error_label=None):
    """Manual calibration: user hovers over top-left and bottom-right corners with visual guide."""

    def countdown(msg):
        for i in range(5, 0, -1):
            text = f"{msg} ({i})"
            if status_label:
                # Use default parameter to capture text value, not reference
                status_label.after(0, lambda t=text: status_label.config(text=t, bootstyle="info"))
            time.sleep(1)

    countdown("Move mouse to TOP-LEFT corner of Auction Options button")
    top_left_x, top_left_y = pyautogui.position()

    countdown("Move mouse to BOTTOM-RIGHT corner of Auction Options button")
    bottom_right_x, bottom_right_y = pyautogui.position()

    width = bottom_right_x - top_left_x
    height = bottom_right_y - top_left_y

    # Validate calibration: ensure mouse moved correctly
    if width <= 0 or height <= 0:
        error_msg = ""
        if width <= 0:
            error_msg += "Mouse moved horizontally in wrong direction (should move left to right). "
        if height <= 0:
            error_msg += "Mouse moved vertically in wrong direction (should move top to bottom)."

        print(f"❌ Calibration failed: {error_msg}")

        # Show error in dedicated error_label if provided, otherwise use status_label
        error_display = error_label if error_label else status_label
        if error_display:
            error_display.after(
                0,
                lambda msg=error_msg: error_display.config(
                    text=f"❌ Calibration failed: {msg}Try again!", bootstyle="danger"
                ),
            )
        return

    region = (
        top_left_x - PADDING_LEFT,
        top_left_y - PADDING_TOP,
        width + PADDING_LEFT + PADDING_RIGHT,
        height + PADDING_TOP + PADDING_BOTTOM,
    )

    return region


def get_default_region():
    """Return a default bottom-left region with padding if no calibration exists."""
    try:
        screen_width, screen_height = pyautogui.size()
    except Exception:
        screen_width, screen_height = 0, 0

    # Check for FH6 window for better default
    fh6_window = window_utils.get_fh6_window()
    if fh6_window:
        # Prioritize FH6 window bounds
        screen_width = fh6_window.width
        screen_height = fh6_window.height

    # Button dimensions
    w, h = 365, 75
    margin_left, margin_bottom = 10, 10

    if screen_width == 0 or screen_height == 0:
        return (0, 0, screen_width, screen_height)

    x1 = margin_left - PADDING_LEFT
    y1 = screen_height - h - margin_bottom - PADDING_TOP
    width = w + PADDING_LEFT + PADDING_RIGHT
    height = h + PADDING_TOP + PADDING_BOTTOM

    return (x1, y1, width, height)


def load_region():
    """Return region from config, or default if not calibrated."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return tuple(data["AUCTION_OPTIONS_REGION"])
    except Exception:
        return get_default_region()


def has_manual_region():
    """Return True if a manual AUCTION_OPTIONS_REGION exists in config."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return "AUCTION_OPTIONS_REGION" in data
    except Exception:
        return False


def has_auto_region():
    """Return True if an auto AUCTION_OPTIONS_REGION exists in config."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return "AUTO_AUCTION_OPTIONS_REGION" in data
    except Exception:
        return False


def reset_region(status_label=None):
    """Reset AUCTION_OPTIONS_REGION in config to default (or empty)."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    if "AUCTION_OPTIONS_REGION" in data:
        del data["AUCTION_OPTIONS_REGION"]

    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

    if status_label:
        status_label.after(
            0, lambda: status_label.config(text="Manual calibration: NOT SET", bootstyle="danger")
        )


def find_optimal_template_and_location(base_template):
    """Find the optimal template and scale for the current screen configuration.

    Returns:
        tuple: (template_path, scale, location) or None if not found
    """
    import vision_utils

    # Get window size for template selection
    win = window_utils.get_fh6_window()
    if win:
        size_region = window_utils.get_window_region(win)
    else:
        # Fall back to full screen if window not found
        import pyautogui

        screen_w, screen_h = pyautogui.size()
        size_region = (0, 0, screen_w, screen_h)

    # Choose the primary template based on window size
    template_path, category = vision_utils.choose_template(
        base_template, region=size_region, debug=False
    )

    # Try the primary template first with scale detection
    result = find_template_at_best_scale(template_path)
    if result:
        scale, location = result
        return template_path, scale, location

    # If primary template fails, try other variants
    candidates = []

    # Add other variants if they exist (1024x768 first — it's a closer match for
    # small-resolution games and the full template may not match at all)
    small = base_template.replace(".png", "_1024x768.png")
    if os.path.isfile(window_utils.resource_path(small)):
        candidates.append(small)

    med = base_template.replace(".png", "_med.png")
    if os.path.isfile(window_utils.resource_path(med)):
        candidates.append(med)

    candidates.append(base_template)  # full size

    # Remove the primary template if it's already in candidates
    if template_path in candidates:
        candidates.remove(template_path)

    # Try each candidate
    for candidate in candidates:
        candidate_path = window_utils.resource_path(candidate)
        result = find_template_at_best_scale(candidate_path)
        if result:
            scale, location = result
            return candidate_path, scale, location

    return None


def find_template_at_best_scale(template_path):
    """Find the best scale for a specific template.

    Returns:
        tuple: (scale, location) or None if not found
    """
    import cv2
    import numpy as np

    try:
        # Load template
        template_color = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template_color is None:
            return None

        template_gray = cv2.cvtColor(template_color, cv2.COLOR_BGR2GRAY)
        template_h, template_w = template_gray.shape[:2]

        # Take screenshot
        import pyautogui

        screenshot = pyautogui.screenshot()
        screen_img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        screen_gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
        screen_h, screen_w = screen_gray.shape[:2]

        # Try different scales. Go above 1.0 so the template can match a larger
        # button in fullscreen mode (where the game renders at the monitor's
        # native resolution and the button is physically bigger than the template).
        scales_to_try = np.linspace(1.5, 0.4, 24)

        for scale in scales_to_try:
            t_h = int(template_h * scale)
            t_w = int(template_w * scale)

            if t_h <= 0 or t_w <= 0 or t_h > screen_h or t_w > screen_w:
                continue

            resized = cv2.resize(template_gray, (t_w, t_h), interpolation=cv2.INTER_AREA)

            result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            # Use a threshold in line with the rest of the app's detectors
            # (typically ~0.65–0.72 rather than 0.8, which is too strict here).
            if max_val >= 0.7:
                match_left = max_loc[0]
                match_top = max_loc[1]
                return scale, (match_left, match_top, t_w, t_h)

    except Exception as e:
        print(f"Error in find_template_at_best_scale: {e}")

    return None


def find_template_at_best_scale_in_region(
    template_path,
    region,
    scale_min=0.3,
    scale_max=1.2,
    scale_steps=7,
    confidence=0.65,
):
    """Like find_template_at_best_scale but searches only inside *region*.

    Used to verify that the saved calibration parameters actually detect
    the button in the saved region (not just anywhere on screen).

    Returns True if found, False otherwise.
    """
    import cv2
    import numpy as np
    import pyautogui

    try:
        template_color = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template_color is None:
            return False
        template_gray = cv2.cvtColor(template_color, cv2.COLOR_BGR2GRAY)
        template_h, template_w = template_gray.shape[:2]

        screenshot = pyautogui.screenshot(region=region)
        screen_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        screen_h, screen_w = screen_gray.shape[:2]

        for scale in np.linspace(scale_max, scale_min, scale_steps):
            t_h = int(template_h * scale)
            t_w = int(template_w * scale)
            if t_h <= 0 or t_w <= 0 or t_h > screen_h or t_w > screen_w:
                continue
            resized = cv2.resize(template_gray, (t_w, t_h), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val >= confidence:
                return True
    except Exception as e:
        print(f"Error in find_template_at_best_scale_in_region: {e}")
    return False


def select_sold_badge_template(win=None) -> str:
    """Return the best-fit sold badge template path for the current window size.

    Uses the same choose_template() logic as detect_sold() so calibration and
    scanning always agree on which file to use.  Falls back to the full-size
    template when the window cannot be detected.
    """
    import vision_utils

    base = window_utils.resource_path("assets/sold_badge_template.png")
    if win is None:
        win = window_utils.get_fh6_window()
    if win:
        region = window_utils.get_window_region(win)
        chosen, _ = vision_utils.choose_template(base, region=region)
        return chosen
    return base


def auto_calibrate_sold_badge(status_label=None) -> dict | None:
    """Detect the sold badge position by scanning visible auction rows.

    When Windows OCR is available (winrt packages installed), finds yellow blobs
    in each row and reads their text — the blob that says "SOLD" is the badge.
    Falls back to template matching when OCR is unavailable.

    Returns the saved dict, or None if no badge was found.
    Call this while a sold car is visible in the auction list.
    """
    import asyncio

    import cv2
    import numpy as np

    import vision_utils

    def _status(msg: str) -> None:
        print(msg)
        if status_label:
            try:
                status_label.after(0, lambda t=msg: status_label.config(text=t, bootstyle="info"))
            except Exception:
                pass

    win = window_utils.get_fh6_window()
    if not win:
        _status("❌ Badge calibration: FH6 window not found")
        return None

    row_regions = window_utils.get_row_regions(win)
    if not row_regions:
        _status("❌ Badge calibration: no row regions detected")
        return None

    _status("Detecting sold badge…")
    full_img = vision_utils.grab_full_screen()
    if full_img is None:
        full_img = pyautogui.screenshot()

    # Badge is always in the left portion of the row, away from price/timer UI.
    SEARCH_X_FRACTION = 0.55

    best_info: dict | None = None

    if vision_utils._winrt_available():
        # OCR path: find yellow blobs in each row, read their text.
        # The blob that contains "SOLD" (but not "NOT SOLD") is the badge.
        _status("Scanning auction rows for SOLD badge…")

        for row_idx, (rx, ry, rw, rh) in enumerate(row_regions):
            search_w = int(rw * SEARCH_X_FRACTION)
            row_pil = full_img.crop((rx, ry, rx + search_w, ry + rh))
            row_bgr = cv2.cvtColor(np.array(row_pil), cv2.COLOR_RGB2BGR)

            # Find yellow blobs — the sold badge is a distinct yellow rectangle.
            hsv = cv2.cvtColor(row_bgr, cv2.COLOR_BGR2HSV)
            yellow_mask = cv2.inRange(hsv, np.array([24, 100, 100]), np.array([38, 255, 255]))
            contours, _ = cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue

            # Try each yellow blob, largest first.
            for contour in sorted(contours, key=cv2.contourArea, reverse=True):
                if cv2.contourArea(contour) < search_w * rh * 0.005:
                    break  # remaining blobs are too small to be a badge
                bx, by, bw, bh_badge = cv2.boundingRect(contour)
                pad = max(4, int(rh * 0.05))
                crop = row_bgr[
                    max(0, by - pad) : min(row_bgr.shape[0], by + bh_badge + pad),
                    max(0, bx - pad) : min(row_bgr.shape[1], bx + bw + pad),
                ]
                try:
                    text = asyncio.run(vision_utils._winrt_ocr_async(crop))
                except Exception:
                    continue

                text_up = text.upper().strip()
                # "NOT SOLD" badges also contain "SOLD" — exclude them.
                # The yellow gate already filters red "Not Sold" badges, but
                # we check the text too in case of unexpected badge colours.
                if "SOLD" not in text_up or "NOT SOLD" in text_up:
                    continue

                _status(f"✅ Badge found in row {row_idx + 1} (OCR: '{text.strip()}')")
                best_info = {
                    "row_idx": row_idx,
                    "rx": rx,
                    "ry": ry,
                    "rw": rw,
                    "rh": rh,
                    "match_x": bx,
                    "match_y": by,
                    "match_w": bw,
                    "match_h": bh_badge,
                }
                break
            if best_info:
                break

        if best_info is None:
            _status(
                "❌ No SOLD badge detected. "
                "Make sure a sold car is visible in the auction list and try again."
            )
            return None

    else:
        # Template matching fallback (when WinRT OCR packages are not installed).
        base_tpl = window_utils.resource_path("assets/sold_badge_template.png")
        candidates = []
        for suffix in ("", "_med", "_1024x768"):
            p = base_tpl.replace(".png", f"{suffix}.png")
            if os.path.isfile(p):
                candidates.append(p)

        best_score = 0.0
        best_template_name = ""
        tpl_best_scores: dict[str, float] = {}
        MIN_W_PCT = 0.08
        MIN_H_PCT = 0.20

        for row_idx, (rx, ry, rw, rh) in enumerate(row_regions):
            search_w = int(rw * SEARCH_X_FRACTION)
            row_pil = full_img.crop((rx, ry, rx + search_w, ry + rh))
            row_bgr = cv2.cvtColor(np.array(row_pil), cv2.COLOR_RGB2BGR)
            sh, sw = row_bgr.shape[:2]
            min_tw = max(4, int(rw * MIN_W_PCT))
            min_th = max(4, int(rh * MIN_H_PCT))

            for tpl_path in candidates:
                tpl = cv2.imread(tpl_path)
                if tpl is None:
                    continue
                tpl_name = os.path.basename(tpl_path)
                tpl_row_best = 0.0
                for scale in np.linspace(1.2, 0.1, 30):
                    th = int(tpl.shape[0] * scale)
                    tw = int(tpl.shape[1] * scale)
                    if tw < min_tw or th < min_th or th > sh or tw > sw:
                        continue
                    resized = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
                    result = cv2.matchTemplate(row_bgr, resized, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val > tpl_row_best:
                        tpl_row_best = max_val
                    if max_val > best_score:
                        best_score = max_val
                        best_template_name = tpl_name
                        best_info = {
                            "row_idx": row_idx,
                            "rx": rx,
                            "ry": ry,
                            "rw": rw,
                            "rh": rh,
                            "match_x": max_loc[0],
                            "match_y": max_loc[1],
                            "match_w": tw,
                            "match_h": th,
                        }
                if tpl_row_best > tpl_best_scores.get(tpl_name, 0.0):
                    tpl_best_scores[tpl_name] = tpl_row_best

        _status("📊 Badge calibration scores (best match per template across all rows):")
        for tname, score in sorted(tpl_best_scores.items(), key=lambda x: -x[1]):
            marker = " ← SELECTED" if tname == best_template_name else ""
            _status(f"   {tname}: {score:.3f}{marker}")

        MIN_DETECTION_SCORE = 0.45
        if best_info is None or best_score < MIN_DETECTION_SCORE:
            _status(
                f"❌ Badge calibration: no sold badge found "
                f"(best score={best_score:.3f}, need ≥{MIN_DETECTION_SCORE}). "
                "Make sure a sold car is visible in the auction list."
            )
            return None

    # --- Save badge parameters (common to both paths) ---
    rw, rh_val = best_info["rw"], best_info["rh"]
    result_dict = {
        "badge_x_pct": round(best_info["match_x"] / rw, 4) if rw else 0,
        "badge_y_pct": round(best_info["match_y"] / rh_val, 4) if rh_val else 0,
        "badge_w_pct": round(best_info["match_w"] / rw, 4) if rw else 0,
        "badge_h_pct": round(best_info["match_h"] / rh_val, 4) if rh_val else 0,
        "badge_dx_px": best_info["match_x"],
        "badge_dy_px": best_info["match_y"],
        "badge_w_px": best_info["match_w"],
        "badge_h_px": best_info["match_h"],
        "row_ref_px": [rw, rh_val],
        "calibration_score": 1.0,
        "note": (
            "Auto-calibrated by auto_calibrate_sold_badge(). "
            "Percentages are relative to the row card (width, height). "
            "Apply to any row: badge_x = row_x + row_w * badge_x_pct, etc."
        ),
    }

    window_utils.save_badge_params(
        result_dict, win.width, win.height, window_utils._get_display_dpr()
    )

    try:
        ax = best_info["rx"] + best_info["match_x"]
        ay = best_info["ry"] + best_info["match_y"]
        mw, mh = best_info["match_w"], best_info["match_h"]
        badge_crop = full_img.crop((ax, ay, ax + mw, ay + mh))
        captured_path = window_utils.get_user_data_file("sold_badge_captured_template.png")
        badge_crop.save(captured_path)
        try:
            with open(CONFIG_FILE) as f:
                _cfg = json.load(f)
        except FileNotFoundError:
            _cfg = {}
        _cfg["CAPTURED_SOLD_BADGE_TEMPLATE"] = captured_path
        with open(CONFIG_FILE, "w") as f:
            json.dump(_cfg, f, indent=2)
        _status("📸 Sold badge snapshot saved.")
    except Exception as _e:
        _status(f"⚠️ Could not capture badge template: {_e}")

    row_num = best_info["row_idx"] + 1
    _status(f"✅ Sold badge detected in row {row_num} and saved.")
    return result_dict


def has_sold_badge_auto_cal() -> bool:
    """Return True if an auto-calibrated sold badge template is saved in config."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return "AUTO_SOLD_BADGE_TEMPLATE" in data
    except Exception:
        return False


def load_sold_badge_template() -> str | None:
    """Return the auto-calibrated sold badge template path, or None if not set."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return data.get("AUTO_SOLD_BADGE_TEMPLATE")
    except Exception:
        return None


def load_captured_badge_template() -> str | None:
    """Return the pixel-captured badge template path if it exists, else None."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        path = data.get("CAPTURED_SOLD_BADGE_TEMPLATE")
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


def reset_sold_badge_auto_cal() -> None:
    """Remove AUTO_SOLD_BADGE_TEMPLATE from config."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data.pop("AUTO_SOLD_BADGE_TEMPLATE", None)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def auto_calibrate(status_label=None):
    """Auto calibrate: detect the auction options button and select the best sold
    badge template for the current window size.  Both results are saved to config
    so the sniper can use them without re-running variant searches every scan.
    """

    def countdown(msg):
        for i in range(5, 0, -1):
            text = f"{msg} ({i})"
            print(text)
            if status_label:
                status_label.after(0, lambda t=text: status_label.config(text=t, bootstyle="info"))
            time.sleep(1)

    countdown(
        "Make sure FH6 is in focus, AUCTION OPTIONS is visible, and at least one SOLD car is in the auction list. Calibration starts in 5 seconds."
    )

    try:
        if status_label:
            status_label.after(
                0,
                lambda: status_label.config(
                    text="Calibrating... looking for Auction Options button on screen, this may take a moment.",
                    bootstyle="warning",
                ),
            )

        base_template = "assets/auction_options_template.png"
        result = find_optimal_template_and_location(base_template)

        if result is None:
            print("❌ Auto calibration failed: Could not find Auction Options button")
            return False

        template_path, scale, location = result
        left, top, width, height = location

        region = (
            left - PADDING_LEFT,
            top - PADDING_TOP,
            width + PADDING_LEFT + PADDING_RIGHT,
            height + PADDING_TOP + PADDING_BOTTOM,
        )

        # Select the best sold badge template for the current window size
        sold_tpl = select_sold_badge_template()

        cfg_update = {
            "AUTO_AUCTION_OPTIONS_REGION": region,
            "AUTO_AUCTION_OPTIONS_TEMPLATE": template_path,
            "AUTO_AUCTION_OPTIONS_SCALE": scale,
            "AUTO_SOLD_BADGE_TEMPLATE": sold_tpl,
        }
        try:
            with open(CONFIG_FILE) as f:
                existing = json.load(f)
            existing.update(cfg_update)
            # Auto-cal supersedes manual cal — remove stale manual keys so the
            # auto-cal region is actually used during scanning.
            for stale_key in ("AUCTION_OPTIONS_REGION", "MANUAL_TEMPLATE_INFO"):
                existing.pop(stale_key, None)
            cfg_update = existing
        except FileNotFoundError:
            pass

        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg_update, f, indent=2)

        print("✅ Auction Options button found and calibrated.")

        # Detect and save sold badge position from the current screen.
        if status_label:
            status_label.after(
                0,
                lambda: status_label.config(
                    text="Calibrating sold badge position…", bootstyle="warning"
                ),
            )
        badge_result = auto_calibrate_sold_badge(status_label)
        badge_ok = badge_result is not None
        if not badge_ok:
            print(
                "⚠️  Sold badge position could not be detected — make sure a SOLD car "
                "is visible in the auction list and try again. "
                "The sniper will still work using the built-in badge templates."
            )

        # Verify the saved parameters still detect the button in the saved region.
        margin = scale * 0.12
        verify = find_template_at_best_scale_in_region(
            template_path,
            region=region,
            scale_min=max(0.1, scale - margin),
            scale_max=min(1.5, scale + margin),
            scale_steps=7,
            confidence=0.65,
        )
        if verify:
            print("✅ Calibration verified successfully.")
        else:
            print(
                "⚠️  Calibration saved but could not be verified — "
                "try recalibrating with the auction screen clearly visible."
            )
        return True, verify, badge_ok

    except Exception as e:
        print(f"❌ Auto calibration error: {e}")
        if status_label:
            err_text = f"Auto calibration: ERROR - {e}"
            status_label.after(
                0,
                lambda t=err_text: status_label.config(text=t, bootstyle="danger"),
            )


def load_auto_region():
    """Return auto-calibrated region from config, or None if not set."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return tuple(data["AUTO_AUCTION_OPTIONS_REGION"])
    except Exception:
        return None


def load_auto_template_info():
    """Return auto-calibrated template path and scale, or None if not set."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        # Try new keys first, then fall back to old keys for backward compatibility
        template_path = data.get("AUTO_AUCTION_OPTIONS_TEMPLATE") or data.get("AUTO_TEMPLATE_PATH")
        scale = data.get("AUTO_AUCTION_OPTIONS_SCALE") or data.get("AUTO_SCALE")
        if template_path and scale is not None:
            return template_path, scale
    except Exception:
        pass
    return None


def reset_auto_region(status_label=None):
    """Reset AUTO_AUCTION_OPTIONS_REGION in config."""
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    # Clear all auto calibration data
    keys_to_remove = [
        "AUTO_AUCTION_OPTIONS_REGION",
        "AUTO_AUCTION_OPTIONS_TEMPLATE",
        "AUTO_AUCTION_OPTIONS_SCALE",
        "AUTO_SOLD_BADGE_TEMPLATE",
        "CAPTURED_SOLD_BADGE_TEMPLATE",
    ]

    for key in keys_to_remove:
        if key in data:
            del data[key]

    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

    if status_label:
        status_label.after(
            0, lambda: status_label.config(text="Auto calibration: NOT SET", bootstyle="danger")
        )
