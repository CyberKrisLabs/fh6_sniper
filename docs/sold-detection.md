# Sold Car Detection — FH6 Auction House

## Background / Problem

In **FH5**, a sold car disappeared from the auction list immediately. The sniper could rely on
the Auction Options button being visible as a proxy for "there is a buyable car right now."

In **FH6**, sold cars remain visible in the auction list for roughly **30–60 seconds** after
being purchased. During this window the row is still displayed — and the Auction Options button
is still visible — but the car is already gone.

**Detecting the Auction Options button alone is no longer sufficient.**

---

## Auction List Layout

- The visible list shows **4 rows** (cars) at a time.
- Pressing **arrow down** scrolls to the next row; after 4 presses a 5th car becomes visible.

### Row states

| State | Visual |
|---|---|
| **Available car** | Full card, white/coloured background, Auction Options button visible |
| **Sold car** | Same card + small **"Sold!" badge** (yellow bg, black text, plate-style) in the top-left of the card |
| **Empty slot** | Semi-transparent black placeholder — no card content |

---

## Row Region Formula

Row positions are **calculated from window dimensions** — no per-session calibration needed.

### Constants (measured at reference window 3558×2045 physical)

| Constant | Value | Meaning |
|---|---|---|
| `ROW_X_PCT` | `0.041` | Left edge of cards ≈ 4.1 % of window width |
| `ROW_Y_START_PCT` | `0.1095` | Top of row 1 ≈ 10.95 % of window height |
| `ROW_HEIGHT_PCT` | `0.1163` | Card height ≈ 11.63 % of window height |
| `ROW_WIDTH_PCT` | `0.2999` | Card width ≈ 30 % of window width |
| `ROW_GAP_PCT` | `0.0049` | Gap between cards ≈ 0.49 % of window height |

### ⚠ Critical DPR note — physical vs logical coordinates

`window_utils.get_row_regions()` and `get_tuned_row_regions()` must apply the **display device
pixel ratio (DPR)** when converting row percentages to pyautogui coordinates.

**Why this matters:**

| Tool | Coordinate space |
|---|---|
| `pygetwindow` (`win.left`, `win.top`, `win.width`, `win.height`) | Physical pixels |
| `pyautogui.screenshot(region=…)` | Physical pixels |
| `tune_rows.py` / `row_regions_tuned.json` percentages | Qt **logical** pixels |

On a 150 % DPI screen (DPR = 1.5, physical 3840×2160, logical 2560×1440), applying
row percentages directly to `win.width` / `win.height` (physical) gives rows that are
**1.5× too small at the wrong position** — the screenshots land on the wrong part of the
screen and template matching fails.

**The correct formula** (mirrors `tools/test_detection.py`):

```python
dpr = _get_display_dpr()   # from window_utils; uses GetDpiForMonitor
wx, wy, ww, wh = win.left, win.top, win.width, win.height  # physical

# Compute in Qt logical space, then scale to physical
x_log  = int(wx / dpr + (ww / dpr) * ROW_X_PCT)
w_log  = int(ww * ROW_WIDTH_PCT)
h_log  = int(wh * ROW_HEIGHT_PCT)
y0_log = wy + int(wh * ROW_Y_START_PCT)
step   = int(wh * ROW_STEP_PCT)

rows = [
    (int(x_log * dpr), int((y0_log + i * step) * dpr), int(w_log * dpr), int(h_log * dpr))
    for i in range(num_rows)
]
```

`_get_display_dpr()` uses `shcore.GetDpiForMonitor` (returns real DPI regardless of process
DPI-awareness) with a Qt `QApplication.primaryScreen().devicePixelRatio()` fallback.
**Do NOT use `GetDeviceCaps(LOGPIXELSX)`** — it returns 96 on DPI-aware processes.

Per-row tuning (`docs/row_regions_tuned.json`) applies the same DPR correction in
`get_tuned_row_regions()`.

---

## Per-Row Scan Logic

For each visible row (top to bottom), `sniper.find_available_row()`:

1. **Is a car present?** — `row_has_car(region)`: mean brightness of row screenshot
   below threshold → empty placeholder → stop scanning.
2. **Is the car sold?** — `sold_badge_score(row_region, badge_params, template_path)`:
   yellow-color gate → Windows OCR (reads "SOLD", returns 1.0) → multi-scale template
   match fallback. Score ≥ `vision_utils.SOLD_THRESHOLD` (0.68) → sold.
3. **Available rows** are collected; by default the sniper buys the **last**
   available row (less competition than row 1), navigating down to it with
   arrow keys. The "Buy last available row" setting can switch this to the
   first available row for a slightly faster (but more contested) attempt.

If every visible row is sold (or row 1 never rendered), the sniper runs a full
`reset_search()` — Esc → Enter → Enter — to reload the auction list. There is no
scrolling past row 4.

---

## Sold Badge Detection

### Template

`assets/sold_badge_template.png` (+ `_med`, `_1024x768` variants) — cleaned captures of
the yellow "SOLD!" badge with the car background removed. Committed to the repo; no
in-app capture needed. (A pixel-captured per-user template was tried and removed: the
tilted badge's bounding box inevitably bakes the calibration car's paintwork in as noise,
while the cleaned templates' flat background is effectively self-masking under
TM_CCOEFF_NORMED.)

To regenerate variants if the template is replaced:
```python
from PIL import Image
img = Image.open("assets/sold_badge_template.png")
w, h = img.size
img.resize((int(w * 0.60), int(h * 0.60)), Image.LANCZOS).save("assets/sold_badge_template_med.png")
img.resize((int(w * 0.36), int(h * 0.36)), Image.LANCZOS).save("assets/sold_badge_template_1024x768.png")
```

### Badge position (`docs/sold_badge_region.json`)

Calibrated by `tools/measure_sold_region.py`. Stores where within the row card to scan for
the badge as fractions of the row's physical dimensions.

**⚠ Coordinate space caveat with `measure_sold_region.py`:**

The overlay tool draws in Qt logical pixels but the row dimensions it receives from
`pygetwindow` are physical. This means the badge offset values (`badge_dx_px`,
`badge_dy_px`) are in logical pixels while `row_ref_px` dimensions are physical — a mixed
unit. `sold_badge_score()` currently applies the percentages directly (no DPR correction) because
`get_row_regions()` now returns correct physical rows, and the percentage round-trip
(logical_offset / physical_dim × physical_dim) happens to give approximately the right
physical position for the badge.

If detection confidence drops after re-running `measure_sold_region.py` on a DPR ≠ 1 system,
recheck this arithmetic. The clean fix would be to have `measure_sold_region.py` save badge
offsets in physical pixels (multiply arrow-key steps by DPR before saving).

### Confidence threshold

`vision_utils.SOLD_THRESHOLD` = **0.68** (single authoritative constant — sniper.py
re-exports it; calibration and the tuning tools import it). Score below the threshold →
badge not detected, row treated as available. A Windows-OCR "SOLD" read scores an
exact 1.0.

If confidence is consistently low (< 0.6), the likely causes are:
1. Wrong row coordinates (DPR not applied — see above)
2. Template captured from wrong area (check `assets/sold_badge_template.png`)
3. FH6 UI update changed the badge appearance → recapture template from the game

---

## Files Involved

| File | Role |
|---|---|
| `window_utils.py` | `get_row_regions()`, `get_tuned_row_regions()`, `_get_display_dpr()` |
| `vision_utils.py` | `row_has_car()`, `sold_badge_score()`, `SOLD_THRESHOLD` |
| `sniper.py` | `find_available_row()` — iterates rows, calls both detectors |
| `assets/sold_badge_template*.png` | Badge templates (committed, real game captures) |
| `docs/sold_badge_region.json` | Badge scan sub-region percentages within a row |
| `docs/row_regions_tuned.json` | Per-row tuning overrides (written by `tune_rows.py`) |
| `tools/test_detection.py` | Live detection test UI — reference implementation of correct DPR-aware row calculation |
| `tools/measure_sold_region.py` | Interactive badge-position calibration tool |
| `tools/tune_rows.py` | Interactive row-position tuning tool |
