import json

import calibrator


def test_has_manual_region(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    # no file -> False
    monkeypatch.setattr(calibrator, "CONFIG_FILE", str(cfg))
    assert not calibrator.has_manual_region()
    # create with region
    data = {"AUCTION_OPTIONS_REGION": [1, 2, 3, 4]}
    cfg.write_text(json.dumps(data))
    assert calibrator.has_manual_region()


def test_has_auto_region(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    # no file -> False
    monkeypatch.setattr(calibrator, "CONFIG_FILE", str(cfg))
    assert not calibrator.has_auto_region()
    # create with auto region
    data = {"AUTO_AUCTION_OPTIONS_REGION": [1, 2, 3, 4]}
    cfg.write_text(json.dumps(data))
    assert calibrator.has_auto_region()


def test_load_auto_region(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(calibrator, "CONFIG_FILE", str(cfg))
    # no file -> None
    assert calibrator.load_auto_region() is None
    # create with auto region
    data = {"AUTO_AUCTION_OPTIONS_REGION": [1, 2, 3, 4]}
    cfg.write_text(json.dumps(data))
    assert calibrator.load_auto_region() == (1, 2, 3, 4)
