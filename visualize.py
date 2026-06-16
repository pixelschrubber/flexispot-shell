#!/usr/bin/env python3
"""
Artistic polar / sunflower visualization of a treadmill session.

Each radial line = one trackpoint.
  Angle  = position in time (12 o'clock = start, clockwise)
  Length = speed (longer = faster)
  Color  = speed (plasma colormap: indigo → magenta → gold)

Requires: pip3 install --user --break-system-packages matplotlib
Enable:   add  "visualize": true  to config.json
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def render(start_time: datetime, trackpoints: list[dict], output_path: Path) -> None:
    """Render the sunflower poster to output_path (PNG)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import numpy as np
        from matplotlib.collections import LineCollection
    except ImportError:
        print("  Visualization skipped — pip3 install --user --break-system-packages matplotlib")
        return

    if not trackpoints:
        return

    total_s  = (trackpoints[-1]["time"] - start_time).total_seconds()
    speeds   = np.array([tp["speed_ms"] for tp in trackpoints])
    times_s  = np.array([(tp["time"] - start_time).total_seconds() for tp in trackpoints])

    max_speed = float(speeds.max()) or 1.0
    min_speed = float(speeds[speeds > 0].min()) if (speeds > 0).any() else 0.0

    # Angles: 12 o'clock = start, clockwise
    angles = -np.pi / 2 + 2 * np.pi * times_s / total_s
    # Radius: min speed → short petal, max speed → full-length petal
    radii  = np.where(speeds > 0, 0.18 + 0.82 * (speeds / max_speed), 0.0)

    cmap   = plt.cm.plasma
    norm   = mcolors.Normalize(vmin=0, vmax=max_speed)
    colors = cmap(norm(speeds))

    # ── Canvas ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw={"projection": "polar"},
                           facecolor="#07070e")
    ax.set_facecolor("#07070e")
    ax.set_axis_off()
    ax.set_ylim(0, 1.18)

    # ── Starburst petals with glow ────────────────────────────────────────────
    segs = [[[a, 0.0], [a, r]] for a, r in zip(angles.tolist(), radii.tolist())]

    for lw, alpha in [(16, 0.018), (8, 0.055), (4, 0.13), (1.6, 1.0)]:
        lc = LineCollection(segs, colors=colors, linewidths=lw,
                            alpha=alpha, capstyle="round")
        ax.add_collection(lc)

    # Glowing dots at petal tips
    mask = radii > 0.18
    ax.scatter(angles[mask], radii[mask], c=colors[mask], s=6,
               alpha=0.7, zorder=5, linewidths=0)

    # Subtle outer guide ring
    ring = np.linspace(0, 2 * np.pi, 360)
    ax.plot(ring, np.full_like(ring, 1.1), color="#ffffff0a", lw=0.5, zorder=1)

    # ── Stats in the centre ───────────────────────────────────────────────────
    dist_km    = trackpoints[-1]["distance_m"] / 1000
    total_kcal = int(sum(tp.get("kcal", 0.0) for tp in trackpoints))
    moving     = speeds[speeds > 0]
    avg_speed  = float(moving.mean()) if len(moving) else 0.0
    pace_s     = 1000 / avg_speed if avg_speed > 0 else 0
    pace_str   = f"{int(pace_s // 60)}:{int(pace_s % 60):02d}"
    dur_h      = int(total_s // 3600)
    dur_m      = int((total_s % 3600) // 60)
    dur_str    = f"{dur_h:02d}:{dur_m:02d}" if dur_h else f"{dur_m} min"
    date_str   = f"{start_time.day}. {start_time.strftime('%B %Y')}"

    kw = dict(ha="center", transform=fig.transFigure, fontfamily="monospace")
    fig.text(0.5, 0.578, f"{dist_km:.2f} km",  fontsize=26, color="#ffffff", weight="bold", **kw)
    fig.text(0.5, 0.537, dur_str,               fontsize=16, color="#ccccee", **kw)
    fig.text(0.5, 0.501, f"Ø {pace_str} /km",  fontsize=16, color="#ccccee", **kw)
    fig.text(0.5, 0.465, f"{total_kcal} kcal",  fontsize=16, color="#ccccee", **kw)
    fig.text(0.5, 0.413, date_str,               fontsize=11, color="#77778a", **kw)

    # ── Speed legend (slow → fast label) ─────────────────────────────────────
    slow_str = f"{int(min_speed * 3.6 * 10) / 10:.1f} km/h"
    fast_str = f"{int(max_speed * 3.6 * 10) / 10:.1f} km/h"
    fig.text(0.31, 0.07, f"◀ {slow_str}", fontsize=9, color="#666677",
             ha="center", transform=fig.transFigure, fontfamily="monospace")
    fig.text(0.69, 0.07, f"{fast_str} ▶", fontsize=9, color="#ffcc44",
             ha="center", transform=fig.transFigure, fontfamily="monospace")

    # Color gradient bar
    grad_ax = fig.add_axes([0.33, 0.055, 0.34, 0.012])
    grad_ax.imshow(np.linspace(0, 1, 256).reshape(1, -1), aspect="auto",
                   cmap=cmap, origin="lower")
    grad_ax.set_axis_off()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, facecolor=fig.get_facecolor(),
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def try_render(start_time: datetime, trackpoints: list[dict],
               fit_path: Path, cfg: dict) -> None:
    """Render poster if enabled in config; log result, never raise."""
    if not cfg.get("visualize"):
        return
    output_path = fit_path.with_suffix(".png")
    try:
        render(start_time, trackpoints, output_path)
        print(f"  Poster: {output_path.name}")
    except Exception as e:
        print(f"  Visualization failed: {e}")
