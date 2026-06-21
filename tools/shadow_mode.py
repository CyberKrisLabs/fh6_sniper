"""Shadow mode — runs the full sniper detection loop without buying.

Displays an always-on-top overlay with per-scan results and logs all scores
to the console so you can verify detection is working before running live.

Usage:
    python tools/shadow_mode.py
    python tools/shadow_mode.py --scans 500 --no-reset
"""

import argparse
import datetime
import os
import queue
import sys
import threading
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibrator  # noqa: E402
import sniper  # noqa: E402
import vision_utils  # noqa: E402
import window_utils  # noqa: E402

SOLD_THRESHOLD = sniper.SOLD_THRESHOLD

COLOR_BG = "#0d1117"
COLOR_AVAILABLE = "#3fb950"
COLOR_SOLD = "#f78166"
COLOR_RESET = "#8b949e"
COLOR_HEADER = "#58a6ff"
OVERLAY_W = 440


# ── Thread-safe overlay ───────────────────────────────────────────────────────


class StatusOverlay:
    """Borderless always-on-top overlay. Thread-safe via a message queue."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.90)
        self.root.configure(bg=COLOR_BG)

        self._label = tk.Label(
            self.root,
            text="Shadow Mode — starting...",
            font=("Consolas", 10),
            bg=COLOR_BG,
            fg=COLOR_HEADER,
            justify=tk.LEFT,
            anchor="nw",
            padx=12,
            pady=8,
            wraplength=OVERLAY_W - 20,
            width=52,
        )
        self._label.pack(fill=tk.BOTH, expand=True)

        self._hide_job = None

        # Position top-right, calculated after widgets are laid out
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{sw - OVERLAY_W - 16}+16")

        # Poll the queue every 50 ms on the main thread
        self.root.after(50, self._drain)

    def _drain(self):
        try:
            while True:
                fn = self._q.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def show(self, text: str, color: str = COLOR_HEADER, duration: float = 3.0):
        """Thread-safe: can be called from any thread."""

        def _update():
            if self._hide_job is not None:
                self.root.after_cancel(self._hide_job)
            self._label.configure(text=text, fg=color)
            self.root.deiconify()
            self._hide_job = self.root.after(int(duration * 1000), self._hide)

        self._q.put(_update)

    def _hide(self):
        self.root.withdraw()
        self._hide_job = None

    def tick(self):
        self.root.update()


# ── Scan loop (background thread) ─────────────────────────────────────────────


def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def shadow_loop(stop_event: threading.Event, overlay: StatusOverlay, scans: int, do_reset: bool):
    def log(msg: str):
        print(f"[{_ts()}] {msg}")

    # Countdown so user has time to focus FH6
    for i in range(5, 0, -1):
        if stop_event.is_set():
            return
        log(f"Starting in {i}...")
        overlay.show(
            f"Shadow Mode\nFocus FH6 now!\n\nStarting in {i}...",
            color=COLOR_HEADER,
            duration=1.1,
        )
        stop_event.wait(1)

    log("Shadow mode running — Ctrl+C to stop")

    cfg = sniper.load_config()
    timings = sniper.load_timings()

    manual_region = (
        tuple(cfg["AUCTION_OPTIONS_REGION"]) if "AUCTION_OPTIONS_REGION" in cfg else None
    )
    auto_region = (
        tuple(cfg["AUTO_AUCTION_OPTIONS_REGION"]) if "AUTO_AUCTION_OPTIONS_REGION" in cfg else None
    )

    window = window_utils.get_fh6_window()
    full_region = window_utils.get_window_region(window) if window else None

    if manual_region:
        bottom_left_region = manual_region
        log(f"Using manual region: {manual_region}")
    elif auto_region:
        bottom_left_region = auto_region
        log(f"Using auto region: {auto_region}")
    elif full_region:
        bottom_left_region = window_utils.bottom_left_quarter(full_region)
        log(f"Using window bottom-left quarter: {bottom_left_region}")
    else:
        log("WARNING: no region configured — detection may fail")
        bottom_left_region = None

    badge_params = sniper.load_badge_params(
        window.width if window else None,
        window.height if window else None,
    )
    sold_template = calibrator.load_sold_badge_template() or window_utils.resource_path(
        "assets/sold_badge_template.png"
    )
    log("Sold-badge detection: " + ("enabled" if badge_params else "DISABLED (missing json)"))

    for i in range(scans):
        if stop_event.is_set():
            break

        try:
            if not window_utils.is_fh6_focused():
                log("FH6 not focused — waiting")
                overlay.show("Waiting for FH6 focus...", color=COLOR_RESET, duration=2.0)
                stop_event.wait(1)
                continue
        except Exception:
            stop_event.wait(0.5)
            continue

        scan_n = i + 1

        if not sniper.car_available(region=bottom_left_region):
            log(f"Scan #{scan_n}  NO CAR — would reset")
            overlay.show(f"Scan #{scan_n}\nNO CAR — reset", color=COLOR_RESET, duration=1.5)
            if do_reset:
                sniper.reset_search(timings, stop_event=stop_event)
            continue

        # Auction button visible — scan every row
        win_now = window_utils.get_fh6_window()
        row_regions = window_utils.get_row_regions(win_now) if win_now else []

        if not row_regions:
            log(f"Scan #{scan_n}  car_available=True but no row regions")
            continue

        full_img = vision_utils.grab_full_screen()
        row_lines: list[str] = []
        row_states: list[str] = []

        for row_idx, row_reg in enumerate(row_regions):
            rx, ry, rw, rh = row_reg
            row_img = (
                full_img.crop((rx, ry, rx + rw, ry + rh))
                if full_img is not None
                else vision_utils.grab_region(row_reg)
            )

            if not vision_utils.row_has_car(row_reg, row_img=row_img):
                row_lines.append(f"  Row {row_idx + 1}: empty")
                row_states.append("empty")
                continue

            if badge_params and os.path.isfile(sold_template):
                score = vision_utils.sold_badge_score(
                    row_reg, badge_params, sold_template, row_img=row_img
                )
                if score >= SOLD_THRESHOLD:
                    row_lines.append(f"  Row {row_idx + 1}: SOLD       score={score:.3f}")
                    row_states.append("sold")
                else:
                    row_lines.append(f"  Row {row_idx + 1}: available  score={score:.3f}")
                    row_states.append("available")
            else:
                row_lines.append(f"  Row {row_idx + 1}: available  (badge detection off)")
                row_states.append("available")

        log(f"Scan #{scan_n}  car_available=True")
        for line in row_lines:
            log(line)

        available_indices = [idx for idx, s in enumerate(row_states) if s == "available"]
        has_sold = any(s == "sold" for s in row_states)

        if available_indices:
            target = available_indices[-1] + 1
            log(f"  -> WOULD BUY row {target} (shadow: skipped)")
            overlay.show(
                f"Scan #{scan_n}  CAR AVAILABLE\nWould buy: Row {target}\n\n"
                + "\n".join(row_lines),
                color=COLOR_AVAILABLE,
                duration=3.0,
            )
        elif has_sold:
            log("  -> all visible rows sold — would reset")
            overlay.show(
                f"Scan #{scan_n}  ALL SOLD\nWould reset\n\n" + "\n".join(row_lines),
                color=COLOR_SOLD,
                duration=3.0,
            )
        else:
            log("  -> no available rows — would reset")
            overlay.show(
                f"Scan #{scan_n}\nNO AVAILABLE ROWS — reset", color=COLOR_RESET, duration=2.0
            )

        if do_reset:
            sniper.reset_search(timings, stop_event=stop_event)

    log("Shadow mode stopped")
    overlay.show("Shadow Mode\nStopped", color=COLOR_RESET, duration=5.0)


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="FH6 shadow mode — detection only, no buying")
    parser.add_argument(
        "--scans", type=int, default=2000, help="Max scan iterations (default 2000)"
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Observe only — do not send reset keystrokes to the game",
    )
    args = parser.parse_args()

    stop_event = threading.Event()
    overlay = StatusOverlay()

    thread = threading.Thread(
        target=shadow_loop,
        args=(stop_event, overlay, args.scans, not args.no_reset),
        daemon=True,
    )
    thread.start()

    try:
        while thread.is_alive():
            overlay.tick()
            time.sleep(0.016)
    except KeyboardInterrupt:
        print("\nCtrl+C — stopping")
        stop_event.set()

    thread.join(timeout=5)


if __name__ == "__main__":
    main()
