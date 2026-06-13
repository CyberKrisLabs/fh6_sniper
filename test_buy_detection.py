"""Diagnostic tool: capture the screen after a buy attempt and analyse what the sniper sees.

Usage
-----
1. In FH6, trigger a buy so the result screen (success or failure) is visible.
2. Switch to this terminal window and run:
       python test_buy_detection.py
3. You have 5 seconds to switch back to FH6 before the capture fires.
4. The script saves a timestamped PNG to docs/ and prints the best match score
   for every template variant so you can see exactly why detection went wrong.

The saved PNG has coloured rectangles drawn on it:
  - Green  = match above confidence threshold  (would be reported as FOUND)
  - Yellow = best match below threshold        (too weak to trigger)
  - Red    = template tried but no result (e.g. size mismatch)
"""

import os
import subprocess
import sys
import time
from datetime import datetime

import cv2
import numpy as np
import pyautogui

# Make sure project root is on the path when run from any directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vision_utils
import window_utils

CONFIDENCE = 0.72  # same default used in buy_sequence for full-size windows
SCALE_MIN = 0.35
SCALE_MAX = 1.0
SCALE_STEPS = 30  # more steps for thorough diagnosis
COUNTDOWN = 5

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")


def _load_gray(path: str):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def best_match_score(screen_gray, template_gray, scale_min, scale_max, scale_steps):
    """Return (best_score, best_scale, best_loc_xy) across all scales."""
    sh, sw = screen_gray.shape[:2]
    th, tw = template_gray.shape[:2]

    best_score = -1.0
    best_scale = None
    best_loc = None

    for scale in np.linspace(scale_max, scale_min, scale_steps):
        rh = int(th * scale)
        rw = int(tw * scale)
        if rh <= 0 or rw <= 0 or rh > sh or rw > sw:
            continue
        resized = cv2.resize(template_gray, (rw, rh), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = max_val
            best_scale = scale
            best_loc = (max_loc[0], max_loc[1], rw, rh)

    return best_score, best_scale, best_loc


def analyse(screen_bgr, label, template_paths, confidence, scale_min, scale_max, scale_steps):
    """Run matching for a list of template paths and return results + annotated image."""
    screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
    annotated = screen_bgr.copy()

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    overall_found = False

    for tpl_path in template_paths:
        name = os.path.basename(tpl_path)
        if not os.path.isfile(tpl_path):
            print(f"  [SKIP] {name} — file not found")
            continue

        try:
            tpl_gray = _load_gray(tpl_path)
        except Exception as e:
            print(f"  [ERROR] {name} — {e}")
            continue

        score, scale, loc = best_match_score(
            screen_gray, tpl_gray, scale_min, scale_max, scale_steps
        )

        found = score >= confidence
        if found:
            overall_found = True

        status = "✅ FOUND" if found else ("⚠️  weak" if score >= confidence * 0.85 else "❌ miss")
        print(
            f"  {status}  {name:<45}  score={score:.4f}  scale={scale:.3f}  threshold={confidence}"
        )

        if loc is not None:
            x, y, w, h = loc
            color = (0, 200, 0) if found else (0, 200, 255)  # green or yellow
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
            tag = f"{name[:20]} {score:.3f}"
            cv2.putText(
                annotated,
                tag,
                (x, max(y - 5, 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )

    return overall_found, annotated


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("FH6 Buy Detection Diagnostic")
    print("-----------------------------")
    print(f"Switch to FH6 now. Capturing in {COUNTDOWN} seconds...\n")

    for i in range(COUNTDOWN, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    print("  Capturing full screen...")
    screen_pil = vision_utils.grab_full_screen()
    if screen_pil is None:
        screen_pil = pyautogui.screenshot()

    screen_bgr = cv2.cvtColor(np.array(screen_pil), cv2.COLOR_RGB2BGR)
    print(f"  Screen size: {screen_bgr.shape[1]}x{screen_bgr.shape[0]} px")

    # Determine full_region from the FH6 window (same logic as sniper_loop)
    win = window_utils.get_fh6_window()
    if win:
        full_region = window_utils.get_window_region(win)
        rx, ry, rw, rh = full_region
        print(f"  FH6 window region: x={rx} y={ry} w={rw} h={rh}")
        # Crop screen to the FH6 window region for matching (same as sniper)
        screen_bgr = screen_bgr[ry : ry + rh, rx : rx + rw]
        print(f"  Cropped to window: {screen_bgr.shape[1]}x{screen_bgr.shape[0]} px")
    else:
        print("  ⚠️  FH6 window not found — analysing full screen")
        full_region = None

    # Determine which template size category applies (same as choose_template)
    base_succ = window_utils.resource_path("assets/buyout_successful_template.png")
    base_fail = window_utils.resource_path("assets/buyout_failed_template.png")

    _, cat = vision_utils.choose_template(base_succ, region=full_region, debug=False)
    print(f"\n  Template category chosen by size heuristic: '{cat}'")

    # Adjust thresholds to match buy_sequence logic
    if cat == "small":
        conf = 0.65
        scale_min = 0.7
    elif cat == "medium":
        conf = 0.70
        scale_min = 0.5
    else:
        conf = 0.72
        scale_min = 0.35

    print(f"  Matching params: confidence={conf}  scale_min={scale_min}  scale_max={SCALE_MAX}")

    succ_templates = [
        base_succ,
        base_succ.replace(".png", "_med.png"),
    ]
    fail_templates = [
        base_fail,
        base_fail.replace(".png", "_med.png"),
    ]

    found_succ, annotated = analyse(
        screen_bgr, "SUCCESS templates", succ_templates, conf, scale_min, SCALE_MAX, SCALE_STEPS
    )
    found_fail, annotated = analyse(
        annotated, "FAIL templates", fail_templates, conf, scale_min, SCALE_MAX, SCALE_STEPS
    )

    print(f"\n{'='*60}")
    if found_succ:
        verdict = "✅ WOULD REPORT: Buy successful"
    elif found_fail:
        verdict = "❌ WOULD REPORT: Buy failed"
    else:
        verdict = "⚠️  WOULD REPORT: Undetermined (neither template matched)"
    print(f"  VERDICT: {verdict}")
    print(f"{'='*60}\n")

    # Save the raw capture and the annotated version
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(OUTPUT_DIR, f"buy_capture_{ts}_raw.png")
    ann_path = os.path.join(OUTPUT_DIR, f"buy_capture_{ts}_annotated.png")

    cv2.imwrite(raw_path, screen_bgr)
    cv2.imwrite(ann_path, annotated)

    print(f"  Raw screenshot  → {raw_path}")
    print(f"  Annotated image → {ann_path}")
    print()
    print("  Green box  = match above threshold (sniper counts this as FOUND)")
    print("  Yellow box = best match but below threshold (not counted)")
    print()

    # Open the annotated image so the user can inspect it immediately
    try:
        subprocess.Popen(["explorer", ann_path])
    except Exception:
        pass


if __name__ == "__main__":
    main()
