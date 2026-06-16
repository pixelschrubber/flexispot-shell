#!/usr/bin/env python3
"""
Treadmill console display image — session stats overlaid on the device photo.

Renders TIME / SPEED / DISTANCE in DSEG7 (7-segment LCD font) on top of a
cropped photo of the Flexispot console, matching the look of the real display.

Requires: Pillow (already installed via garminconnect deps)
Enable:   "visualize": true in config.json (same flag as the poster)

On first run, two files are downloaded into assets/:
  - The console background image from the Flexispot product page
  - DSEG7 font (keshikan, SIL OFL) from GitHub releases
"""

from __future__ import annotations

import io
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"

_CONSOLE_URL = (
    "https://s3.springbeetle.eu/prod-de2-s3/trantor/attachments/DE/GP018-20241107-specImg.png"
)
_DSEG7_URL = (
    "https://github.com/keshikan/DSEG/releases/download/v0.46/fonts-DSEG_v046.zip"
)

# Console crop (original 800×800 product image)
# The display panel starts around x=440; include some bezel on each side
_CROP     = (415, 153, 560, 233)   # (left, top, right, bottom)
_SCALE    = 6                       # upscale factor

# Display windows in original 800×800 image coords
_DISP_Y0, _DISP_Y1 = 172, 210
_DISPLAYS = [
    ("TIME",     460, 481),
    ("SPEED",    490, 517),
    ("DISTANCE", 521, 547),
]

# Colors
_BG      = (18, 18, 18)       # display window fill
_GHOST   = (38, 38, 35)       # unlit segment colour
_LIT     = (228, 230, 210)    # active segment colour
_LABEL   = (110, 110, 100)    # label text


# ── Asset helpers ─────────────────────────────────────────────────────────────

def _ensure_console() -> "Image.Image":
    from PIL import Image
    cache = _ASSETS / "console_bg.png"
    if not cache.exists():
        _ASSETS.mkdir(exist_ok=True)
        data = urllib.request.urlopen(_CONSOLE_URL, timeout=20).read()
        cache.write_bytes(data)
    return Image.open(cache).convert("RGBA")


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


def _label_font(size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    from PIL import ImageFont
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_time(total_s: float) -> str:
    h  = int(total_s // 3600)
    m  = int((total_s % 3600) // 60)
    s  = int(total_s % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _ghost(value: str) -> str:
    """Replace each digit/dot/colon with its 'all-segments' ghost equivalent."""
    mapping = {"0": "8", "1": "8", "2": "8", "3": "8", "4": "8",
               "5": "8", "6": "8", "7": "8", "8": "8", "9": "8",
               ".": ".", ":": ":", " ": " "}
    return "".join(mapping.get(c, c) for c in value)


# ── Main render ───────────────────────────────────────────────────────────────

def render_display(trackpoints: list[dict], start_time: datetime, output_path: Path) -> None:
    """Render session stats onto the console background and save PNG."""
    from PIL import Image, ImageDraw

    if not trackpoints:
        return

    total_s   = (trackpoints[-1]["time"] - start_time).total_seconds()
    dist_km   = trackpoints[-1]["distance_m"] / 1000
    moving    = [tp["speed_ms"] for tp in trackpoints if tp.get("speed_ms", 0) > 0]
    avg_kmh   = sum(moving) / len(moving) * 3.6 if moving else 0.0

    values = [_fmt_time(total_s), f"{avg_kmh:.1f}", f"{dist_km:.2f}"]

    # ── Background ───────────────────────────────────────────────────────────
    bg = _ensure_console().crop(_CROP).resize(
        ((_CROP[2] - _CROP[0]) * _SCALE, (_CROP[3] - _CROP[1]) * _SCALE),
        Image.LANCZOS,
    )
    draw = ImageDraw.Draw(bg)

    # ── Font sizing: fit to display window height ─────────────────────────────
    cx0, cy0 = _CROP[0], _CROP[1]
    dy0 = (_DISP_Y0 - cy0) * _SCALE
    dy1 = (_DISP_Y1 - cy0) * _SCALE
    dh  = dy1 - dy0

    font_size = int(dh * 0.80)
    font      = _ensure_font(font_size)
    lbl_font  = _label_font(max(10, int(font_size * 0.20)))

    # Auto-shrink font so the widest value fits in its box
    for (_, x0, x1), value in zip(_DISPLAYS, values):
        box_w = (x1 - x0) * _SCALE
        bb    = draw.textbbox((0, 0), value, font=font)
        while (bb[2] - bb[0]) > box_w * 0.92 and font_size > 10:
            font_size -= 2
            font     = _ensure_font(font_size)
            lbl_font = _label_font(max(10, int(font_size * 0.20)))
            bb       = draw.textbbox((0, 0), value, font=font)

    # ── Draw each display window ──────────────────────────────────────────────
    for (label, x0, x1), value in zip(_DISPLAYS, values):
        sx0 = (x0 - cx0) * _SCALE
        sx1 = (x1 - cx0) * _SCALE
        cx  = (sx0 + sx1) // 2

        # Fill display background (slightly wider than the pixel cluster)
        pad = int(dh * 0.12)
        draw.rectangle([sx0 - pad, dy0 - pad, sx1 + pad, dy1 + pad], fill=_BG)

        def _draw_centered(text: str, color: tuple) -> None:
            bb = draw.textbbox((0, 0), text, font=font)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            tx = cx - tw // 2 - bb[0]
            ty = dy0 + (dh - th) // 2 - bb[1]
            draw.text((tx, ty), text, font=font, fill=color)

        _draw_centered(_ghost(value), _GHOST)   # unlit ghost segments
        _draw_centered(value,         _LIT)     # active segments

        # Label below
        bb = draw.textbbox((0, 0), label, font=lbl_font)
        lw = bb[2] - bb[0]
        draw.text((cx - lw // 2, dy1 + pad + 2), label, font=lbl_font, fill=_LABEL)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path)


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
    try:
        render_display(trackpoints, start_time, out)
        print(f"  Display: {out.name}")
    except Exception as e:
        print(f"  Display render failed: {e}")
