#!/usr/bin/env python3
"""
Background monitor — auto-detects treadmill start/stop via Shelly power draw
and saves a TCX file for each session without any manual interaction.

Run directly:  python3 monitor.py
As a service:  launchctl load ~/Library/LaunchAgents/net.flexispot.monitor.plist
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path

from treadmill import (
    OUTPUT_DIR,
    fmt_duration,
    get_power,
    kcal_for_interval,
    load_calibration,
    load_config,
    power_to_speed,
    save_activity,
)
from strava import try_upload

LOG_FILE = Path(__file__).parent / "monitor.log"

POLL_INTERVAL   = 5
START_THRESH_W  = 15.0
START_CONFIRM_S = 10
STOP_DELAY_S    = 60
MIN_SESSION_S   = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger(__name__)


class State(Enum):
    WAITING    = auto()
    CONFIRMING = auto()
    ACTIVE     = auto()
    STOPPING   = auto()


def save_session(start_time: datetime, trackpoints: list[dict], weight_kg: float, cfg: dict):
    duration   = (trackpoints[-1]["time"] - start_time).total_seconds()
    dist_km    = trackpoints[-1]["distance_m"] / 1000
    total_kcal = int(sum(tp.get("kcal", 0.0) for tp in trackpoints))

    if duration < MIN_SESSION_S:
        log.info(f"Session too short ({duration:.0f}s) — discarded")
        return

    tcx_path, fit_path = save_activity(start_time, trackpoints)

    avg_pace_min = duration / max(dist_km, 0.001) / 60
    pace_str     = f"{int(avg_pace_min)}:{int((avg_pace_min % 1) * 60):02d} min/km"

    log.info(
        f"Session saved: {fit_path.name} + {tcx_path.name}  |  "
        f"Time: {fmt_duration(duration)}  |  "
        f"Distance: {dist_km:.2f} km  |  "
        f"Avg pace: {pace_str}  |  "
        f"Calories: {total_kcal} kcal"
    )
    try_upload(fit_path, cfg)


def main():
    cfg       = load_config()
    shelly_ip = cfg["shelly_ip"]
    weight_kg = cfg.get("user_weight_kg", 75.0)
    cfg_ref   = cfg  # passed through to save_session for Strava

    log.info("Flexispot monitor started")
    idle_power, cal_points = load_calibration()
    log.info(
        f"Calibration: idle {idle_power:.1f}W, {len(cal_points)} steps, "
        f"start threshold: >{idle_power + START_THRESH_W:.1f}W"
    )

    state          = State.WAITING
    session_start: datetime | None = None
    trackpoints: list[dict] = []
    total_distance_m = 0.0
    confirm_since    = 0.0
    stop_since       = 0.0
    consecutive_errors = 0

    while True:
        try:
            power = get_power(shelly_ip)
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 3:
                log.warning(f"Shelly unreachable: {e}")
            elif consecutive_errors == 4:
                log.warning("Further Shelly errors suppressed...")
            time.sleep(POLL_INTERVAL)
            continue

        now    = datetime.now(timezone.utc)
        now_ts = time.monotonic()
        active = power > idle_power + START_THRESH_W

        if state == State.WAITING:
            if active:
                confirm_since = now_ts
                state = State.CONFIRMING
                log.info(f"Treadmill active ({power:.1f}W) — confirming for {START_CONFIRM_S}s")

        elif state == State.CONFIRMING:
            if not active:
                state = State.WAITING
                log.info(f"Signal too brief ({power:.1f}W) — back to waiting")
            elif now_ts - confirm_since >= START_CONFIRM_S:
                session_start    = now
                trackpoints      = []
                total_distance_m = 0.0
                state = State.ACTIVE
                log.info("Session started")

        elif state == State.ACTIVE:
            speed_kmh = power_to_speed(power, idle_power, cal_points)
            speed_ms  = speed_kmh / 3.6
            dt        = (now - trackpoints[-1]["time"]).total_seconds() if trackpoints else 0.0
            total_distance_m += speed_ms * dt
            interval_kcal     = kcal_for_interval(speed_kmh, dt, weight_kg)

            trackpoints.append({
                "time":       now,
                "distance_m": total_distance_m,
                "speed_ms":   speed_ms,
                "power_w":    power,
                "kcal":       interval_kcal,
            })

            elapsed = (now - session_start).total_seconds()
            if int(elapsed) % 60 < POLL_INTERVAL:
                running_kcal = int(sum(tp.get("kcal", 0.0) for tp in trackpoints))
                pace_min     = elapsed / max(total_distance_m / 1000, 0.001) / 60
                pace_str     = f"{int(pace_min)}:{int((pace_min % 1) * 60):02d} min/km"
                log.info(
                    f"  {fmt_duration(elapsed)}  {power:.1f}W  {speed_kmh:.1f} km/h  "
                    f"{total_distance_m/1000:.2f} km  {pace_str}  {running_kcal} kcal"
                )

            if not active:
                stop_since = now_ts
                state = State.STOPPING
                log.info(f"Power gone ({power:.1f}W) — waiting {STOP_DELAY_S}s before saving")

        elif state == State.STOPPING:
            if active:
                state = State.ACTIVE
                log.info(f"Treadmill resumed ({power:.1f}W) — session continues")
            elif now_ts - stop_since >= STOP_DELAY_S:
                log.info("Session ended")
                save_session(session_start, trackpoints, weight_kg, cfg)
                state            = State.WAITING
                session_start    = None
                trackpoints      = []
                total_distance_m = 0.0

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
