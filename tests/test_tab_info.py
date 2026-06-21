"""Tests for InfoTab widget."""

import pytest

pytest.importorskip("PySide6")

import app


@pytest.fixture
def info_tab(qtbot):
    tab = app.InfoTab()
    qtbot.addWidget(tab)
    return tab


def test_version_displayed(info_tab):
    found = any(
        app.__version__ in w.text()
        for w in info_tab.findChildren(__import__("PySide6").QtWidgets.QLabel)
    )
    assert found, f"Version {app.__version__} not found in InfoTab labels"


def test_update_btn_exists(info_tab):
    assert info_tab.update_btn is not None
    assert info_tab.update_btn.isEnabled()


def test_update_check_no_requests(info_tab, monkeypatch, qtbot):
    import ui.tabs.info as _info_mod

    monkeypatch.setattr(_info_mod, "HAVE_REQUESTS", False)
    info_tab._check_updates()
    qtbot.wait(200)
    assert (
        "not installed" in info_tab.update_label.text().lower() or info_tab.update_btn.isEnabled()
    )
