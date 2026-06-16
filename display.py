#!/usr/bin/env python3
"""
Treadmill console display image — session stats overlaid on a real photo
of the console, lighting up the actual LED digit positions.

Place a photo of your own console at assets/console_photo.jpg (close-up,
straight-on, showing the TIME / SPEED / DISTANCE / CALORIES LED display).
The coordinates below were calibrated for that specific photo; if you use
a different photo or framing, re-measure the pixel positions.

Requires: Pillow
Enable:   "visualize": true in config.json (same flag as the poster)

DSEG7 font (keshikan, SIL OFL) is downloaded once into assets/.
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"
_PHOTO  = _ASSETS / "console_photo.jpg"

_DSEG7_URL = (
    "https://github.com/keshikan/DSEG/releases/download/v0.46/fonts-DSEG_v046.zip"
)

# ── Calibration for assets/console_photo.jpg ──────────────────────────────────
# Crop window — the full console panel (rounded top, both speakers, logo),
# not just a thin sliver around the display, so the result looks like a real photo.
_CROP  = (0, 900, 5712, 2200)
_SCALE = 0.40

# LED digit row (original photo coords) — erased and redrawn
_DIGIT_Y0, _DIGIT_Y1 = 1410, 1640
_REF_ROW = 1385  # clean background row sampled to erase the existing digits

# Single erase band spanning all four displays (avoids leftover "0:00" ghosting
# regardless of how wide the new value renders)
_ERASE_X0, _ERASE_X1 = 1780, 4020

# (label, x0, x1) — label text is NOT drawn; the photo already shows it
_DISPLAYS = [
    ("TIME",     1842, 2217),
    ("SPEED",    2465, 2815),
    ("DISTANCE", 2978, 3370),
    ("CALORIES", 3800, 3960),
]

_LIT  = (215, 232, 255)   # bright LED blue-white
_GLOW = (90, 150, 255)    # soft bloom colour (blurred underlay)


# ── Asset helpers ─────────────────────────────────────────────────────────────

def _ensure_font(size: int) -> "ImageFont.FreeTypeFont":
    from PIL import ImageFont
    path = _ASSETS / "DSEG7Classic-Regular.ttf"
    if not path.exists():
        _ASSETS.mkdir(exist_ok=True)
        data = urllib.request.urlopen(_DSEG7_URL, timeout=30).read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if name.endswith("DSEG7Classic-Regular.ttf"):
                    path.write_bytes(zf.read(name))
                    break
    return ImageFont.truetype(str(path), size)


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_time(total_s: float) -> str:
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = int(total_s % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _erase_digits(img: "Image.Image") -> None:
    """Replace the existing LED digits with the clean background colour
    sampled from a reference row, stretched across the whole display band."""
    pad = 15
    by0, by1 = _DIGIT_Y0 - pad, _DIGIT_Y1 + pad
    strip = img.crop((_ERASE_X0, _REF_ROW, _ERASE_X1, _REF_ROW + 1)).resize(
        (_ERASE_X1 - _ERASE_X0, by1 - by0)
    )
    img.paste(strip, (_ERASE_X0, by0))


# ── Main render ───────────────────────────────────────────────────────────────

def render_display(
    trackpoints: list[dict],
    start_time: datetime,
    output_path: Path,
    total_kcal: float = 0.0,
) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    if not trackpoints:
        return
    if not _PHOTO.exists():
        raise FileNotFoundError(f"Console photo missing: {_PHOTO}")

    total_s  = (trackpoints[-1]["time"] - start_time).total_seconds()
    dist_km  = trackpoints[-1]["distance_m"] / 1000
    moving   = [tp["speed_ms"] for tp in trackpoints if tp.get("speed_ms", 0) > 0]
    avg_kmh  = sum(moving) / len(moving) * 3.6 if moving else 0.0

    values = [
        _fmt_time(total_s),
        f"{avg_kmh:.1f}",
        f"{dist_km:.2f}",
        f"{int(total_kcal)}",
    ]

    img = Image.open(_PHOTO).convert("RGB")
    _erase_digits(img)

    bg = img.crop(_CROP)
    bg = bg.resize((int(bg.width * _SCALE), int(bg.height * _SCALE)), Image.LANCZOS)

    cx0, cy0 = _CROP[0], _CROP[1]
    dy0 = (_DIGIT_Y0 - cy0) * _SCALE
    dy1 = (_DIGIT_Y1 - cy0) * _SCALE
    dh  = dy1 - dy0

    # One font size for all four displays — real LED digits are all the same
    # physical height, regardless of how many characters a field shows.
    # Size it so the longest value never grows into a neighbouring display.
    centers = [((x0 - cx0) * _SCALE + (x1 - cx0) * _SCALE) / 2 for _, x0, x1 in _DISPLAYS]
    budgets = []
    for i, cx in enumerate(centers):
        gaps = []
        if i > 0:
            gaps.append(cx - centers[i - 1])
        if i < len(centers) - 1:
            gaps.append(centers[i + 1] - cx)
        budgets.append(min(gaps) * 0.85)

    tmp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font_size = int(dh * 0.85)
    while font_size > 10:
        f = _ensure_font(font_size)
        widths = [tmp_draw.textbbox((0, 0), v, font=f)[2] for v in values]
        if all(w <= b for w, b in zip(widths, budgets)):
            break
        font_size -= 2
    font = _ensure_font(font_size)

    def centered_xy(draw, cx: float, value: str) -> tuple[float, float]:
        bb = draw.textbbox((0, 0), value, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        return cx - tw / 2 - bb[0], dy0 + (dh - th) / 2 - bb[1]

    # Soft glow underlay (blurred), then sharp digits on top
    glow_layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    glow_draw  = ImageDraw.Draw(glow_layer)
    for (_, x0, x1), value in zip(_DISPLAYS, values):
        cx = ((x0 - cx0) * _SCALE + (x1 - cx0) * _SCALE) / 2
        tx, ty = centered_xy(glow_draw, cx, value)
        glow_draw.text((tx, ty), value, font=font, fill=(*_GLOW, 255))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=max(3, int(dh * 0.07))))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow_layer).convert("RGB")

    draw = ImageDraw.Draw(bg)
    for (_, x0, x1), value in zip(_DISPLAYS, values):
        cx = ((x0 - cx0) * _SCALE + (x1 - cx0) * _SCALE) / 2
        tx, ty = centered_xy(draw, cx, value)
        draw.text((tx, ty), value, font=font, fill=_LIT)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.save(output_path)


# ── Integration helper ────────────────────────────────────────────────────────

def try_render_display(
    start_time: datetime,
    trackpoints: list[dict],
    fit_path: Path,
    cfg: dict,
) -> None:
    """Render display image if visualize is enabled; log result, never raise."""
    if not cfg.get("visualize"):
        return
    out = fit_path.with_name(fit_path.stem + "_display.png")
    total_kcal = sum(tp.get("kcal", 0.0) for tp in trackpoints)
    try:
        render_display(trackpoints, start_time, out, total_kcal)
        print(f"  Display: {out.name}")
    except Exception as e:
        print(f"  Display render failed: {e}")
