# FH5 Sniper → FH6 Sniper Migration Plan

## Context

This codebase is a Forza Horizon 5 auction house sniper. It detects in-game UI buttons via
OpenCV template matching and automates car purchases. FH6 is now out with a refreshed UI, so
the image templates need replacing and all FH5 branding/window-title references need updating.

The core logic (scan loop, key presses, detection flow, calibration system) is fully reusable.
Only assets and FH5-specific strings need to change.

---

## 1. Files to DELETE (build artifacts / stale)

Remove entirely — these will be regenerated when the project is rebuilt:

- `build/` — PyInstaller build artifacts
- `dist/` — compiled `.exe` files (including `dist/config.json`)
- Any `*.spec` file in root (e.g. `FH5 Sniper.spec`)

---

## 2. Image Templates to REPLACE (9 files)

All 9 PNGs in `assets/` are FH5 UI screenshots and must be replaced with FH6 captures.
**Keep the exact same filenames** — the code references them by name.

### How to capture

Run FH6 in windowed mode. Open the Auction House, find a car listing.

| File | What to screenshot |
|---|---|
| `assets/auction_options_template.png` | "Auction Options" button, full-size window (~1920×1080) |
| `assets/auction_options_template_med.png` | Same button, ~70% window size |
| `assets/auction_options_template_small.png` | Same button, ~40% window size |
| `assets/buyout_successful_template.png` | Purchase success confirmation screen, full-size |
| `assets/buyout_successful_template_med.png` | Same, ~70% size |
| `assets/buyout_successful_template_small.png` | Same, ~40% size |
| `assets/buyout_failed_template.png` | Purchase failure / outbid screen, full-size |
| `assets/buyout_failed_template_med.png` | Same, ~70% size |
| `assets/buyout_failed_template_small.png` | Same, ~40% size |

### Test fixture images (used by pytest)

Also replace these two in `tests/`:

| File | What to screenshot |
|---|---|
| `tests/auction_present.png` | FH6 screen with "Auction Options" button visible |
| `tests/auction_absent.png` | FH6 screen with no car selected (button absent) |

> **Tip:** The calibrator in the app can help verify templates after capture.
> Use "Auto Calibration" to confirm a template matches correctly.

---

## 3. Code Changes Required

### window_utils.py — most critical file

| What | Change |
|---|---|
| Line 58 — window title | `"Forza Horizon 5"` → `"Forza Horizon 6"` |
| Line ~35 — APPDATA dir | `FH5Sniper` → `FH6Sniper` |
| `get_fh5_window()` | Rename → `get_fh6_window()` |
| `is_fh5_focused()` | Rename → `is_fh6_focused()` |
| `wait_for_fh5_focus()` | Rename → `wait_for_fh6_focus()` |

> Note: `is_fh5_focused()` checks for the substring `"forza"` (case-insensitive), so it
> already works for FH6 — this is just a rename.

### app.py — branding & callers

- GUI window title: `"FH5 Sniper"` → `"FH6 Sniper"`
- Update all calls to the three renamed `window_utils` functions
- GitHub repo URL strings: update `FH5-Sniper/fh5_sniper` references
- All user-facing instruction text: `"Forza Horizon 5"` / `"FH5"` → `"FH6"`
- Recalibration modal popup text mentioning FH5
- 5-second countdown message: "Please focus Forza Horizon 5 now" → FH6

### sniper.py — callers & log messages

- Update calls to renamed `window_utils` functions
- Log and comment strings mentioning "FH5" or "Forza Horizon 5"

### calibrator.py — callers & user text

- Update calls to renamed `window_utils` functions
- Any user-facing strings mentioning "FH5"
- Button dimension constants (`w=365, h=75` at line ~221) — review after FH6 templates
  are captured; adjust if the button size differs

### README.md

- Title and all "FH5 Sniper" / "Forza Horizon 5" occurrences → FH6
- PyInstaller build command: `--name "FH5 Sniper"` → `"FH6 Sniper"`

### Tests

- `tests/test_window_utils.py` — update function name references
- `tests/test_sniper.py` — update function name references

---

## 4. Files That Need NO Changes

| File | Reason |
|---|---|
| `vision_utils.py` | Pure OpenCV logic, zero game-specific references |
| `settings.py` | Config management, no game-specific strings |
| `logger.py` | Logging utility, no game references |
| `mcp_server/server.py` | Code introspection tool, no game references |
| `requirements.txt` | Dependencies are unchanged |
| `.gitignore` | Fine as-is |

---

## 5. Execution Order

1. **Clean** — delete `build/`, `dist/`, any `*.spec` files
2. **Rename functions** in `window_utils.py`, update all callers in `app.py`, `sniper.py`, `calibrator.py`
3. **Update strings** — all "FH5" / "Forza Horizon 5" occurrences in code and README
4. **Update config path** — `FH5Sniper` → `FH6Sniper` in `window_utils.py`
5. **Capture new templates** — take FH6 screenshots, save into `assets/` and `tests/` with the exact same filenames as listed above
6. **Run calibration** — launch the app, use Auto Calibration to verify templates work against FH6
7. **Adjust button constants** in `calibrator.py` if FH6 button dimensions differ from FH5
8. **Run tests** — `pytest -q` (tests will fail until new test fixture images are in `tests/`)
9. **Rebuild exe** — `pyinstaller --onefile --windowed --name "FH6 Sniper" app.py`

---

## 6. Verification Checklist

- [ ] `pytest -q` passes after new test fixtures are added
- [ ] `python app.py` — window title shows "FH6 Sniper"
- [ ] Auto Calibration detects the "Auction Options" button in FH6
- [ ] Sniper starts, finds the FH6 window, no "FH5 not focused" errors
- [ ] Config is saved to `%APPDATA%\FH6Sniper\config.json` (not `FH5Sniper`)
- [ ] Successful buy registers as a win; failed buy registers as a loss
