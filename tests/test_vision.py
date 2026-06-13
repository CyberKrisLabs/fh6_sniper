import pyautogui
import pytest
from PIL import Image

import vision_utils
import window_utils

# we will monkeypatch pyautogui.screenshot to return known images


def test_locate_template_matches(monkeypatch, tmp_path):
    # use one of the existing templates as the "screen"
    template = window_utils.resource_path("assets/auction_options_template.png")
    img = Image.open(template)

    def fake_screenshot(region=None):
        # ignore region and return the template itself as screenshot
        return img

    monkeypatch.setattr(pyautogui, "screenshot", fake_screenshot)
    # since screenshot equals template, detection should succeed
    loc = vision_utils.locate_on_screen_with_variants(template, confidence=0.1)
    assert loc is not None

    # if we search for a non-existing image, result should be None
    none_path = tmp_path / "none.png"
    none_path.write_text("not an image")
    # invalid image should surface an error rather than quietly returning None
    with pytest.raises(ValueError):
        vision_utils.locate_on_screen_with_variants(str(none_path), confidence=0.9)
