"""Generate assets/sniper.ico — modern flat crosshair icon in FH6 orange.

Run once whenever you want to refresh the icon:
    python tools/make_icon.py
"""

import math
import os

from PIL import Image, ImageDraw

ORANGE = (255, 107, 0, 255)
ORANGE_DIM = (255, 107, 0, 140)
BG = (18, 18, 24, 255)


def _draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = cy = size / 2
    pad = size * 0.04

    # ── Rounded square background ────────────────────────────────────────────
    radius = size * 0.18
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=BG,
    )

    # ── Outer scope ring ─────────────────────────────────────────────────────
    ring_r = size * 0.33
    lw = max(1, round(size * 0.055))
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=ORANGE,
        width=lw,
    )

    # ── Tick marks at 12 / 3 / 6 / 9 (small dash on the ring) ───────────────
    if size >= 48:
        tick_len = size * 0.07
        tick_lw = max(1, round(size * 0.035))
        for angle_deg in (0, 90, 180, 270):
            angle = math.radians(angle_deg)
            inner = ring_r - tick_len / 2
            outer = ring_r + tick_len / 2
            x1 = cx + math.cos(angle) * inner
            y1 = cy + math.sin(angle) * inner
            x2 = cx + math.cos(angle) * outer
            y2 = cy + math.sin(angle) * outer
            draw.line([(x1, y1), (x2, y2)], fill=ORANGE, width=tick_lw)

    # ── Crosshair lines ───────────────────────────────────────────────────────
    gap = size * 0.14
    margin = size * 0.10
    line_lw = max(1, round(size * 0.04))

    # horizontal
    draw.line([(pad + margin, cy), (cx - gap, cy)], fill=ORANGE, width=line_lw)
    draw.line([(cx + gap, cy), (size - pad - margin, cy)], fill=ORANGE, width=line_lw)
    # vertical
    draw.line([(cx, pad + margin), (cx, cy - gap)], fill=ORANGE, width=line_lw)
    draw.line([(cx, cy + gap), (cx, size - pad - margin)], fill=ORANGE, width=line_lw)

    # ── Centre dot ────────────────────────────────────────────────────────────
    dot_r = max(1, round(size * 0.055))
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=ORANGE,
    )

    return img


def make_icon() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_draw_icon(s) for s in sizes]

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "sniper.ico")
    images[0].save(
        out,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Icon written -> {os.path.normpath(out)}")


if __name__ == "__main__":
    make_icon()
