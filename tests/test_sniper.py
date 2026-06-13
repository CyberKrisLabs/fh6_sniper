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
    monkeypatch.setattr(sniper.pyautogui, "press", noop)
    monkeypatch.setattr(sniper.pyautogui, "typewrite", noop)
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


def test_reset_search(monkeypatch):
    calls = []

    def fake_write(keys, interval=None):
        calls.append(tuple(keys))

    monkeypatch.setattr(window_utils, "wait_for_fh6_focus", lambda stop_event=None: True)
    monkeypatch.setattr(window_utils, "is_fh6_focused", lambda: True)
    monkeypatch.setattr(sniper.pyautogui, "typewrite", fake_write)
    sniper.reset_search(settings.load_timings())
    assert calls, "reset_search should have sent keystrokes"

    # if unfocused, no write
    calls.clear()
    monkeypatch.setattr(window_utils, "is_fh6_focused", lambda: False)
    sniper.reset_search(settings.load_timings())
    assert not calls
