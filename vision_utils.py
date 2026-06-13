"""Vision utilities with multi-scale template matching.

This module provides a drop-in replacement for PyAutoGUI's
`locateOnScreen` that can handle scaled templates. Templates are assumed to be
captured at full screen resolution; when the game runs at a lower resolution or
in a window, the template is scaled down during matching.

The core function `locate_on_screen_scaled` mimics the PyAutoGUI API but uses
OpenCV internals for performance and scale awareness.
"""

from __future__ import annotations

import json
import os
import time

import cv2
import numpy as np
import pyautogui
from PIL import Image

import window_utils

CONFIG_FILE = window_utils.get_config_file()

# simple in-memory cache for loaded templates to avoid disk I/O
_template_cache = {}

# dxcam camera instance — reused across calls (DXGI Desktop Duplication)
_dxcam_instance = None


def _get_dxcam():
    global _dxcam_instance
    if _dxcam_instance is None:
        import dxcam

        _dxcam_instance = dxcam.create(output_color="RGB")
    return _dxcam_instance


def grab_full_screen() -> Image | None:
    """Capture the entire primary display using DXGI Desktop Duplication.

    A single full-screen grab produces one complete GPU frame so all callers
    (row brightness checks, badge matching) work from identical pixel data.
    Per-region grabs each hit the DXGI pipeline independently and can land on
    different frames; a shared capture fails consistently rather than silently
    producing mixed-row results.

    Known limitation — "lost chance" on bad frame:
        FH6 uses DirectX 12 flip-model presentation with hardware overlay planes.
        DXGI Desktop Duplication occasionally returns the raw 3D scene instead of
        the auction UI overlay (~1 in 74 scans observed).  When this happens all
        rows appear dark and the scan is skipped entirely — a lost opportunity but
        never a false buy.  The brightness check catches bad frames before the
        badge check runs, so a false "available" is not possible from this path.

        The proper fix is Windows Graphics Capture (WGC) via the `windows-capture`
        package (same API as Xbox Game Bar / OBS Game Capture), which correctly
        captures hardware overlay planes.  Not implemented; the trade-off was
        accepted as good enough for now.

    Returns a PIL RGB Image, or None on complete failure.
    """
    try:
        cam = _get_dxcam()
        for _ in range(5):
            frame = cam.grab()  # no region arg → full screen
            if frame is not None:
                return Image.fromarray(frame)
            time.sleep(0.016)
    except Exception:
        pass
    try:
        return pyautogui.screenshot()
    except Exception:
        return None


def grab_region(region: tuple[int, int, int, int]):
    """Screenshot a screen region using DXGI Desktop Duplication (dxcam).

    dxcam reads directly from the GPU output via IDXGIOutputDuplication,
    capturing the final composited frame that is actually sent to the display.
    pyautogui and mss use GDI BitBlt which can miss DirectX overlay frames,
    returning raw 3D background instead of the UI.

    When dxcam returns None (no new GPU frame since last call), we retry a few
    times with a short sleep rather than falling back immediately to pyautogui —
    the fallback GDI path is the one that returns stale/wrong frames for DX12
    games running in flip-model presentation.

    Returns a PIL-compatible Image (RGB).  Falls back to pyautogui only if
    dxcam fails entirely (e.g. device lost or unrecoverable error).

    Args:
        region: (left, top, width, height) in physical screen pixels.
    """
    left, top, width, height = region
    try:
        cam = _get_dxcam()
        dxcam_region = (left, top, left + width, top + height)
        # Retry up to 5 times (~80 ms total) waiting for a fresh GPU frame.
        # dxcam returns None when the display hasn't produced a new frame yet;
        # sleeping one display-refresh interval (16 ms) is usually enough.
        for _ in range(5):
            frame = cam.grab(region=dxcam_region)
            if frame is not None:
                return Image.fromarray(frame)
            time.sleep(0.016)
    except Exception:
        pass
    return pyautogui.screenshot(region=region)


# remember the last successful scale for each template path; helps narrow
# future searches when the window size is stable.
_last_scale_hint = {}


# thresholds for distinguishing window sizes relative to the screen.
# if either dimension is below SMALL -> use small template
# if between SMALL and MED -> medium template (if available)
# otherwise use full template.  these numbers were chosen based on the
# behaviour users reported when resizing the FH6 window.
SMALL_PERCENT_WIDTH = 0.50  # 50% of screen width
SMALL_PERCENT_HEIGHT = 0.50  # 50% of screen height
MED_PERCENT_WIDTH = 0.80  # up to 80% of screen width is considered medium
MED_PERCENT_HEIGHT = 0.80  # up to 80% of screen height is considered medium

# Absolute pixel thresholds for detecting a 1024x768 game window.
# Using the actual FH6 window size (not the search region) avoids false
# positives when a small button region is passed to choose_template().
SMALL_ABS_WIDTH = 1150  # FH6 window narrower than this → use _1024x768 template
SMALL_ABS_HEIGHT = 870  # FH6 window shorter than this → use _1024x768 template


def choose_template(
    base_path: str, region: tuple[int, int, int, int] | None = None, debug: bool = False
):
    """Return appropriate template path depending on region size relative to screen.

    Args:
        base_path: path to the fullscreen template (e.g. "auction_options_template.png").
        region: optional region tuple whose dimensions are used instead of the
                actual window. If None, tries to query the FH6 window.
        debug: whether to emit informational prints.

    Returns:
        (path, category) tuple where category is "full", "medium", or "small".
    """
    # get screen dimensions for relative comparison
    screen_w, screen_h = pyautogui.size()
    if debug:
        print(f"screen size: {screen_w}x{screen_h}")

    # Always look up the live FH6 window for the absolute-size check.
    # The search region passed via `region` is typically just the button area
    # (~300×100 px), which would always look "small" — using the actual game
    # window prevents false positives.
    fh6_win = window_utils.get_fh6_window()
    fh6_w = fh6_win.width if fh6_win else 0
    fh6_h = fh6_win.height if fh6_win else 0

    # determine window/region dimensions for the percentage-based check
    w = h = 0
    if region:
        _, _, w, h = region
    elif fh6_win:
        w, h = fh6_w, fh6_h

    small_tpl = base_path.replace(".png", "_1024x768.png")

    # Absolute-pixel check first: covers 1024×768 whether windowed on a large
    # monitor or fullscreen on a native 1024×768 display.
    category = "full"
    if fh6_w and fh6_h and fh6_w <= SMALL_ABS_WIDTH and fh6_h <= SMALL_ABS_HEIGHT and os.path.isfile(small_tpl):
        category = "small"
    elif w and h:
        w_percent = w / screen_w
        h_percent = h / screen_h
        if debug:
            print(f"window size: {w}x{h} ({w_percent * 100:.1f}% x {h_percent * 100:.1f}%)")
        if w_percent < MED_PERCENT_WIDTH or h_percent < MED_PERCENT_HEIGHT:
            category = "medium"

    if category == "small":
        chosen = small_tpl
    elif category == "medium":
        candidate = base_path.replace(".png", "_med.png")
        chosen = candidate if os.path.isfile(candidate) else base_path
    else:
        chosen = base_path

    if debug:
        print(f"template selection: chose {category} -> {chosen}")
    return chosen, category


def save_manual_template_match(template_path, scale, confidence):
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)

        data["MANUAL_TEMPLATE_INFO"] = {
            "template_path": template_path,
            "scale": scale,
            "confidence": confidence,
        }

        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

        print("✅ Updated MANUAL_TEMPLATE_INFO in config.json")

    except Exception as e:
        print(f"⚠️ Failed writing config: {e}")


def _load_template(image_path: str, debug: bool = False):
    """Load template as a numpy array (BGR) and cache the result.

    Args:
        image_path: path to template
        debug: whether to print loading message
    """
    if image_path in _template_cache:
        if debug:
            print(f"Template '{image_path}' retrieved from cache")
        return _template_cache[image_path]

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Template not found: {image_path}")

    # read in color by default; convert to gray later
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Failed to load image: {image_path}")

    _template_cache[image_path] = img
    if debug:
        print(f"Loaded template '{image_path}' (cached)")
    return img


def locate_on_screen_with_variants(
    base_path: str,
    region=None,
    confidence: float = 0.8,
    grayscale: bool = True,
    scale_min: float = 0.4,
    scale_max: float = 1.0,
    scale_steps: int = 18,
    debug: bool = False,
    scale_hint: float | None = None,
    hint_margin: float = 0.10,
    test: bool = False,
) -> tuple[int, int, int, int] | None:
    """Attempt to locate a template and its size variants.

    The method first calls :func:`choose_template` to pick a primary file path
    (medium/full).  If no match is found using that template, additional
    candidates are tried in this order:
    1. medium variant (``*_med.png``) if it exists
    2. full-size base template

    This makes the detection resilient when the window-size heuristic
    misclassifies the current scaling.
    """
    # determine primary candidate and category (debug flag matters)
    template, category = choose_template(base_path, region=region, debug=debug)
    candidates = [template]

    # helper to add file if exists and not already present
    def maybe_add(path):
        if path not in candidates and os.path.isfile(path):
            candidates.append(path)

    # medium variant
    med = base_path.replace(".png", "_med.png")
    maybe_add(med)
    # full base template
    maybe_add(base_path)
    # 1024x768 variant — last resort so larger-window templates are tried first
    small = base_path.replace(".png", "_1024x768.png")
    maybe_add(small)

    if debug:
        print(f"searching variants: {candidates}")

    for tpl in candidates:
        if tpl == template:
            # inherit the provided scale_hint for the primary candidate
            hint = scale_hint
        else:
            hint = None
        loc = locate_on_screen_scaled(
            tpl,
            region=region,
            confidence=confidence,
            grayscale=grayscale,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_steps=scale_steps,
            debug=debug,
            scale_hint=hint,
            hint_margin=hint_margin,
            test=test,
        )
        if loc is not None:
            return loc
    return None


def locate_on_screen_scaled(
    image_path: str,
    region=None,
    confidence: float = 0.8,
    grayscale: bool = True,
    scale_min: float = 0.4,
    scale_max: float = 1.0,
    scale_steps: int = 18,
    debug: bool = False,
    scale_hint: float | None = None,
    hint_margin: float = 0.10,
    test: bool = False,
) -> tuple[int, int, int, int] | None:
    """Search the screen or region for a template at multiple scales.

    Args:
        image_path: Path to the single template image (assumed fullscreen).
        region: Optional (left, top, width, height) to limit search.
        confidence: Matching threshold (0-1); same semantics as PyAutoGUI.
        grayscale: Whether to convert images to grayscale for matching.
        scale_min: Minimum scale factor (relative to original template).
        scale_max: Maximum scale factor. Should normally be 1.0.
        scale_steps: Number of intermediate scales to try.
        debug: Print detailed information about each scale.

    Returns:
        A 4-tuple (left, top, width, height) in screen coordinates if found,
        otherwise `None`.
    """
    # take screenshot of region or full screen
    try:
        if region:
            left, top, w, h = region
            screenshot = grab_region(region)
        else:
            left, top = 0, 0
            screenshot = pyautogui.screenshot()
    except Exception as e:
        print(f"⚠️  Error taking screenshot: {e}")
        return None

    # convert screenshot to numpy BGR array
    screen_img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    if grayscale:
        screen_proc = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
    else:
        screen_proc = screen_img

    template_color = _load_template(image_path, debug=debug)

    if grayscale:
        template_proc = cv2.cvtColor(template_color, cv2.COLOR_BGR2GRAY)
    else:
        template_proc = template_color

    screen_h, screen_w = screen_proc.shape[:2]

    # decide which scales to try first
    scales_to_try = None
    # accept an explicit hint or fall back to cached hint
    if scale_hint is None:
        scale_hint = _last_scale_hint.get(image_path)
    if scale_hint is not None:
        # compute a tight window around the hint
        low = max(scale_min, scale_hint * (1.0 - hint_margin))
        high = min(scale_max, scale_hint * (1.0 + hint_margin))
        scales_to_try = np.linspace(high, low, scale_steps)
    else:
        scales_to_try = np.linspace(scale_max, scale_min, scale_steps)

    # iterate over candidate scales
    for scale in scales_to_try:
        # compute resized template size
        t_h = int(template_proc.shape[0] * scale)
        t_w = int(template_proc.shape[1] * scale)

        # skip impossible scales
        if t_h <= 0 or t_w <= 0 or t_h > screen_h or t_w > screen_w:
            continue

        resized = cv2.resize(template_proc, (t_w, t_h), interpolation=cv2.INTER_AREA)

        # do the matching
        try:
            result = cv2.matchTemplate(screen_proc, resized, cv2.TM_CCOEFF_NORMED)
        except Exception as e:
            print(f"⚠️  Error during matchTemplate at scale {scale}: {e}")
            continue

        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if debug:
            print(f"scale={scale:.3f} max_val={max_val:.3f}")

        if max_val >= confidence:
            # remember this scale for next time
            _last_scale_hint[image_path] = scale
            # match found - compute screen coords

            if test:
                save_manual_template_match(image_path, scale, confidence)

            match_left = left + max_loc[0]
            match_top = top + max_loc[1]
            # width/height should be size of resized template

            return (match_left, match_top, t_w, t_h)

    # if we tried a hinted window and failed, fall back to full range once
    if scale_hint is not None and scales_to_try is not None:
        # check if the hint-limited search covered entire interval; if not,
        # run once over the full range.
        full_range = np.linspace(scale_max, scale_min, scale_steps)
        if not np.array_equal(full_range, scales_to_try):
            for scale in full_range:
                t_h = int(template_proc.shape[0] * scale)
                t_w = int(template_proc.shape[1] * scale)
                if t_h <= 0 or t_w <= 0 or t_h > screen_h or t_w > screen_w:
                    continue
                resized = cv2.resize(template_proc, (t_w, t_h), interpolation=cv2.INTER_AREA)
                try:
                    result = cv2.matchTemplate(screen_proc, resized, cv2.TM_CCOEFF_NORMED)
                except Exception:
                    continue
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if debug:
                    print(f"scale={scale:.3f} max_val={max_val:.3f}")
                if max_val >= confidence:
                    _last_scale_hint[image_path] = scale
                    match_left = left + max_loc[0]
                    match_top = top + max_loc[1]
                    return (match_left, match_top, t_w, t_h)
    # no match found
    if debug:
        print(f"no match for '{image_path}' (confidence {confidence})")
    return None


# ── Sold-car detection ────────────────────────────────────────────────────────


def row_has_car(region: tuple[int, int, int, int], dark_threshold: int = 150, row_img=None) -> bool:
    """Return True if the row region contains a car card (not an empty dark slot).

    Empty auction slots are semi-transparent black placeholders; their mean
    pixel brightness is well below available or sold car rows.

    Args:
        region: (x, y, w, h) in screen coords to screenshot.
        dark_threshold: mean grayscale value below which we call the row empty.
        row_img: optional pre-captured PIL Image to use instead of screenshotting.
    """
    try:
        screenshot = row_img if row_img is not None else grab_region(region)
        gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        return float(np.mean(gray)) > dark_threshold
    except Exception as e:
        print(f"⚠️  row_has_car error: {e}")
        return True  # fail-safe: assume car present so we don't skip real ones


def detect_sold(
    row_region: tuple[int, int, int, int],
    badge_params: dict,
    template_path: str,
    confidence: float = 0.73,
) -> bool:
    """Return True if the "Sold!" badge is detected in the row's badge sub-region.

    Tries the _med variant as a fallback when it exists alongside
    the base template — same pattern as the auction button templates.

    Args:
        row_region: (x, y, w, h) of the full row card in screen coords.
        badge_params: dict loaded from docs/sold_badge_region.json with
                      badge_x_pct, badge_y_pct, badge_w_pct, badge_h_pct keys.
        template_path: absolute path to sold_badge_template.png.
        confidence: template-match threshold (0–1).
    """
    rx, ry, rw, rh = row_region
    bx = rx + int(rw * badge_params["badge_x_pct"])
    by = ry + int(rh * badge_params["badge_y_pct"])
    bw = max(1, int(rw * badge_params["badge_w_pct"]))
    bh = max(1, int(rh * badge_params["badge_h_pct"]))
    scan = (bx, by, bw, bh)

    # Pick primary variant based on row width vs screen width (row ≈ 30 % of window)
    screen_w = pyautogui.size()[0]
    rw_pct = rw / screen_w if screen_w else 1.0
    if rw_pct < MED_PERCENT_WIDTH * 0.30:
        primary = template_path.replace(".png", "_med.png")
    else:
        primary = template_path

    # Build candidate list: preferred size first, then full as fallback
    candidates: list[str] = []
    for p in [
        primary,
        template_path.replace(".png", "_med.png"),
        template_path,
        template_path.replace(".png", "_1024x768.png"),
    ]:
        if p not in candidates and os.path.isfile(p):
            candidates.append(p)

    for tpl in candidates:
        loc = locate_on_screen_scaled(
            tpl,
            region=scan,
            confidence=confidence,
            grayscale=False,
            scale_min=0.1,  # wider range → handles small windows even with one template
            scale_max=1.2,
            scale_steps=24,
        )
        if loc is not None:
            return True
    return False


def sold_badge_score(
    row_region: tuple[int, int, int, int],
    badge_params: dict,
    template_path: str,
    row_img=None,
) -> float:
    """Return the best raw template-match confidence for the sold badge (0–1).

    Same region and candidate logic as detect_sold() but returns the peak score
    across all variants and scales without applying a threshold. Useful for
    tuning the confidence value in test_detection.py.

    Args:
        row_img: optional pre-captured PIL Image of the full row. When provided
                 the badge sub-region is cropped from it instead of taking a
                 second screenshot — avoids frame-timing issues where a second
                 grab_region call returns a different (stale) frame.
    """
    rx, ry, rw, rh = row_region
    bx = rx + int(rw * badge_params["badge_x_pct"])
    by = ry + int(rh * badge_params["badge_y_pct"])
    bw = max(1, int(rw * badge_params["badge_w_pct"]))
    bh = max(1, int(rh * badge_params["badge_h_pct"]))

    screen_w = pyautogui.size()[0]
    rw_pct = rw / screen_w if screen_w else 1.0
    if rw_pct < MED_PERCENT_WIDTH * 0.30:
        primary = template_path.replace(".png", "_med.png")
    else:
        primary = template_path

    candidates: list[str] = []
    for p in [
        primary,
        template_path.replace(".png", "_med.png"),
        template_path,
        template_path.replace(".png", "_1024x768.png"),
    ]:
        if p not in candidates and os.path.isfile(p):
            candidates.append(p)

    try:
        if row_img is not None:
            badge_pil = row_img.crop((bx - rx, by - ry, bx - rx + bw, by - ry + bh))
        else:
            badge_pil = grab_region((bx, by, bw, bh))
        screen_img = cv2.cvtColor(np.array(badge_pil), cv2.COLOR_RGB2BGR)
    except Exception:
        return 0.0

    best = 0.0
    sh, sw = screen_img.shape[:2]
    for tpl_path in candidates:
        try:
            tpl = _load_template(tpl_path)
            for scale in np.linspace(1.2, 0.1, 24):
                th = int(tpl.shape[0] * scale)
                tw = int(tpl.shape[1] * scale)
                if th <= 0 or tw <= 0 or th > sh or tw > sw:
                    continue
                resized = cv2.resize(tpl, (tw, th), interpolation=cv2.INTER_AREA)
                result = cv2.matchTemplate(screen_img, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                if max_val > best:
                    best = float(max_val)
        except Exception:
            continue
    return best
