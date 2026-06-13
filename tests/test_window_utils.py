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


def test_bottom_left_quarter():
    reg = (0, 0, 100, 100)
    cropped = window_utils.bottom_left_quarter(reg)
    assert cropped == (0, 50, 50, 50)
    assert window_utils.bottom_left_quarter(None) is None
