#!/usr/bin/env python3
"""
Floating macOS widget — auto-detects treadmill sessions via Shelly power draw
and shows a live HUD (time, speed, distance, calories). Saves TCX on stop.

Run: python3 widget.py
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from enum import Enum, auto

from treadmill import (
    OUTPUT_DIR,
    fmt_duration,
    get_power,
    kcal_for_interval,
    load_calibration,
    load_config,
    power_to_speed,
    write_tcx,
)

POLL_INTERVAL   = 5
START_THRESH_W  = 15.0
START_CONFIRM_S = 10
STOP_DELAY_S    = 60
MIN_SESSION_S   = 60

# Apple-style dark palette
C_BG     = "#1c1c1e"
C_BAR    = "#2c2c2e"
C_BORDER = "#3a3a3c"
C_GREEN  = "#30d158"
C_ORANGE = "#ff9f0a"
C_RED    = "#ff453a"
C_WHITE  = "#f2f2f7"
C_GRAY   = "#8e8e93"
C_DIM    = "#3a3a3c"

W, H = 290, 268


class State(Enum):
    WAITING    = auto()
    CONFIRMING = auto()
    ACTIVE     = auto()
    STOPPING   = auto()


class TreadmillWidget:

    def __init__(self):
        cfg              = load_config()
        self._shelly_ip  = cfg["shelly_ip"]
        self._weight_kg  = cfg.get("user_weight_kg", 75.0)
        self.idle_power, self.cal_pts = load_calibration()

        self._lock          = threading.Lock()
        self._state         = State.WAITING
        self._session_start: datetime | None = None
        self._dist_km       = 0.0
        self._speed_kmh     = 0.0
        self._kcal          = 0.0
        self._pace_str      = "–"
        self._saved_fname   = ""
        self._trackpoints   = []
        self._btn_visible   = False

        self._build_window()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._tick()

    # ── Window ────────────────────────────────────────────────────────────────

    def _build_window(self):
        r = tk.Tk()
        self.root = r
        r.title("Flexispot")
        r.geometry(f"{W}x{H}+80+80")
        r.resizable(False, False)
        r.configure(bg=C_BG)
        r.wm_attributes("-topmost", True)
        r.wm_attributes("-alpha", 0.96)
        r.overrideredirect(True)
        r.update()

        r.bind("<ButtonPress-1>", lambda e: setattr(r, "_dx", e.x) or setattr(r, "_dy", e.y))
        r.bind("<B1-Motion>",     lambda e: r.geometry(
            f"+{r.winfo_x() + e.x - r._dx}+{r.winfo_y() + e.y - r._dy}"))

        self._build_ui()

    def _build_ui(self):
        r = self.root

        bar = tk.Frame(r, bg=C_BAR, height=38)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        bar.bind("<ButtonPress-1>", lambda e: setattr(r, "_dx", e.x) or setattr(r, "_dy", e.y))
        bar.bind("<B1-Motion>",     lambda e: r.geometry(
            f"+{r.winfo_x() + e.x - r._dx}+{r.winfo_y() + e.y - r._dy}"))

        self._dot = tk.Label(bar, text="●", font=("Helvetica Neue", 9),
                             fg=C_DIM, bg=C_BAR)
        self._dot.pack(side="left", padx=(12, 5))

        tk.Label(bar, text="FLEXISPOT", font=("Helvetica Neue", 10, "bold"),
                 fg=C_GRAY, bg=C_BAR).pack(side="left")

        tk.Button(bar, text="✕", font=("Helvetica Neue", 12),
                  fg=C_GRAY, bg=C_BAR, bd=0, highlightthickness=0,
                  activeforeground=C_RED, activebackground=C_BAR,
                  cursor="hand2", command=r.destroy).pack(side="right", padx=12)

        self._status_lbl = tk.Label(r, text="WAITING",
                                    font=("Helvetica Neue", 10),
                                    fg=C_GRAY, bg=C_BG)
        self._status_lbl.pack(pady=(12, 0))

        self._time_lbl = tk.Label(r, text="--:--:--",
                                  font=("Helvetica Neue", 52, "bold"),
                                  fg=C_DIM, bg=C_BG)
        self._time_lbl.pack(pady=(0, 8))

        tk.Frame(r, bg=C_BORDER, height=1).pack(fill="x", padx=20)

        row = tk.Frame(r, bg=C_BG)
        row.pack(fill="x", padx=0, pady=10)

        left = tk.Frame(row, bg=C_BG)
        left.pack(side="left", expand=True)
        tk.Label(left, text="SPEED", font=("Helvetica Neue", 8),
                 fg=C_GRAY, bg=C_BG).pack()
        self._speed_lbl = tk.Label(left, text="–",
                                   font=("Helvetica Neue", 22, "bold"),
                                   fg=C_DIM, bg=C_BG)
        self._speed_lbl.pack()
        tk.Label(left, text="km/h", font=("Helvetica Neue", 9),
                 fg=C_GRAY, bg=C_BG).pack()

        tk.Frame(row, bg=C_BORDER, width=1).pack(side="left", fill="y", pady=4)

        right = tk.Frame(row, bg=C_BG)
        right.pack(side="left", expand=True)
        tk.Label(right, text="DISTANCE", font=("Helvetica Neue", 8),
                 fg=C_GRAY, bg=C_BG).pack()
        self._dist_lbl = tk.Label(right, text="–",
                                  font=("Helvetica Neue", 22, "bold"),
                                  fg=C_DIM, bg=C_BG)
        self._dist_lbl.pack()
        tk.Label(right, text="km", font=("Helvetica Neue", 9),
                 fg=C_GRAY, bg=C_BG).pack()

        tk.Frame(r, bg=C_BORDER, height=1).pack(fill="x", padx=20)

        kcal_frame = tk.Frame(r, bg=C_BG)
        kcal_frame.pack(pady=10)
        tk.Label(kcal_frame, text="CALORIES", font=("Helvetica Neue", 8),
                 fg=C_GRAY, bg=C_BG).pack()
        self._kcal_lbl = tk.Label(kcal_frame, text="–",
                                  font=("Helvetica Neue", 28, "bold"),
                                  fg=C_DIM, bg=C_BG)
        self._kcal_lbl.pack()
        tk.Label(kcal_frame, text="kcal", font=("Helvetica Neue", 9),
                 fg=C_GRAY, bg=C_BG).pack()

        bot = tk.Frame(r, bg=C_BG)
        bot.pack(fill="x", padx=20, pady=(0, 14))

        self._pace_lbl = tk.Label(bot, text="– min/km",
                                  font=("Helvetica Neue", 10),
                                  fg=C_GRAY, bg=C_BG)
        self._pace_lbl.pack(side="left")

        self._save_btn = tk.Button(bot, text="Save",
                                   font=("Helvetica Neue", 9),
                                   fg=C_BG, bg=C_GREEN, bd=0, padx=8, pady=3,
                                   activebackground="#27b84a", activeforeground=C_BG,
                                   cursor="hand2", command=self._manual_save)

    # ── Background polling thread ─────────────────────────────────────────────

    def _poll_loop(self):
        state         = State.WAITING
        confirm_since = stop_since = 0.0
        session_start = None
        trackpoints   = []
        total_dist    = total_kcal = 0.0
        errors        = 0

        while True:
            try:
                power  = get_power(self._shelly_ip)
                errors = 0
            except Exception:
                errors += 1
                time.sleep(POLL_INTERVAL)
                continue

            now    = datetime.now(timezone.utc)
            now_m  = time.monotonic()
            active = power > self.idle_power + START_THRESH_W

            if state == State.WAITING:
                if active:
                    confirm_since = now_m
                    state = State.CONFIRMING

            elif state == State.CONFIRMING:
                if not active:
                    state = State.WAITING
                elif now_m - confirm_since >= START_CONFIRM_S:
                    session_start = now
                    trackpoints   = []
                    total_dist = total_kcal = 0.0
                    state = State.ACTIVE
                    with self._lock:
                        self._state         = State.ACTIVE
                        self._session_start = session_start

            elif state == State.ACTIVE:
                speed_kmh = power_to_speed(power, self.idle_power, self.cal_pts)
                speed_ms  = speed_kmh / 3.6
                dt        = (now - trackpoints[-1]["time"]).total_seconds() if trackpoints else 0.0
                total_dist  += speed_ms * dt
                ikc          = kcal_for_interval(speed_kmh, dt, self._weight_kg)
                total_kcal  += ikc
                trackpoints.append({
                    "time":       now,
                    "distance_m": total_dist,
                    "speed_ms":   speed_ms,
                    "kcal":       ikc,
                })

                pace_str = "–"
                if speed_kmh >= 0.5:
                    pm = 60.0 / speed_kmh
                    pace_str = f"{int(pm)}:{int((pm % 1) * 60):02d} min/km"

                with self._lock:
                    self._state         = State.ACTIVE
                    self._session_start = session_start
                    self._dist_km       = total_dist / 1000
                    self._speed_kmh     = speed_kmh
                    self._kcal          = total_kcal
                    self._pace_str      = pace_str
                    self._trackpoints   = list(trackpoints)

                if not active:
                    stop_since = now_m
                    state = State.STOPPING
                    with self._lock:
                        self._state = State.STOPPING

            elif state == State.STOPPING:
                if active:
                    state = State.ACTIVE
                    with self._lock:
                        self._state = State.ACTIVE
                elif now_m - stop_since >= STOP_DELAY_S:
                    fname = self._save_tcx(session_start, trackpoints)
                    with self._lock:
                        self._state         = State.WAITING
                        self._session_start = None
                        self._saved_fname   = fname or ""
                    state         = State.WAITING
                    session_start = None
                    trackpoints   = []
                    total_dist = total_kcal = 0.0

            time.sleep(POLL_INTERVAL)

    def _save_tcx(self, start: datetime, trackpoints: list[dict]) -> str | None:
        if not trackpoints:
            return None
        fname    = start.strftime("treadmill_%Y%m%d_%H%M%S.tcx")
        out_path = OUTPUT_DIR / fname
        write_tcx(start, trackpoints, out_path)
        return fname

    # ── Manual save button ────────────────────────────────────────────────────

    def _manual_save(self):
        with self._lock:
            pts   = list(self._trackpoints)
            start = self._session_start
            self._state         = State.WAITING
            self._session_start = None
        if pts and start:
            fname = self._save_tcx(start, pts)
            with self._lock:
                self._saved_fname = fname or ""

    # ── GUI tick (every second) ───────────────────────────────────────────────

    def _tick(self):
        with self._lock:
            state   = self._state
            start   = self._session_start
            dist_km = self._dist_km
            speed   = self._speed_kmh
            kcal    = self._kcal
            pace    = self._pace_str
            saved   = self._saved_fname
            if saved:
                self._saved_fname = ""

        elapsed = (datetime.now(timezone.utc) - start).total_seconds() if start else None

        if state == State.ACTIVE:
            self._dot.config(fg=C_GREEN)
            self._status_lbl.config(text="ACTIVE", fg=C_GREEN)
            self._time_lbl.config(
                text=fmt_duration(elapsed) if elapsed else "--:--:--", fg=C_GREEN)
            self._speed_lbl.config(text=f"{speed:.1f}", fg=C_WHITE)
            self._dist_lbl.config(text=f"{dist_km:.2f}", fg=C_WHITE)
            self._kcal_lbl.config(text=f"{int(kcal)}", fg=C_ORANGE)
            self._pace_lbl.config(text=pace, fg=C_GRAY)
            self._show_btn(True)

        elif state == State.STOPPING:
            self._dot.config(fg=C_ORANGE)
            self._status_lbl.config(text="STOPPING...", fg=C_ORANGE)
            self._time_lbl.config(
                text=fmt_duration(elapsed) if elapsed else "--:--:--", fg=C_ORANGE)
            self._speed_lbl.config(text=f"{speed:.1f}", fg=C_WHITE)
            self._dist_lbl.config(text=f"{dist_km:.2f}", fg=C_WHITE)
            self._kcal_lbl.config(text=f"{int(kcal)}", fg=C_ORANGE)
            self._pace_lbl.config(text=pace, fg=C_GRAY)
            self._show_btn(True)

        elif state == State.CONFIRMING:
            self._dot.config(fg=C_ORANGE)
            self._status_lbl.config(text="DETECTING...", fg=C_ORANGE)

        else:  # WAITING
            self._dot.config(fg=C_DIM)
            self._show_btn(False)
            if saved:
                self._status_lbl.config(text=f"✓  {saved}", fg=C_GREEN)
                self._time_lbl.config(text="--:--:--", fg=C_DIM)
                self._speed_lbl.config(text="–", fg=C_DIM)
                self._dist_lbl.config(text="–", fg=C_DIM)
                self._kcal_lbl.config(text="–", fg=C_DIM)
                self._pace_lbl.config(text="– min/km", fg=C_GRAY)
                self.root.after(4000,
                    lambda: self._status_lbl.config(text="WAITING", fg=C_GRAY))
            else:
                self._status_lbl.config(text="WAITING", fg=C_GRAY)

        self.root.after(1000, self._tick)

    def _show_btn(self, show: bool):
        if show and not self._btn_visible:
            self._save_btn.pack(side="right")
            self._btn_visible = True
        elif not show and self._btn_visible:
            self._save_btn.pack_forget()
            self._btn_visible = False

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    TreadmillWidget().run()
