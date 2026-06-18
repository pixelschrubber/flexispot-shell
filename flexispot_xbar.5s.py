#!/usr/bin/env python3
# <xbar.title>Flexispot Treadmill</xbar.title>
# <xbar.version>1.0</xbar.version>
# <xbar.author>Ulf Mayer</xbar.author>
# <xbar.desc>Live treadmill stats via Shelly Plug in the macOS menu bar</xbar.desc>
# <xbar.aboutURL>https://harder-better-faster-stronger.de/?flexispot</xbar.aboutURL>
# <xbar.refreshTime>5s</xbar.refreshTime>
#
# Setup:
#   1. Install xbar: https://xbarapp.com
#   2. Place this file and all other project files in the xbar plugin folder
#      (xbar menu → "Open Plugin Folder")
#   3. Restart xbar

import sys
from pathlib import Path

# Allow importing treadmill.py from the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import subprocess
import time
from treadmill import (
    get_power,
    load_calibration,
    load_config,
    load_start_threshold,
    power_to_speed,
    speed_to_met,
    fmt_duration,
    OUTPUT_DIR,
)

STATE_FILE     = Path(__file__).resolve().parent / "session_state.json"

_dark = subprocess.run(
    ["defaults", "read", "-g", "AppleInterfaceStyle"],
    capture_output=True, text=True
).returncode == 0
FG = "#ffffff" if _dark else "#000000"
STOP_DELAY_S  = 60
MIN_SESSION_S = 60


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"status": "idle", "start_ts": None, "dist_m": 0.0,
            "kcal": 0.0, "last_ts": None, "stop_ts": None}


def save_state(s: dict):
    STATE_FILE.write_text(json.dumps(s))


def clear_state() -> dict:
    s = {"status": "idle", "start_ts": None, "dist_m": 0.0,
         "kcal": 0.0, "last_ts": None, "stop_ts": None}
    save_state(s)
    return s


def pace_str(speed_kmh: float) -> str:
    if speed_kmh < 0.5:
        return "–"
    pm = 60.0 / speed_kmh
    return f"{int(pm)}:{int((pm % 1) * 60):02d} /km"


def main():
    cfg        = load_config()
    shelly_ip  = cfg["shelly_ip"]
    weight_kg  = cfg.get("user_weight_kg", 75.0)
    idle_power, cal_pts = load_calibration()
    start_thresh = load_start_threshold(cfg, idle_power, cal_pts)

    now   = time.time()
    state = load_state()

    try:
        power     = get_power(shelly_ip)
        shelly_ok = True
    except Exception:
        shelly_ok = False
        power     = 0.0

    active    = shelly_ok and power > idle_power + start_thresh
    speed_kmh = power_to_speed(power, idle_power, cal_pts) if active else 0.0
    speed_ms  = speed_kmh / 3.6
    status    = state.get("status", "idle")

    if status == "idle":
        if active:
            state = {"status": "active", "start_ts": now, "dist_m": 0.0,
                     "kcal": 0.0, "last_ts": now, "stop_ts": None}

    elif status == "active":
        last_ts = state.get("last_ts") or now
        dt      = now - last_ts
        state["dist_m"] += speed_ms * dt
        state["kcal"]   += speed_to_met(speed_kmh) * weight_kg * (dt / 3600.0)
        state["last_ts"] = now
        if not active:
            state["status"]  = "stopping"
            state["stop_ts"] = now

    elif status == "stopping":
        last_ts = state.get("last_ts") or now
        dt      = now - last_ts
        state["last_ts"] = now
        if active:
            state["status"]  = "active"
            state["stop_ts"] = None
            state["dist_m"] += speed_ms * dt
            state["kcal"]   += speed_to_met(speed_kmh) * weight_kg * (dt / 3600.0)
        elif now - (state.get("stop_ts") or now) >= STOP_DELAY_S:
            state = clear_state()

    save_state(state)

    # ── xbar output ──────────────────────────────────────────────────────────

    if not shelly_ok:
        print("🏃 –")
        print("---")
        print("Shelly unreachable | color=#b30000")
        return

    if status in ("active", "stopping"):
        start_ts = state.get("start_ts") or now
        elapsed  = now - start_ts
        dist_km  = state.get("dist_m", 0.0) / 1000
        kcal     = state.get("kcal", 0.0)
        indicator = "🟢" if status == "active" else "🟠"

        speed_str = f"{speed_kmh:.1f} km/h" if speed_kmh >= 0.1 else "–"
        print(f"{indicator} {speed_str}")
        print("---")
        print(f"🕐 Time:      {fmt_duration(elapsed)} | color={FG}")
        print(f"🏃 Speed:     {speed_kmh:.1f} km/h  ({power:.0f}W) | color={FG}")
        print(f"📏 Distance:  {dist_km:.2f} km | color={FG}")
        print(f"🔥 Calories:  {int(kcal)} kcal | color={FG}")
        print(f"⏱ Pace:      {pace_str(speed_kmh)} | color={FG}")
        if status == "stopping":
            remain = max(0, STOP_DELAY_S - (now - (state.get("stop_ts") or now)))
            print(f"⏳ Ends in:   {int(remain)}s | color=#c06000")

        try:
            import stats as st
            gstats = st.load_stats()
            streak = st.get_streak(gstats)
            if streak > 0:
                tag = "Tag" if streak == 1 else "Tage"
                print("---")
                print(f"🔥 Streak: {streak} {tag} | color={FG}")
        except Exception:
            pass
    else:
        print("🏃 ready")
        print("---")
        print(f"Power: {power:.1f}W  (idle: {idle_power:.1f}W) | color={FG}")
        print(f"Threshold: >{idle_power + start_thresh:.1f}W to start | color={FG}")

        # ── Gamification ─────────────────────────────────────────────────────
        try:
            import stats as st
            gstats   = st.load_stats()
            streak   = st.get_streak(gstats)
            week_km  = st.get_week_km(gstats)
            delta    = st.week_delta_pct(gstats)
            goal_km  = cfg.get("gamification", {}).get("weekly_goal_km")

            print("---")

            if streak > 0:
                tag = "Tag" if streak == 1 else "Tage"
                print(f"🔥 Streak: {streak} {tag} | color={FG}")

            if goal_km:
                week_line = f"📅 Diese Woche: {week_km:.1f} / {goal_km} km"
            else:
                week_line = f"📅 Diese Woche: {week_km:.1f} km"
            if delta is not None:
                sign  = "↑" if delta >= 0 else "↓"
                color = "#1a7a1a" if delta >= 0 else "#b30000"
                print(f"{week_line}  {sign}{abs(delta):.0f}% | color={color}")
            else:
                print(f"{week_line} | color={FG}")

            journey = st.journey_progress(gstats, cfg)
            if journey:
                name, done, total = journey
                bar = st.progress_bar(done, total)
                pct = done / total * 100
                print(f"🗺️ {name}: {done:.0f} / {total:.0f} km  {bar}  {pct:.0f}% | color=#0044cc")
        except Exception:
            pass
        # ─────────────────────────────────────────────────────────────────────

        print("---")
        activities = sorted(OUTPUT_DIR.glob("*.tcx")) if OUTPUT_DIR.exists() else []
        if activities:
            print(f"Last session: {activities[-1].name} | color={FG}")



if __name__ == "__main__":
    main()
