#!/usr/bin/env python3
"""
Manual treadmill tracker — run while walking, stop with Ctrl+C.
Reads power from Shelly Plug, derives speed via calibration table,
accumulates distance and saves a TCX file for Garmin Connect.
"""

import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from treadmill import (
    fmt_duration,
    get_power,
    kcal_for_interval,
    load_calibration,
    load_config,
    power_to_speed,
    save_activity,
)
from strava import try_upload
from garmin import try_upload as try_upload_garmin
from visualize import try_render
from heartrate import load_hr_monitor

POLL_INTERVAL = 5


def main():
    cfg        = load_config()
    shelly_ip  = cfg["shelly_ip"]
    weight_kg  = cfg.get("user_weight_kg", 75.0)
    hr_monitor = load_hr_monitor(cfg)

    idle_power, cal_points = load_calibration()

    print("=== Flexispot Treadmill Tracker ===")
    print(f"Calibration: {len(cal_points)} speed steps, idle: {idle_power:.1f}W")
    print("Stop with Ctrl+C — TCX file is saved automatically.\n")

    start_time         = datetime.now(timezone.utc)
    trackpoints: list[dict] = []
    total_distance_m   = 0.0
    consecutive_errors = 0

    def finish(signum=None, frame=None):
        print("\n\nSaving activity...")
        if not trackpoints:
            print("No data recorded.")
            sys.exit(0)

        tcx_path, fit_path = save_activity(start_time, trackpoints)

        elapsed      = (trackpoints[-1]["time"] - start_time).total_seconds()
        dist_km      = total_distance_m / 1000
        avg_pace_min = elapsed / max(dist_km, 0.001) / 60
        total_kcal   = int(sum(tp.get("kcal", 0.0) for tp in trackpoints))

        print(f"\nActivity saved:")
        print(f"  FIT: {fit_path}")
        print(f"  TCX: {tcx_path}")
        print(f"  Time:      {fmt_duration(elapsed)}")
        print(f"  Distance:  {dist_km:.2f} km")
        print(f"  Avg pace:  {int(avg_pace_min)}:{int((avg_pace_min % 1) * 60):02d} min/km")
        print(f"  Calories:  {total_kcal} kcal  (weight: {weight_kg:.0f} kg)")
        try_upload(fit_path, cfg)
        garmin_id = try_upload_garmin(fit_path, cfg, start_time)
        try_render(start_time, trackpoints, fit_path, cfg, garmin_id)
        sys.exit(0)

    signal.signal(signal.SIGINT, finish)
    signal.signal(signal.SIGTERM, finish)

    has_hr = hr_monitor is not None
    hr_col = f"  {'HR':>6}" if has_hr else ""
    print(f"{'Time':>10}  {'Power':>10}  {'Speed':>12}  {'Distance':>9}  {'Pace':<9}  {'Calories':>8}{hr_col}")
    print("-" * (72 + (9 if has_hr else 0)))

    while True:
        try:
            power = get_power(shelly_ip)
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 3:
                print(f"  Shelly unreachable: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        speed_kmh = power_to_speed(power, idle_power, cal_points)
        speed_ms  = speed_kmh / 3.6

        now     = datetime.now(timezone.utc)
        elapsed = (now - start_time).total_seconds()

        if trackpoints:
            dt = (now - trackpoints[-1]["time"]).total_seconds()
        else:
            dt = 0.0
        total_distance_m += speed_ms * dt
        interval_kcal     = kcal_for_interval(speed_kmh, dt, weight_kg)
        hr                = hr_monitor.get_hr() if hr_monitor else 0

        tp = {
            "time":       now,
            "distance_m": total_distance_m,
            "speed_ms":   speed_ms,
            "power_w":    power,
            "kcal":       interval_kcal,
        }
        if hr:
            tp["heart_rate"] = hr
        trackpoints.append(tp)

        pace_str = "–"
        if speed_kmh >= 0.5:
            pace_min = 60.0 / speed_kmh
            pace_str = f"{int(pace_min)}:{int((pace_min % 1) * 60):02d} /km"

        total_kcal = sum(tp.get("kcal", 0.0) for tp in trackpoints)
        hr_str     = f"  {hr:>4} bpm" if has_hr else ""
        print(
            f"\r{fmt_duration(elapsed):>10}  {power:>8.1f}W  {speed_kmh:>7.1f} km/h"
            f"  {total_distance_m/1000:>6.2f} km  {pace_str:<9}  {total_kcal:>5.0f} kcal{hr_str}",
            end="",
            flush=True,
        )

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
