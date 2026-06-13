"""Tests for CalibrationTab widget."""

import pytest

pytest.importorskip("PySide6")

import app


@pytest.fixture
def sniper_tab(qtbot):
    tab = app.SniperTab()
    qtbot.addWidget(tab)
    return tab


@pytest.fixture
def calib_tab(qtbot, sniper_tab):
    tab = app.CalibrationTab(sniper_tab)
    qtbot.addWidget(tab)
    return tab


def test_remove_buttons_disabled_when_no_calibration(calib_tab, monkeypatch):
    monkeypatch.setattr("calibrator.has_manual_region", lambda: False)
    monkeypatch.setattr("calibrator.has_auto_region", lambda: False)
    calib_tab._refresh_status()
    assert not calib_tab.manual_remove_btn.isEnabled()
    assert not calib_tab.auto_remove_btn.isEnabled()
    assert not calib_tab.test_btn.isEnabled()
    assert not calib_tab.overlay_btn.isEnabled()


def test_remove_buttons_enabled_when_calibrated(calib_tab, monkeypatch):
    monkeypatch.setattr("calibrator.has_manual_region", lambda: True)
    monkeypatch.setattr("calibrator.has_auto_region", lambda: True)
    calib_tab._refresh_status()
    assert calib_tab.manual_remove_btn.isEnabled()
    assert calib_tab.auto_remove_btn.isEnabled()
    assert calib_tab.test_btn.isEnabled()
    assert calib_tab.overlay_btn.isEnabled()


def test_status_label_shows_not_set(calib_tab, monkeypatch):
    monkeypatch.setattr("calibrator.has_manual_region", lambda: False)
    monkeypatch.setattr("calibrator.has_auto_region", lambda: False)
    calib_tab._refresh_status()
    assert "NOT SET" in calib_tab.status_label.text()


def test_auto_run_disables_button_during_run(calib_tab, monkeypatch, qtbot):
    def fake_auto_calibrate(status_label=None):
        return True

    monkeypatch.setattr("calibrator.auto_calibrate", fake_auto_calibrate)
    monkeypatch.setattr("calibrator.has_manual_region", lambda: False)
    monkeypatch.setattr("calibrator.has_auto_region", lambda: True)

    calib_tab._run_auto()
    qtbot.wait(200)
    assert calib_tab.auto_run_btn.isEnabled()
