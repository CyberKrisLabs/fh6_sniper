"""
Window utility module for Forza Horizon 6 detection.
Provides functions to locate the FH6 window and get dynamic regions for image detection.
"""

import json
import os
import sys

import pyautogui
import pygetwindow as gw


def _get_display_dpr() -> float:
    """Return the display device pixel ratio (e.g. 1.5 for 150 % scaling).

    Row percentages stored by tune_rows.py are in Qt logical space.
    pyautogui uses physical pixels.  Multiplying by DPR bridges the two.
    Uses GetDpiForMonitor (shcore.dll) which returns the real effective DPI
    regardless of process DPI-awareness mode.
    """
    try:
        import ctypes
        import ctypes.wintypes

        pt = ctypes.wintypes.POINT(0, 0)
        monitor = ctypes.windll.user32.MonitorFromPoint(pt, 1)  # MONITOR_DEFAULTTOPRIMARY
        dpi_x = ctypes.c_uint(96)
        dpi_y = ctypes.c_uint(96)
        hr = ctypes.windll.shcore.GetDpiForMonitor(
            monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
        )
        if hr == 0:
            return dpi_x.value / 96.0
    except Exception:
        pass
    # Qt fallback (works when called from the GUI process)
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen:
            return float(screen.devicePixelRatio())
    except Exception:
        pass
    return 1.0


def resource_path(relative_path: str) -> str:
    """Return an absolute path to a resource, handling PyInstaller bundling.

    The assets directory and other data files are stored alongside the
    executable when packaged. During development ``__file__`` is used instead.
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base, relative_path)


def get_user_data_file(filename: str) -> str:
    """Return a user-writable path for a runtime data file.

    When running from source: returns ``docs/<filename>`` so calibration data
    stays in the repo as before.
    When running as a compiled exe (PyInstaller): returns
    ``%APPDATA%\\FH6Sniper\\<filename>``. (No seeding from bundled defaults —
    docs/ is deliberately not included in the PyInstaller bundle; these files
    are created by calibration/tuning on first use.)
    """
    if not getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", filename)

    app_data = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(app_data, "FH6Sniper")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, filename)


def get_config_file() -> str:
    """Return the full path to config.json in a user-writable location.

    On Windows, uses %APPDATA%/FH6Sniper/config.json so the app can write
    configuration even when installed in Program Files. Creates the directory
    if it doesn't exist.
    """
    try:
        # Use APPDATA for user config (Windows standard)
        app_data = os.environ.get("APPDATA")
        if app_data:
            config_dir = os.path.join(app_data, "FH6Sniper")
        else:
            # Fallback to home directory
            config_dir = os.path.expanduser("~/.fh6sniper")

        # Create directory if it doesn't exist
        os.makedirs(config_dir, exist_ok=True)

        return os.path.join(config_dir, "config.json")
    except Exception as e:
        # Final fallback: use current directory (development mode)
        print(f"⚠️  Could not determine config directory: {e}, using local config.json")
        return "config.json"


def get_fh6_window():
    """
    Retrieves the Forza Horizon 6 window object.

    Returns:
        pygetwindow.Window: The FH6 window object, or None if not found.
    """
    try:
        windows = gw.getWindowsWithTitle("Forza Horizon 6")
        if windows:
            return windows[0]
        return None
    except Exception as e:
        print(f"⚠️  Error retrieving FH6 window: {e}")
        return None


def get_window_region(window):
    """
    Converts a pygetwindow.Window object to a PyAutoGUI region tuple in physical
    display pixels.

    pygetwindow reports coordinates in **logical** units, which are affected by
    Windows DPI scaling.  Screenshots taken by PyAutoGUI are in physical
    pixels, so we need to scale the window dimensions accordingly or the
    regions will be wrong (as observed when the reported window width was half
    of the true pixel width).

    Args:
        window: A pygetwindow.Window object.

    Returns:
        tuple: (left, top, width, height) suitable for pyautogui.locateOnScreen(),
               or None on error.
    """
    if window is None:
        return None

    try:
        # raw logical values
        left, top, w, h = window.left, window.top, window.width, window.height

        # compute scaling factors between logical system metrics and physical
        import ctypes

        import pyautogui

        logical_w = ctypes.windll.user32.GetSystemMetrics(0)
        logical_h = ctypes.windll.user32.GetSystemMetrics(1)
        phys_w, phys_h = pyautogui.size()

        scale_x = phys_w / logical_w if logical_w else 1.0
        scale_y = phys_h / logical_h if logical_h else 1.0

        scaled = (
            int(left * scale_x),
            int(top * scale_y),
            int(w * scale_x),
            int(h * scale_y),
        )

        return scaled
    except Exception as e:
        print(f"⚠️  Error converting window to region: {e}")
        return None


def is_window_fullscreen_like(window):
    """
    Checks if a window is fullscreen or borderless fullscreen based on size.

    Args:
        window: A pygetwindow.Window object.

    Returns:
        bool: True if the window is approximately fullscreen size.
    """
    if window is None:
        return False

    try:
        screen_w, screen_h = pyautogui.size()
        # Allow small tolerance for window decorations
        width_match = abs(window.width - screen_w) < 10
        height_match = abs(window.height - screen_h) < 10
        return width_match and height_match
    except Exception as e:
        print(f"⚠️  Error checking fullscreen status: {e}")
        return False


def get_fh6_region_safe(fallback_region=None):
    """
    Safely retrieves the FH6 window region with graceful fallback.
    Logs warnings to console if window not found but doesn't crash.

    Args:
        fallback_region: Default region to use if FH6 window not found.
                        If None, returns None (caller must handle).

    Returns:
        tuple: (left, top, width, height) or fallback_region or None
    """
    window = get_fh6_window()

    if window is None:
        print("WARNING: Forza Horizon 6 window not found. Using fallback region.")
        return fallback_region

    # Log fullscreen status for debugging
    fullscreen = is_window_fullscreen_like(window)
    mode = "fullscreen-like" if fullscreen else "windowed"
    print(
        f"FH6 window detected ({mode}): {window.left}, {window.top}, {window.width}x{window.height}"
    )

    region = get_window_region(window)
    return region if region else fallback_region


# ── Auction row geometry ──────────────────────────────────────────────────────
# Percentages of window width/height.  ROW_X_PCT is the physical fraction —
# derived from two calibration points at 150 % DPI (see docs/sold-detection.md).

ROW_X_PCT = 0.041
ROW_Y_START_PCT = 0.1095
ROW_HEIGHT_PCT = 0.1163
ROW_WIDTH_PCT = 0.2999
ROW_GAP_PCT = 0.0049
ROW_STEP_PCT = ROW_HEIGHT_PCT + ROW_GAP_PCT


def get_row_regions(win, num_rows: int = 4) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) regions for auction list rows in pyautogui screen coords.

    Loads per-row tuning from docs/row_regions_tuned.json when available;
    falls back to the formula constants otherwise.

    Row percentages are stored in Qt logical space by tune_rows.py, so we
    apply the display DPR when converting to physical pyautogui coordinates
    (same approach as tools/test_detection.py _get_row_regions).
    """
    tuned = get_tuned_row_regions(win, num_rows)
    if tuned:
        return tuned
    wx, wy, ww, wh = win.left, win.top, win.width, win.height
    dpr = _get_display_dpr()
    game_w_log = ww / dpr

    # Snap window height to nearest standard game resolution height so that the
    # OS window chrome (title bar + borders) is excluded from the row geometry.
    _STD_H = [480, 600, 720, 768, 800, 900, 1080, 1200, 1440, 1600, 1800, 2160]
    game_h_log = wh / dpr
    content_h_log = max((h for h in _STD_H if h <= game_h_log), default=int(game_h_log))
    content_h_phys = int(content_h_log * dpr)
    title_h_phys = wh - content_h_phys

    # FH6 auction cards stop shrinking below ~1600 logical game width.
    card_scale = max(1.0, 1600.0 / max(game_w_log, 1))

    x = int(wx + ww * ROW_X_PCT)
    y0 = int(wy + title_h_phys + content_h_phys * ROW_Y_START_PCT)
    w = int(ww * ROW_WIDTH_PCT * card_scale)
    h = int(content_h_phys * ROW_HEIGHT_PCT * card_scale)
    step = int(content_h_phys * ROW_STEP_PCT * card_scale)
    return [(x, y0 + i * step, w, h) for i in range(num_rows)]


def best_matching_row_profile(
    profiles: list[dict], win_w: int, win_h: int, dpr: float = 1.0
) -> dict:
    """Return the profile closest to the current window, matched on LOGICAL dimensions.

    Matching on logical (physical ÷ DPR) rather than physical pixels makes profiles
    DPI-independent: the same game window at the same in-game resolution always has the
    same logical size regardless of the OS scaling setting.

    Score = max(|log_w/ref_log_w − 1|, |log_h/ref_log_h − 1|) — lower is better.
    """
    log_w = win_w / dpr
    log_h = win_h / dpr
    best: dict = profiles[0]
    best_score = float("inf")
    for p in profiles:
        ref = p.get("window_ref_physical", {})
        ref_dpr = ref.get("dpr", 1.0)
        ref_log_w = ref.get("width", 1) / ref_dpr
        ref_log_h = ref.get("height", 1) / ref_dpr
        score = max(abs(log_w / ref_log_w - 1), abs(log_h / ref_log_h - 1))
        if score < best_score:
            best_score = score
            best = p
    return best


# Tuned-rows JSON cached by mtime — get_row_regions runs on every scan with
# a car present, and the file only changes when the user re-runs the tuner.
_tuned_rows_cache: dict = {"mtime": None, "data": None}


def _load_tuned_rows_cached(path: str) -> dict | None:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _tuned_rows_cache["mtime"] != mtime:
        with open(path) as f:
            _tuned_rows_cache["data"] = json.load(f)
        _tuned_rows_cache["mtime"] = mtime
    return _tuned_rows_cache["data"]


def get_tuned_row_regions(win, num_rows: int = 4) -> list[tuple[int, int, int, int]]:
    """Load per-row tuning from docs/row_regions_tuned.json and return screen coords.

    Supports both legacy flat-format ({"rows": [...]}) and multi-profile format
    ({"profiles": [{window_ref_physical, rows}, ...]}). Auto-selects the closest
    profile for the current window size; falls back to the formula if >30% off.

    Returns an empty list if the file is missing or cannot be applied.
    """
    tuned_path = get_user_data_file("row_regions_tuned.json")
    if not os.path.isfile(tuned_path):
        return []
    try:
        data = _load_tuned_rows_cached(tuned_path)
        if data is None:
            return []

        dpr = _get_display_dpr()

        if "profiles" in data:
            profiles = data["profiles"]
            if not profiles:
                return []
            profile = best_matching_row_profile(profiles, win.width, win.height, dpr)
            ref = profile.get("window_ref_physical", {})
            ref_dpr = ref.get("dpr", 1.0)
            mismatch = max(
                abs((win.width / dpr) / (ref.get("width", 1) / ref_dpr) - 1),
                abs((win.height / dpr) / (ref.get("height", 1) / ref_dpr) - 1),
            )
            if mismatch > 0.30:
                return []  # no profile close enough; let caller fall back to formula
            rows_pct = profile.get("rows", [])
        else:
            rows_pct = data.get("rows", [])

        if not rows_pct:
            return []
        wx, wy, ww, wh = win.left, win.top, win.width, win.height
        result = []
        for r in rows_pct[:num_rows]:
            # Percentages are physical fractions; pygetwindow and pyautogui both
            # use physical pixels so no DPR conversion is needed here.
            result.append(
                (
                    int(wx + ww * r["x_pct"]),
                    int(wy + wh * r["y_pct"]),
                    int(ww * r["w_pct"]),
                    int(wh * r["h_pct"]),
                )
            )
        return result
    except Exception as e:
        print(f"⚠️  get_tuned_row_regions: {e}")
        return []


_BADGE_REGION_PATH = get_user_data_file("sold_badge_region.json")


def load_badge_params(win_w: int | None = None, win_h: int | None = None) -> dict | None:
    """Load sold-badge region params for the given window size.

    Supports both legacy flat format and multi-profile format.
    When win_w/win_h are given, picks the closest matching profile.
    Returns a flat dict with badge_x_pct, badge_y_pct, etc., or None if unavailable.
    """
    try:
        with open(_BADGE_REGION_PATH) as f:
            data = json.load(f)
        if "profiles" in data:
            profiles = data["profiles"]
            if not profiles:
                return None
            if win_w and win_h:
                dpr = _get_display_dpr()
                return best_matching_row_profile(profiles, win_w, win_h, dpr)
            return profiles[0]
        return data  # legacy flat format
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_badge_params(params: dict, win_w: int, win_h: int, dpr: float = 1.0) -> None:
    """Save badge params as a profile in sold_badge_region.json (multi-profile format).

    Replaces an existing profile within 5% of win_w/win_h, or appends a new one.
    """
    try:
        with open(_BADGE_REGION_PATH) as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}

    if "profiles" in existing:
        profiles = list(existing["profiles"])
    elif any(k.startswith("badge_") for k in existing):
        # Migrate legacy flat format to multi-profile
        old_ref = existing.get("window_ref_physical", {"width": win_w, "height": win_h})
        old_label = f"{old_ref.get('width', win_w)}x{old_ref.get('height', win_h)}"
        profiles = [
            {
                "label": old_label,
                "window_ref_physical": old_ref,
                **{k: v for k, v in existing.items() if k != "window_ref_physical"},
            }
        ]
    else:
        profiles = []

    new_profile = {
        "label": f"{win_w}x{win_h}",
        "window_ref_physical": {"width": win_w, "height": win_h, "dpr": dpr},
        **params,
    }

    curr_log_w = win_w / dpr
    curr_log_h = win_h / dpr
    replaced = False
    for idx, p in enumerate(profiles):
        ref = p.get("window_ref_physical", {})
        ref_dpr = ref.get("dpr", 1.0)
        ref_log_w = ref.get("width", 1) / ref_dpr
        ref_log_h = ref.get("height", 1) / ref_dpr
        score = max(abs(curr_log_w / ref_log_w - 1), abs(curr_log_h / ref_log_h - 1))
        if score <= 0.05:
            profiles[idx] = new_profile
            replaced = True
            break
    if not replaced:
        profiles.append(new_profile)

    os.makedirs(os.path.dirname(_BADGE_REGION_PATH), exist_ok=True)
    with open(_BADGE_REGION_PATH, "w") as f:
        json.dump({"profiles": profiles}, f, indent=2)


def has_manual_badge_profile() -> bool:
    """Return True if a manually hover-captured sold badge profile is saved.

    Distinguishes manual calibration (ui/tabs/calibration.py::_save_badge_from_clicks)
    from auto calibration (calibrator.py::auto_calibrate_sold_badge) via the "note"
    field both writers stamp onto their profile.
    """
    try:
        with open(_BADGE_REGION_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    if "profiles" in data:
        profiles = data["profiles"]
    elif any(k.startswith("badge_") for k in data):
        profiles = [data]  # legacy flat format
    else:
        profiles = []
    return any("Manually calibrated" in str(p.get("note", "")) for p in profiles)


def bottom_left_quarter(region):
    """
    Return a subregion corresponding to the bottom-left quarter of the given region.

    Args:
        region (tuple): (left, top, width, height)

    Returns:
        tuple: cropped region (left, new_top, new_width, new_height)
    """
    if not region:
        return None
    try:
        left, top, width, height = region
        new_width = width // 2
        new_height = height // 2
        # bottom-left: top moves down by half the height
        new_top = top + height - new_height
        return (left, new_top, new_width, new_height)
    except Exception as e:
        print(f"⚠️  Error cropping region to bottom-left quarter: {e}")
        return region


def _get_foreground_window_title():
    """Return the current foreground window title (Unicode)."""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


def is_fh6_focused():
    """Return True if the foreground window title looks like Forza Horizon.

    Uses a substring match on 'forza' (case-insensitive) so it works for
    both FH5 and FH6 without needing an exact title string.
    """
    try:
        title = _get_foreground_window_title().lower()
        if not title:
            return False
        return "forza" in title
    except Exception:
        return False


def wait_for_fh6_focus(stop_event=None, check_interval=0.15):
    """Block until FH6 is the foreground window or stop requested.

    Args:
        stop_event: optional threading.Event — set() to request stop.
        check_interval: sleep time between checks (seconds).

    Returns:
        True if focus acquired, False if stop requested first.
    """
    import time

    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        if is_fh6_focused():
            return True
        if stop_event is not None:
            stop_event.wait(check_interval)
        else:
            time.sleep(check_interval)
