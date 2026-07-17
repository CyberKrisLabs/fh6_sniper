"""Dry-run tool: full sniper cycles with the app's current timings, WITHOUT buying.

Runs the real flow — reset, scan, row detection, navigation, and the buy
sequence — but instead of the final confirm Enter it backs out of the confirm
dialog (Down -> Enter -> Esc, back to the list) and starts the next cycle.
Nothing is ever purchased. Use it to tweak timing settings and verify every
phase lands consistently across repeated cycles, not just once.

Flow:
  1. 5s countdown — switch to FH6.
  2. Initial reset_search (any car already on screen is deliberately ignored,
     so you always get to observe the reset with the current timings).
  3. Scan loop, identical to the live sniper: detect button -> check rows ->
     reset and retry until an available car is found.
  4. Buy sequence up to the LAST step: Y -> Down -> Enter (opens the confirm
     dialog) ... then Down -> Enter -> Esc to decline and return to the list.
  5. Repeats from step 3 for the requested number of cycles.

Timings come from the same config the app saves (change them in the Settings
tab as usual, then re-run this tool).

With --buy the tool runs the SAME flow but performs one REAL purchase: the
final confirm Enter is pressed and the buy result (success/fail) is detected
exactly like the live sniper, then the tool stops after that single cycle.

Usage:
    python tools/dry_run.py [cycles]     # default: 5 dry-buy cycles, no purchase
    python tools/dry_run.py --buy        # ONE real buy, then stop
"""

import os
import sys
import time

# Make sure project root is on the path when run from any directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import calibrator
import settings
import sniper
import vision_utils
import window_utils

COUNTDOWN = 5
MAX_SCANS = 100
DEFAULT_CYCLES = 5


def _resolve_regions():
    """Same region resolution as sniper_loop: manual > auto > window bounds."""
    cfg = sniper.load_config()
    manual = tuple(cfg["AUCTION_OPTIONS_REGION"]) if "AUCTION_OPTIONS_REGION" in cfg else None
    auto = (
        tuple(cfg["AUTO_AUCTION_OPTIONS_REGION"]) if "AUTO_AUCTION_OPTIONS_REGION" in cfg else None
    )
    window = window_utils.get_fh6_window()
    full_region = window_utils.get_window_region(window) if window else None

    if manual:
        print("  Using manual calibration")
        return manual, full_region or manual, window
    if auto:
        print("  Using auto calibration")
        return auto, full_region or auto, window
    if full_region:
        print("  No calibration — using FH6 window bounds (bottom-left quarter)")
        return window_utils.bottom_left_quarter(full_region), full_region, window
    print("  ⚠ FH6 window not found and no calibration — aborting")
    return None, None, None


def _scan_until_available(t, scan_region, window, badge_params, sold_template, buy_last) -> int:
    """Scan exactly like the live loop until an available row appears.

    Returns the 0-based row index, or -1 if none found within MAX_SCANS
    (or focus was lost).
    """
    for i in range(MAX_SCANS):
        if not window_utils.is_fh6_focused():
            print("  🔒 FH6 lost focus — aborting")
            return -1

        shared_frame = vision_utils.grab_full_screen()
        if sniper.car_available(region=scan_region, full_img=shared_frame):
            row_regions = window_utils.get_row_regions(window) if window else []
            if row_regions and badge_params:
                available, saw_any_car = sniper.find_available_row(
                    row_regions,
                    badge_params,
                    sold_template,
                    log=print,
                    full_img=shared_frame,
                    buy_last=buy_last,
                )
            else:
                available, saw_any_car = 0, True

            if available >= 0:
                print(f"  Scan #{i + 1} ✅ Row {available + 1} available — starting dry buy")
                return available
            reason = "all visible rows sold" if saw_any_car else "row 1 didn't render in time"
            print(f"  Scan #{i + 1} 🏷 {reason} — resetting")
        else:
            print(f"  Scan #{i + 1} ❌ No car — resetting")
        sniper.reset_search(t, log=print)
    print(f"  No available car found in {MAX_SCANS} scans — stopping")
    return -1


def _dry_buy(t, available: int) -> None:
    """The real buy sequence, minus the final confirm Enter, then a safe
    decline: Down -> Enter (selects No/cancel) -> Esc back to the list."""
    if available > 0:
        nav_delay = t.get("nav_interval", sniper.DEFAULT_TIMINGS["nav_interval"])
        print(f"  Navigating down {available} row(s)...")
        for _ in range(available):
            sniper.press_key("down")
            time.sleep(nav_delay)

    print("  Buy sequence (dry): Y -> Down -> Enter ... stopping before confirm")
    sniper.press_key("y")
    time.sleep(t.get("car_available_interval", sniper.DEFAULT_TIMINGS["car_available_interval"]))
    sniper.press_key("down")
    time.sleep(t.get("nav_interval", sniper.DEFAULT_TIMINGS["nav_interval"]))
    sniper.press_key("\n")  # selects Buy Out -> opens the confirm dialog
    time.sleep(t.get("confirm_buy_interval", sniper.DEFAULT_TIMINGS["confirm_buy_interval"]))

    print("  🏁 Confirm dialog reached — the live sniper would press Enter here. NOT confirming.")

    # Decline instead of confirming: Down -> Enter -> Esc back to the list.
    print("  Declining (Down -> Enter -> Esc) back to the list...")
    sniper.press_key("down")
    time.sleep(t.get("nav_interval", sniper.DEFAULT_TIMINGS["nav_interval"]))
    sniper.press_key("\n")
    time.sleep(t.get("enter_auction_interval", sniper.DEFAULT_TIMINGS["enter_auction_interval"]))
    sniper.press_key("esc")
    time.sleep(t.get("exit_auction_interval", sniper.DEFAULT_TIMINGS["exit_auction_interval"]))


def main() -> int:
    live_buy = "--buy" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--buy"]
    cycles = 1 if live_buy else DEFAULT_CYCLES
    if args and not live_buy:
        try:
            cycles = max(1, int(args[0]))
        except ValueError:
            print(f"Invalid cycle count {args[0]!r} — using {DEFAULT_CYCLES}")

    t = settings.load_timings()
    buy_last = settings.get_buy_last_available()

    if live_buy:
        print("FH6 Sniper — LIVE BUY TEST (⚠ this WILL purchase ONE car!)")
    else:
        print("FH6 Sniper — DRY RUN (no purchase will be made)")
    print("-" * 50)
    print("  Timings:", ", ".join(f"{k}={v}" for k, v in t.items()))
    print(f"  Buy last available: {buy_last}")
    print(f"  Cycles: {cycles}")
    print(f"\nSwitch to FH6 now. Starting in {COUNTDOWN} seconds...")
    for i in range(COUNTDOWN, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    scan_region, full_region, window = _resolve_regions()
    if scan_region is None:
        return 1

    badge_params = sniper.load_badge_params(
        window.width if window else None, window.height if window else None
    )
    sold_template = calibrator.load_sold_badge_template() or window_utils.resource_path(
        "assets/sold_badge_template.png"
    )
    if not badge_params:
        print("  ⚠ No badge calibration — sold detection skipped (rows treated as available)")

    # Always reset first, even if a car is on screen, so the reset flow runs
    # with the current timings before the first scan.
    print("\n[cycle 1] Initial reset (ignoring any available car)...")
    sniper.reset_search(t, log=print)

    completed = 0
    for cycle in range(1, cycles + 1):
        print(f"\n[cycle {cycle}/{cycles}] Scanning (Ctrl+C to abort)...")
        available = _scan_until_available(
            t, scan_region, window, badge_params, sold_template, buy_last
        )
        if available < 0:
            break

        if live_buy:
            # Navigate to the row, then run the REAL buy sequence — confirm,
            # result detection, dismissal, and the post-buy reset — exactly
            # like the live sniper.
            if available > 0:
                nav_delay = t.get("nav_interval", sniper.DEFAULT_TIMINGS["nav_interval"])
                print(f"  Navigating down {available} row(s)...")
                for _ in range(available):
                    sniper.press_key("down")
                    time.sleep(nav_delay)
            print("  ⚠ LIVE buy sequence — confirming for real...")
            result = sniper.buy_sequence(t, full_region=full_region, log=print)
            if result is True:
                print("  ✅ Buy SUCCESSFUL")
            elif result is False:
                print("  ❌ Buy FAILED (someone else got it / not enough credits)")
            else:
                print("  ⚠ Buy result UNDETERMINED — check the game and Post Buy Wait")
            completed += 1
            break  # live mode: one purchase, then stop

        _dry_buy(t, available)
        completed += 1
        print(f"[cycle {cycle}/{cycles}] ✅ dry-buy cycle complete")
        if cycle < cycles:
            # Same as the live sniper after a buy: reset back to a fresh list.
            sniper.reset_search(t, log=print)

    label = "live-buy" if live_buy else "dry-buy"
    print(f"\nDone: {completed}/{cycles} {label} cycles completed.")
    print("Tweak settings in the app and re-run for the next test.")
    return 0 if completed == cycles else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAborted by user (no keys will be sent).")
        raise SystemExit(130) from None
