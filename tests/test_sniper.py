import pytest

import settings
import sniper
import vision_utils
import window_utils


def noop(*args, **kwargs):
    # placeholder for monkeypatched keystrokes
    pass


@pytest.fixture(autouse=True)
def disable_keystrokes(monkeypatch):
    """Prevent any test from sending real keystrokes via pyautogui."""
    monkeypatch.setattr(sniper.pyautogui, "keyDown", noop)
    monkeypatch.setattr(sniper.pyautogui, "keyUp", noop)
    monkeypatch.setattr(sniper.pyautogui, "press", noop)
    return None


class DummyVision:
    def __init__(self, result_sequence):
        self.seq = list(result_sequence)

    def locate_on_screen_with_variants(self, *args, **kwargs):
        return self.seq.pop(0) if self.seq else None


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    # redirect settings to temp config
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(settings, "CONFIG_FILE", str(cfg))
    return cfg


def test_press_key_holds_before_release(monkeypatch):
    import time as _time

    events = []
    monkeypatch.setattr(
        sniper.pyautogui, "keyDown", lambda k: events.append(("down", k, _time.perf_counter()))
    )
    monkeypatch.setattr(
        sniper.pyautogui, "keyUp", lambda k: events.append(("up", k, _time.perf_counter()))
    )
    sniper.press_key("y")
    assert [(e[0], e[1]) for e in events] == [("down", "y"), ("up", "y")]
    held = events[1][2] - events[0][2]
    assert held >= sniper.KEY_HOLD_MIN_S * 0.5  # generous lower bound for timer jitter


def test_buy_sequence_aborts_when_unfocused(monkeypatch):
    monkeypatch.setattr(window_utils, "is_fh6_focused", lambda: False)
    messages = []
    res = sniper.buy_sequence(settings.load_timings(), log=messages.append)
    assert res is None
    assert any("Buy sequence aborted" in m for m in messages)


def test_buy_sequence_success_and_failure(monkeypatch):
    monkeypatch.setattr(window_utils, "is_fh6_focused", lambda: True)
    monkeypatch.setattr(vision_utils, "grab_full_screen", lambda: None)
    monkeypatch.setattr(sniper.pyautogui, "screenshot", lambda: _FakeScreen())

    monkeypatch.setattr(sniper, "_detect_buy_result", lambda raw, full_region=None: True)
    assert sniper.buy_sequence(settings.load_timings()) is True

    monkeypatch.setattr(sniper, "_detect_buy_result", lambda raw, full_region=None: None)
    assert sniper.buy_sequence(settings.load_timings()) is None


class _FakeScreen:
    width = 1920
    height = 1080

    def crop(self, box):
        return self


def _patch_rows(monkeypatch, sold_scores):
    """Make every row look occupied, with the given per-row sold scores."""
    monkeypatch.setattr(vision_utils, "row_has_car", lambda region, row_img=None: True)
    monkeypatch.setattr(vision_utils, "build_sold_candidates", lambda tpl, w: [tpl])
    scores = list(sold_scores)
    monkeypatch.setattr(
        vision_utils,
        "sold_badge_score",
        lambda region, params, tpl, row_img=None, candidates=None: scores.pop(0),
    )


def test_car_available_ocr_mode(monkeypatch, isolate_config):
    """With AUCTION_BUTTON_OCR on, detection is decided by the button text."""
    import json

    isolate_config.write_text(json.dumps({"AUCTION_BUTTON_OCR": True}))
    monkeypatch.setattr(sniper, "CONFIG_FILE", str(isolate_config))
    monkeypatch.setattr(sniper, "_config_cache", {"mtime": None, "data": None})
    monkeypatch.setattr(vision_utils, "_winrt_available", lambda: True)

    monkeypatch.setattr(vision_utils, "ocr_text_pil", lambda img: "Auction Options")
    assert sniper.car_available(region=(0, 0, 100, 50), full_img=_FakeScreen()) is True

    monkeypatch.setattr(vision_utils, "ocr_text_pil", lambda img: "some other screen")
    assert sniper.car_available(region=(0, 0, 100, 50), full_img=_FakeScreen()) is False


def test_find_available_row_buy_last_targets_last(monkeypatch):
    _patch_rows(monkeypatch, [0.0, 0.0, 0.0])  # three available rows
    rows = [(0, 0, 100, 50), (0, 50, 100, 50), (0, 100, 100, 50)]
    idx, saw_car = sniper.find_available_row(
        rows,
        {"badge_x_pct": 0},
        window_utils.resource_path("assets/sold_badge_template.png"),
        full_img=_FakeScreen(),
        buy_last=True,
    )
    assert idx == 2
    assert saw_car


def test_find_available_row_buy_first_stops_early(monkeypatch):
    calls = []

    def counting_score(region, params, tpl, row_img=None, candidates=None):
        calls.append(region)
        return 0.9 if len(calls) == 1 else 0.0  # row 1 sold, rest available

    monkeypatch.setattr(vision_utils, "row_has_car", lambda region, row_img=None: True)
    monkeypatch.setattr(vision_utils, "build_sold_candidates", lambda tpl, w: [tpl])
    monkeypatch.setattr(vision_utils, "sold_badge_score", counting_score)

    rows = [(0, 0, 100, 50), (0, 50, 100, 50), (0, 100, 100, 50)]
    idx, saw_car = sniper.find_available_row(
        rows,
        {"badge_x_pct": 0},
        window_utils.resource_path("assets/sold_badge_template.png"),
        full_img=_FakeScreen(),
        buy_last=False,
    )
    assert idx == 1  # first available (row 2, 0-based 1)
    assert saw_car
    assert len(calls) == 2  # row 3 was never checked


def test_find_available_row_retries_unrendered_row(monkeypatch):
    """Row 1 empty on the first frame (mid-render) → rescan on a fresh frame
    instead of giving up, since the caller already saw the auction button."""
    calls = {"n": 0}

    def flaky_row_has_car(region, row_img=None):
        calls["n"] += 1
        return calls["n"] > 1  # first check reads empty; rendered on the retry

    monkeypatch.setattr(vision_utils, "row_has_car", flaky_row_has_car)
    monkeypatch.setattr(vision_utils, "build_sold_candidates", lambda tpl, w: [tpl])
    monkeypatch.setattr(
        vision_utils,
        "sold_badge_score",
        lambda region, params, tpl, row_img=None, candidates=None: 0.0,
    )
    monkeypatch.setattr(vision_utils, "grab_full_screen", lambda: _FakeScreen())
    monkeypatch.setattr(sniper.time, "sleep", lambda s: None)

    idx, saw_car = sniper.find_available_row(
        [(0, 0, 100, 50)],
        {"badge_x_pct": 0},
        window_utils.resource_path("assets/sold_badge_template.png"),
        full_img=_FakeScreen(),
        buy_last=True,
    )
    assert idx == 0
    assert saw_car
    assert calls["n"] == 2  # exactly one retry was needed


def test_reset_search(monkeypatch):
    calls = []

    def fake_press(key):
        calls.append(key)

    monkeypatch.setattr(window_utils, "wait_for_fh6_focus", lambda stop_event=None: True)
    monkeypatch.setattr(window_utils, "is_fh6_focused", lambda: True)
    monkeypatch.setattr(sniper, "press_key", fake_press)
    sniper.reset_search(settings.load_timings())
    assert calls == ["esc", "\n", "\n"], "reset_search should press esc, enter, enter in order"

    # if unfocused, no keys sent
    calls.clear()
    monkeypatch.setattr(window_utils, "is_fh6_focused", lambda: False)
    sniper.reset_search(settings.load_timings())
    assert not calls
