# FH6 Sniper

Automated auction house sniper for Forza Horizon 6. Continuously scans for available cars and executes purchases using image recognition — no manual watching required.

---

## Getting Started

**Requirements:** Python 3.10+, Windows 10/11, Forza Horizon 6

```bash
pip install -r requirements.txt
python app.py
```

1. Launch FH6 and navigate to the Auction House
2. Open FH6 Sniper and run **Auto Calibration** (or Manual if auto fails)
3. Pick a timing preset that matches your PC and connection speed
4. Hit **Start** — the sniper takes over from there

---

## How It Works

The sniper takes rapid screenshots of the auction house region and uses OpenCV template matching to detect when the "Auction Options" button appears. When found, it fires the buy sequence automatically. If the car is gone before it can buy, it refreshes the listing and keeps scanning.

Every keystroke is gated behind a focus check — if FH6 loses focus, the sniper pauses immediately.

---

## Features

| Feature | Description |
|---|---|
| Auto & Manual Calibration | Pinpoints the exact screen region to watch for maximum speed |
| Multi-scale Detection | Finds buttons at any window size using 24-step scale search |
| Timing Presets | Fast / Mid / Slow presets tuned for different PC and connection speeds |
| Focus Safety | Stops sending keystrokes the moment FH6 is no longer the active window |
| In-game Overlay | Frameless always-on-top HUD showing live stats without alt-tabbing |
| Live Stats | Tracks buy attempts, successes, failures, and refreshes in real time |
| Color-coded Log | GUI log with emoji markers; everything also written to `sniper.log` |
| Standalone EXE | Packages into a single executable with PyInstaller |

---

## Timing Presets

| Preset | Buy Interval | Post-buy Wait | Reset Interval | Best For |
|---|---|---|---|---|
| Fast | 0.3 s | 4.0 s | 0.7 s | High-end PC, fast connection |
| Mid | 0.5 s | 5.0 s | 0.8 s | Average PC, stable connection |
| Slow | 0.7 s | 6.0 s | 1.1 s | Slower PC or laggy connection |
| Custom | — | — | — | Manual control over each value |

---

## Calibration

Calibration tells the sniper exactly where on your screen to look, which makes detection faster and more reliable.

- **Auto Calibration** — takes a screenshot and finds the auction button automatically. Works in windowed and fullscreen mode. Try this first.
- **Manual Calibration** — hover your mouse over the top-left corner of the button and confirm, then do the same for the bottom-right corner. Use this if auto fails or if you have an unusual window layout.
- **Row Calibration** — fine-tunes the individual auction row positions used for sold-badge detection.

Recalibrate any time you resize, move, or switch between windowed and fullscreen.

---

## Building a Standalone EXE

```powershell
pyinstaller "FH6 Sniper.spec"
```

Output: `dist\FH6 Sniper.exe`

The spec file already includes the correct icon, assets, docs, and hidden imports for pywin32. Asset paths are resolved at runtime via `window_utils.resource_path`, which handles both normal Python execution and the PyInstaller bundle.

---

## Project Structure

```
app.py            GUI entry point (PySide6)
sniper.py         Core scan and buy loop
vision_utils.py   OpenCV template matching engine
calibrator.py     Region calibration (auto + manual)
window_utils.py   FH6 window detection and DPI handling
settings.py       Config file management
row_tuner.py      Interactive row position tuning tool
assets/           Template images for detection
tools/            Developer diagnostic scripts
tests/            pytest test suite
docs/             Project documentation
```

---

## Running Tests

```bash
pytest -q
```

Vision tests monkeypatch `pyautogui.screenshot` to simulate the screen, so FH6 doesn't need to be running. Add your own screenshots to `tests/` and extend `test_vision.py` for more realistic coverage.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Button not detected | Run Auto Calibration, or try Manual if the window is at an unusual size |
| Scans feel slow | Calibrate to a tighter region around the button |
| Keystrokes not landing | Make sure FH6 is the foreground window when you start |
| Auto calibration fails | Make sure the Auction House is open and visible, then retry |
| False positives / misfires | Increase timing intervals in the Settings tab |

**Config and log locations** (useful for debugging):
- Config: `%APPDATA%\FH6Sniper\config.json`
- Log: `sniper.log` in the same folder as the exe

---

## Support

If this tool saves you time, consider supporting development:

[Donate via PayPal](https://www.paypal.com/ncp/payment/W2FY4KHD58UEG)
