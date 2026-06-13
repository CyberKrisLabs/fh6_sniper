"""Tests for SniperTab widget."""

import pytest

pytest.importorskip("PySide6")

import app


@pytest.fixture
def sniper_tab(qtbot):
    tab = app.SniperTab()
    qtbot.addWidget(tab)
    return tab


def test_initial_state(sniper_tab):
    assert sniper_tab.start_btn.isEnabled()
    assert not sniper_tab.stop_btn.isEnabled()


def test_timer_label_initial(sniper_tab):
    assert "00:00" in sniper_tab.timer_label.text()


def test_log_appended(sniper_tab):
    sniper_tab._append_log("hello world")
    assert "hello world" in sniper_tab.log_view.toPlainText()


def test_stats_updated_signal(sniper_tab, qtbot):
    with qtbot.waitSignal(sniper_tab.stats_updated, timeout=1000, raising=False):
        sniper_tab.stats_updated.emit(1, 1, 0, 2, 5)
    assert "1" in sniper_tab.stats_label.text()


def test_tick_timer_increments(sniper_tab):
    sniper_tab._elapsed = 0
    sniper_tab._tick_timer()
    assert sniper_tab._elapsed == 1
    assert "00:01" in sniper_tab.timer_label.text()


def test_tick_timer_hours(sniper_tab):
    sniper_tab._elapsed = 3599
    sniper_tab._tick_timer()
    assert "1:00:00" in sniper_tab.timer_label.text()


def test_mark_calibration_done(sniper_tab):
    assert not sniper_tab._calib_done_this_session
    sniper_tab.mark_calibration_done()
    assert sniper_tab._calib_done_this_session


def test_stop_while_not_running_is_noop(sniper_tab):
    sniper_tab._stop()
    assert not sniper_tab._stop_event.is_set()


def test_log_bridge_delivers_to_tab(sniper_tab, qtbot):
    app._emit_log("bridge test message")
    qtbot.wait(50)
    assert "bridge test message" in sniper_tab.log_view.toPlainText()
