# FH6 Sniper — Claude Context

## Project

Windows automation tool that snipers cars in the Forza Horizon 6 auction house using OpenCV
template matching. Detects UI buttons via screenshot analysis and fires buy sequences via
keyboard automation.

**Platform:** Windows only (DPI scaling and foreground-window detection via ctypes/Win32).
**UI framework:** PySide6 (the ttkbootstrap → PySide6 migration is complete).

---

## Setup

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
pre-commit install
```

---

## Key Commands

| Task | Command |
|---|---|
| Run the app | `python app.py` |
| Lint | `ruff check .` |
| Format | `ruff format .` |
| Lint + auto-fix | `ruff check --fix . && ruff format .` |
| Type check | `mypy .` |
| Tests | `pytest -q` |
| Tests with coverage | `pytest -q --cov` |
| Run all pre-commit checks | `pre-commit run --all-files` |

---

## Before Pushing

1. `pre-commit run --all-files` — runs ruff check + format
2. `mypy .` — type check (fix any new errors you introduced)
3. `pytest -q` — all tests green

CI enforces the same checks on every push.

---

## Architecture

```
app.py            Thin PySide6 launcher (entry point; re-exports for tests)
ui/               PySide6 GUI package
  main_window.py    Main window and tab container
  tabs/             Sniper, Settings, Calibration, Info, Guides tabs
  overlays/         In-game HUD, calibration and region overlays
  log_bridge.py     Thread-safe log signal bridge to the GUI
  theme.py          Dark theme styling
sniper.py         Core scan loop — detects button, fires buy sequence, tracks stats
vision_utils.py   OpenCV engine — multi-scale template matching, screenshot capture
calibrator.py     Calibration helpers — auto and manual region detection
window_utils.py   FH6 window detection (pygetwindow), DPI scaling (ctypes), asset paths
settings.py       Config file load/save + DEFAULT_TIMINGS (APPDATA/FH6Sniper/config.json)
row_tuner.py      Interactive row-region tuning tool
```

## Assets

`assets/` holds 13 PNG templates across 4 families (auction options ×2 backgrounds,
buyout success/fail, sold badge), each with size variants (full / `_med` /
`_1024x768` where present). If you replace a full-size template, regenerate the
variants.

---

## Testing Philosophy

**TDD by layer:**

| Layer | Approach |
|---|---|
| PySide6 UI widgets | **TDD** — write pytest-qt tests first: signal fires on click, widget state after action, etc. |
| Settings / config logic | **TDD** — pure functions, no side effects, easy to test first |
| Vision math | **Fixture-based** — monkeypatch `pyautogui.screenshot` with known images from `tests/`; test detection result |
| Sniper loop / buy sequence | **Test-after with mocks** — mock `is_fh6_focused`, `pyautogui.press`, etc.; don't test real keystrokes |
| Window detection | **Skip** — requires FH6 running; not meaningful to mock the OS API |

**Coverage target:** aim for >80% on `settings.py`, `vision_utils.py`, all PySide6 widget classes. Lower bar on `sniper.py` and `calibrator.py` due to hardware dependencies.

**Running tests:**
```bash
pytest -q              # all tests
pytest --cov --cov-report=term-missing  # with coverage
```

**pytest-qt notes:**
- Every new PySide6 widget class needs a matching `test_<widget>.py` with at minimum: widget renders, primary button/signal works, invalid input is rejected.
- Use `qtbot.addWidget(widget)` to ensure cleanup.
- Use `qtbot.mouseClick` / `qtbot.keyClick` for interaction tests; don't call `.click()` directly.

**Other notes:**
- Tests use monkeypatching on `pyautogui.screenshot` — FH6 does not need to be running.
- Test fixtures live in `tests/` (`auction_present.png`, `auction_absent.png`).
- pywin32 calls are Windows-only; keep them isolated in `window_utils.py`.

---

## Config

Runtime config is stored at `%APPDATA%\FH6Sniper\config.json`.
Never commit `config.json` or `sniper.log` (already in `.gitignore`).

---

## Known Issues

### Screenshot capture — occasional "lost chance" scan

FH6 uses DirectX 12 with flip-model presentation and hardware overlay planes.
DXGI Desktop Duplication (`dxcam`) occasionally captures the raw 3D game scene instead
of the auction UI overlay (~1 in 74 scans). The sniper handles this safely:

- All rows in a scan share **one** `grab_full_screen()` call, so a bad frame makes all
  rows appear dark → scan skips cleanly (no false buy).
- The brightness check (`row_has_car`) catches bad frames before badge detection runs,
  so a false "available" is not possible from this path.
- **Effect:** one missed scan opportunity. The loop refreshes and retries next cycle.

**Proper fix (not yet implemented):** Windows Graphics Capture (WGC) API via the
`windows-capture` Python package — the same API used by Xbox Game Bar and OBS Game
Capture. It correctly captures hardware overlay planes. If this becomes a problem,
the fix belongs in `vision_utils.grab_full_screen()`, not in detection logic.

---

## Active Work

See GitHub issues for the current roadmap. The PySide6 UI migration (issues #4–#9)
is complete — all new UI code is PySide6.

## Performance Rules

Speed is the product — the sniper races other players to buy cars. When touching
the scan loop or buy sequence:

- `pyautogui.PAUSE` is set to 0 in sniper.py; all inter-key timing must be explicit
  via `stop_event.wait(...)` with configurable intervals. Never rely on implicit
  pauses, and never use `pyautogui.typewrite(interval=...)` (it sleeps after the
  last key and can't be interrupted by stop_event).
- Nothing in the per-scan or per-row path may read a file or enumerate windows
  unnecessarily — config.json and row-tuning JSON are mtime-cached, templates are
  cached in vision_utils, candidate lists are hoisted out of loops. Keep it that way.
- Timing defaults live ONLY in `settings.DEFAULT_TIMINGS`; the sold-badge threshold
  lives ONLY in `vision_utils.SOLD_THRESHOLD`. Never introduce a second copy.
