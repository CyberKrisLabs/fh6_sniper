import os
import sys

import window_utils


def test_resource_path_normal(monkeypatch, tmp_path):
    # when _MEIPASS not set, returns path relative to file
    p = window_utils.resource_path("foo.txt")
    assert os.path.isabs(p)
    # emulate bundling
    # monkeypatching _MEIPASS even if it doesn't exist yet
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    p2 = window_utils.resource_path("bar.txt")
    assert p2.startswith(str(tmp_path))


def test_resolve_template_path():
    # existing absolute path is returned unchanged
    real = window_utils.resource_path(os.path.join("assets", "sold_badge_template.png"))
    assert window_utils.resolve_template_path(real) == real

    # stale absolute path (e.g. a deleted PyInstaller _MEI dir) falls back to
    # the bundled asset with the same filename
    stale = r"C:\Users\x\AppData\Local\FH6Sniper\_MEI123456\assets\sold_badge_template.png"
    resolved = window_utils.resolve_template_path(stale)
    assert resolved is not None
    assert os.path.isfile(resolved)
    assert os.path.basename(resolved) == "sold_badge_template.png"

    # bare filename (current config format) resolves the same way
    assert window_utils.resolve_template_path("sold_badge_template.png") == resolved

    # unknown filename and empty input resolve to None
    assert window_utils.resolve_template_path("no_such_template.png") is None
    assert window_utils.resolve_template_path(None) is None
    assert window_utils.resolve_template_path("") is None


def test_bottom_left_quarter():
    reg = (0, 0, 100, 100)
    cropped = window_utils.bottom_left_quarter(reg)
    assert cropped == (0, 50, 50, 50)
    assert window_utils.bottom_left_quarter(None) is None
