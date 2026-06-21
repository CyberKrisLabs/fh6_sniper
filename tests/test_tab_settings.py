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
    assert 0.1 <= settings_tab.buy_interval_spin.value() <= 20.0
    assert 0.1 <= settings_tab.post_buy_spin.value() <= 20.0
    assert 0.1 <= settings_tab.reset_interval_spin.value() <= 20.0
    assert 0 <= settings_tab.scans_spin.value() <= 1000000


def test_preset_fast_applies_values(settings_tab):
    settings_tab.preset_combo.setCurrentText("Fast")
    assert abs(settings_tab.buy_interval_spin.value() - 0.3) < 0.01
    assert abs(settings_tab.post_buy_spin.value() - 4.0) < 0.01
    assert abs(settings_tab.reset_interval_spin.value() - 0.7) < 0.01


def test_preset_slow_applies_values(settings_tab):
    settings_tab.preset_combo.setCurrentText("Slow")
    assert abs(settings_tab.buy_interval_spin.value() - 0.7) < 0.01
    assert abs(settings_tab.post_buy_spin.value() - 6.0) < 0.01
    assert abs(settings_tab.reset_interval_spin.value() - 1.1) < 0.01


def test_save_shows_success_feedback(settings_tab, qtbot):
    settings_tab._save()
    assert (
        "saved" in settings_tab.feedback_label.text().lower()
        or "applied" in settings_tab.feedback_label.text().lower()
    )


def test_detect_preset_mid(settings_tab):
    settings_tab.buy_interval_spin.setValue(0.5)
    settings_tab.post_buy_spin.setValue(5.0)
    settings_tab.reset_interval_spin.setValue(0.8)
    settings_tab._detect_preset()
    assert settings_tab.preset_combo.currentText() == "Mid"


def test_detect_preset_custom(settings_tab):
    settings_tab.buy_interval_spin.setValue(1.2)
    settings_tab.post_buy_spin.setValue(3.3)
    settings_tab.reset_interval_spin.setValue(2.5)
    settings_tab._detect_preset()
    assert settings_tab.preset_combo.currentText() == "Custom"
