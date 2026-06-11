#!/usr/bin/env python3
"""
One-time calibration: measures power draw at each treadmill speed step
and saves a power→speed lookup table to calibration.json.
"""

import json
import time
from pathlib import Path

from treadmill import CALIBRATION_FILE, load_config, get_power

MEASURE_SECONDS = 90


def measure_average_power(shelly_ip: str, duration: int) -> float:
    samples = []
    end = time.time() + duration
    while time.time() < end:
        try:
            p = get_power(shelly_ip)
            samples.append(p)
            remaining = int(end - time.time())
            print(f"\r  Measuring... {remaining:3d}s left  |  current: {p:.1f}W  ",
                  end="", flush=True)
        except Exception as e:
            print(f"\n  Warning: {e}")
        time.sleep(2)
    avg = sum(samples) / len(samples) if samples else 0.0
    print(f"\r  Average: {avg:.1f}W over {len(samples)} samples          ")
    return avg


def main():
    cfg = load_config()
    shelly_ip = cfg["shelly_ip"]

    print("=== Flexispot Treadmill Calibration ===\n")
    print("For each speed step:")
    print("  1. Set the desired speed")
    print("  2. Walk for 30s to stabilise the belt")
    print("  3. Press Enter — the script measures for 90 seconds\n")

    calibration: dict[str, float] = {}

    input("Start the treadmill WITHOUT standing on it, then press Enter for idle measurement... ")
    idle_power = measure_average_power(shelly_ip, 30)
    print(f"  Idle power: {idle_power:.1f}W\n")

    while True:
        speed_str = input("Treadmill speed in km/h (or Enter to finish): ").strip()
        if not speed_str:
            break
        try:
            speed = float(speed_str.replace(",", "."))
        except ValueError:
            print("  Invalid input — enter a number (e.g. 3.5)")
            continue

        input(f"  Set {speed} km/h, walk for 30s, then press Enter... ")
        avg_power = measure_average_power(shelly_ip, MEASURE_SECONDS)
        net_power = max(0.0, avg_power - idle_power)
        calibration[str(speed)] = round(avg_power, 1)
        print(f"  → {speed} km/h = {avg_power:.1f}W (net: {net_power:.1f}W)\n")

    if not calibration:
        print("No calibration data — aborting.")
        return

    sorted_cal = dict(sorted(calibration.items(), key=lambda x: float(x[0])))
    output = {
        "idle_power": round(idle_power, 1),
        "speeds": sorted_cal,
        "shelly_ip": shelly_ip,
    }
    CALIBRATION_FILE.write_text(json.dumps(output, indent=2))
    print(f"\nCalibration saved to {CALIBRATION_FILE}")
    print("\nSpeed table:")
    for spd, pwr in sorted_cal.items():
        print(f"  {float(spd):.1f} km/h → {pwr:.1f}W")


if __name__ == "__main__":
    main()
