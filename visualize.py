#!/usr/bin/env python3
"""
Artistic sunflower / starburst visualization of a treadmill session.

  Angle  = position in time (12 o'clock = start, clockwise)
  Length = speed at that moment (longer = faster)
  Color  = plasma colormap (indigo = slow → magenta → gold = fast)
  Background = radial gradient (dark indigo centre → dark teal edges)

Requires: pip3 install --user --break-system-packages matplotlib
Enable:   "visualize": true  in config.json
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def render(start_time: datetime, trackpoints: list[dict], output_path: Path) -> None:
    """Render and save the poster PNG. Raises ImportError if matplotlib is missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import numpy as np
        from matplotlib.collections import LineCollection
    except ImportError:
        raise ImportError(
            "matplotlib not installed — "
            "pip3 install --user --break-system-packages matplotlib"
        )

    if not trackpoints:
        return

    total_s  = (trackpoints[-1]["time"] - start_time).total_seconds()
    speeds   = np.array([tp["speed_ms"] for tp in trackpoints])
    times_s  = np.array([(tp["time"] - start_time).total_seconds() for tp in trackpoints])

    max_speed = float(speeds.max()) or 1.0

    # 12 o'clock = start, clockwise → angle = -π/2 + 2π·(t/total)
    angles = -np.pi / 2 + 2 * np.pi * times_s / total_s
    radii  = np.where(speeds > 0, 0.18 + 0.82 * speeds / max_speed, 0.0)

    cmap   = plt.cm.plasma
    norm   = mcolors.Normalize(vmin=0, vmax=max_speed)
    colors = cmap(norm(speeds))

    # Cartesian petal endpoints
    xs = radii * np.cos(angles)
    ys = radii * np.sin(angles)

    # ── Canvas ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 10), facecolor="#000000")
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_xlim(-1.18, 1.18)
    ax.set_ylim(-1.18, 1.18)

    # ── Radial gradient background ─────────────────────────────────────────────
    size = 1000
    Y, X = np.mgrid[-1.2:1.2:size * 1j, -1.2:1.2:size * 1j]
    R = np.clip(np.sqrt(X ** 2 + Y ** 2) / 1.2, 0, 1)

    # Centre: dark indigo (#070514)  →  Edge: dark teal-navy (#061522)
    r_ch = np.interp(R, [0, 1], [0.027, 0.024])
    g_ch = np.interp(R, [0, 1], [0.020, 0.083])
    b_ch = np.interp(R, [0, 1], [0.078, 0.133])
    bg = np.stack([r_ch, g_ch, b_ch], axis=-1)

    ax.imshow(bg, extent=[-1.2, 1.2, -1.2, 1.2], aspect="auto",
              origin="lower", zorder=0, interpolation="bilinear")

    # ── Starburst petals with glow layers ─────────────────────────────────────
    segs = [[[0.0, 0.0], [x, y]] for x, y in zip(xs.tolist(), ys.tolist())]

    for lw, alpha in [(18, 0.015), (9, 0.05), (4.5, 0.12), (1.8, 1.0)]:
        lc = LineCollection(segs, colors=colors, linewidths=lw,
                            alpha=alpha, capstyle="round", zorder=1)
        ax.add_collection(lc)

    # Glowing dots at petal tips
    mask = radii > 0.18
    ax.scatter(xs[mask], ys[mask], c=colors[mask], s=7,
               alpha=0.65, zorder=2, linewidths=0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, facecolor="black",
                bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def try_render(
    start_time: datetime,
    trackpoints: list[dict],
    fit_path: Path,
    cfg: dict,
    garmin_activity_id: int | None = None,
) -> None:
    """Render poster and optionally attach it to the Garmin Connect activity."""
    if not cfg.get("visualize"):
        return

    png_path = fit_path.with_suffix(".png")
    try:
        render(start_time, trackpoints, png_path)
        print(f"  Poster: {png_path.name}")
    except ImportError as e:
        print(f"  Visualization skipped: {e}")
        return
    except Exception as e:
        print(f"  Visualization failed: {e}")
        return

    if garmin_activity_id is None:
        return
    try:
        from garmin import attach_image
        attach_image(garmin_activity_id, png_path, cfg)
        print(f"  Garmin: poster attached to activity {garmin_activity_id}")
    except Exception as e:
        print(f"  Garmin poster upload failed: {e}")
