"""Tests for SettingsTab widget."""

import pytest

pytest.importorskip("PySide6")

import app
import settings


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Redirect config writes to a temp file so tests don't touch real user config."""
    temp = tmp_path / "config.json"
    monkeypatch.setattr(settings, "CONFIG_FILE", str(temp))
    monkeypatch.setattr(app.calibrator, "CONFIG_FILE", str(temp))


@pytest.fixture
def sniper_tab(qtbot):
    tab = app.SniperTab()
    qtbot.addWidget(tab)
    return tab


@pytest.fixture
def settings_tab(qtbot, sniper_tab):
    tab = app.SettingsTab(sniper_tab)
    qtbot.addWidget(tab)
    return tab


def test_initial_values_in_range(settings_tab):
    assert 0.1 <= settings_tab.car_available_spin.value() <= 20.0
    assert 0.1 <= settings_tab.nav_interval_spin.value() <= 20.0
    assert 0.1 <= settings_tab.confirm_buy_spin.value() <= 20.0
    assert 0.1 <= settings_tab.post_buy_spin.value() <= 20.0
    assert 0.5 <= settings_tab.exit_auction_spin.value() <= 20.0
    assert 0.1 <= settings_tab.enter_auction_spin.value() <= 20.0
    assert 0.1 <= settings_tab.load_cars_spin.value() <= 20.0
    assert 0 <= settings_tab.scans_spin.value() <= 1000000


def test_exit_auction_spin_floored_at_half_second(settings_tab):
    assert settings_tab.exit_auction_spin.minimum() == 0.5
    settings_tab.exit_auction_spin.setValue(0.1)
    assert settings_tab.exit_auction_spin.value() == 0.5
    # Enter Auction has no extra floor — just the global MIN_INTERVAL
    assert settings_tab.enter_auction_spin.minimum() == settings.MIN_INTERVAL


def test_preset_fast_applies_values(settings_tab):
    settings_tab.preset_combo.setCurrentText("Fast")
    assert abs(settings_tab.car_available_spin.value() - 0.4) < 0.01
    assert abs(settings_tab.nav_interval_spin.value() - 0.3) < 0.01
    assert abs(settings_tab.confirm_buy_spin.value() - 0.35) < 0.01
    assert abs(settings_tab.post_buy_spin.value() - 4.0) < 0.01
    assert abs(settings_tab.exit_auction_spin.value() - 0.725) < 0.01
    assert abs(settings_tab.enter_auction_spin.value() - 0.3) < 0.01
    assert abs(settings_tab.load_cars_spin.value() - 0.8) < 0.01


def test_preset_faster_applies_values(settings_tab):
    settings_tab.preset_combo.setCurrentText("Faster")
    assert abs(settings_tab.car_available_spin.value() - 0.24) < 0.01
    assert abs(settings_tab.nav_interval_spin.value() - 0.05) < 0.01
    assert abs(settings_tab.confirm_buy_spin.value() - 0.18) < 0.01
    assert abs(settings_tab.post_buy_spin.value() - 4.0) < 0.01
    assert abs(settings_tab.exit_auction_spin.value() - 0.65) < 0.01
    assert abs(settings_tab.enter_auction_spin.value() - 0.255) < 0.01
    assert abs(settings_tab.load_cars_spin.value() - 0.75) < 0.01


def test_preset_slow_applies_values(settings_tab):
    settings_tab.preset_combo.setCurrentText("Slow")
    assert abs(settings_tab.car_available_spin.value() - 0.8) < 0.01
    assert abs(settings_tab.nav_interval_spin.value() - 0.7) < 0.01
    assert abs(settings_tab.confirm_buy_spin.value() - 0.75) < 0.01
    assert abs(settings_tab.post_buy_spin.value() - 6.0) < 0.01
    assert abs(settings_tab.exit_auction_spin.value() - 1.2) < 0.01
    assert abs(settings_tab.enter_auction_spin.value() - 0.7) < 0.01
    assert abs(settings_tab.load_cars_spin.value() - 1.2) < 0.01


def test_buy_last_checkbox_defaults_on(settings_tab):
    assert settings_tab.buy_last_cb.isChecked()


def test_button_ocr_checkbox_defaults_off_and_toggles(settings_tab):
    assert not settings_tab.button_ocr_cb.isChecked()
    settings_tab.button_ocr_cb.setChecked(True)
    assert settings.get_auction_button_ocr() is True


def test_overlay_checkbox_defaults_off_and_toggles(settings_tab):
    assert not settings_tab.overlay_cb.isChecked()
    assert settings_tab._sniper_tab._overlay_enabled is False
    settings_tab.overlay_cb.setChecked(True)
    assert settings.get_show_ingame_overlay() is True
    assert settings_tab._sniper_tab._overlay_enabled is True


def test_default_timings_match_mid_preset():
    """A fresh config must detect as 'Mid', not 'Custom' — keep defaults in sync."""
    from ui.tabs.settings import PRESETS

    for key, val in PRESETS["Mid"].items():
        assert abs(settings.DEFAULT_TIMINGS[key] - val) < 0.01, key


def test_save_shows_success_feedback(settings_tab, qtbot):
    settings_tab._save()
    assert (
        "saved" in settings_tab.feedback_label.text().lower()
        or "applied" in settings_tab.feedback_label.text().lower()
    )


def test_detect_preset_mid(settings_tab):
    settings_tab.car_available_spin.setValue(0.6)
    settings_tab.nav_interval_spin.setValue(0.4)
    settings_tab.confirm_buy_spin.setValue(0.45)
    settings_tab.post_buy_spin.setValue(5.0)
    settings_tab.exit_auction_spin.setValue(0.9)
    settings_tab.enter_auction_spin.setValue(0.4)
    settings_tab.load_cars_spin.setValue(0.9)
    settings_tab._detect_preset()
    assert settings_tab.preset_combo.currentText() == "Mid"


def test_detect_preset_custom(settings_tab):
    settings_tab.car_available_spin.setValue(1.2)
    settings_tab.nav_interval_spin.setValue(0.9)
    settings_tab.confirm_buy_spin.setValue(0.9)
    settings_tab.post_buy_spin.setValue(3.3)
    settings_tab.exit_auction_spin.setValue(2.5)
    settings_tab.enter_auction_spin.setValue(2.5)
    settings_tab.load_cars_spin.setValue(2.5)
    settings_tab._detect_preset()
    assert settings_tab.preset_combo.currentText() == "Custom"
