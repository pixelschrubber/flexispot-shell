#!/usr/bin/env python3
"""Shared physics and hardware helpers used by all Flexispot tracking scripts."""

import json
import urllib.request
from datetime import datetime
from pathlib import Path

_BASE            = Path(__file__).parent
CONFIG_FILE      = _BASE / "config.json"
CALIBRATION_FILE = _BASE / "calibration.json"
OUTPUT_DIR       = _BASE / "activities"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            "config.json not found — copy config.example.json and fill in your settings."
        )
    return json.loads(CONFIG_FILE.read_text())


def get_power(shelly_ip: str) -> float:
    url = f"http://{shelly_ip}/rpc/Switch.GetStatus?id=0"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())["apower"]


def load_calibration() -> tuple[float, list[tuple[float, float]]]:
    if not CALIBRATION_FILE.exists():
        return 10.0, [(2.0, 50.0), (3.0, 70.0), (4.0, 95.0), (5.0, 125.0)]
    cal    = json.loads(CALIBRATION_FILE.read_text())
    idle   = cal.get("idle_power", 0.0)
    points = [(float(s), float(p)) for s, p in cal["speeds"].items()]
    points.sort(key=lambda x: x[1])
    return idle, points


def power_to_speed(power: float, idle: float,
                   points: list[tuple[float, float]]) -> float:
    net = power - idle
    if net <= 0 or net <= points[0][1] - idle:
        return 0.0
    if net >= points[-1][1] - idle:
        if len(points) >= 2:
            s1, p1 = points[-2]
            s2, p2 = points[-1]
            return s2 + (s2 - s1) / max(p2 - p1, 0.1) * (net - (p2 - idle))
        return points[-1][0]
    for i in range(len(points) - 1):
        s1, p1 = points[i]
        s2, p2 = points[i + 1]
        n1, n2 = p1 - idle, p2 - idle
        if n1 <= net <= n2:
            return s1 + (net - n1) / max(n2 - n1, 0.1) * (s2 - s1)
    return 0.0


# MET values from Compendium of Physical Activities (Ainsworth et al.)
_MET_TABLE: list[tuple[float, float]] = [
    (0.0,  1.0), (1.0,  1.5), (2.0,  2.5), (3.0,  2.8), (4.0,  3.8),
    (5.0,  5.0), (6.0,  6.0), (8.0,  8.3), (10.0, 10.0), (12.0, 11.8),
]


def speed_to_met(speed_kmh: float) -> float:
    if speed_kmh <= 0:
        return 1.0
    if speed_kmh >= _MET_TABLE[-1][0]:
        return _MET_TABLE[-1][1]
    for i in range(len(_MET_TABLE) - 1):
        s1, m1 = _MET_TABLE[i]
        s2, m2 = _MET_TABLE[i + 1]
        if s1 <= speed_kmh <= s2:
            return m1 + (speed_kmh - s1) / (s2 - s1) * (m2 - m1)
    return 1.0


def kcal_for_interval(speed_kmh: float, dt_seconds: float, weight_kg: float) -> float:
    return speed_to_met(speed_kmh) * weight_kg * (dt_seconds / 3600.0)


def speed_to_cadence(speed_kmh: float) -> int:
    """Estimated walking cadence in strides/min (= steps/min ÷ 2).
    Linear model from walking biomechanics literature; ±10% accuracy."""
    if speed_kmh <= 0:
        return 0
    steps_per_min = 87.0 + 4.8 * speed_kmh
    return max(0, int(steps_per_min / 2))


def load_start_threshold(cfg: dict, idle_power: float,
                         points: list[tuple[float, float]]) -> float:
    """Watts above idle that trigger session detection.

    Uses config value if set; otherwise auto-derives as 60% of the net power
    at the slowest calibrated speed — ensuring even the first speed step
    is reliably detected regardless of treadmill model.
    """
    if "start_threshold_w" in cfg:
        return float(cfg["start_threshold_w"])
    if not points:
        return 10.0
    min_net = points[0][1] - idle_power
    return max(5.0, min_net * 0.6)


def fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_tcx(start_time: datetime, trackpoints: list[dict], output_path: Path) -> None:
    """Write a Garmin Connect / Strava-compatible TCX file.

    Trackpoint dicts need: time (datetime), distance_m (float),
    speed_ms (float), kcal (float), power_w (float, optional).
    """
    total_dist = trackpoints[-1]["distance_m"] if trackpoints else 0.0
    total_time = (
        (trackpoints[-1]["time"] - start_time).total_seconds() if trackpoints else 0.0
    )
    max_speed  = max((tp["speed_ms"] for tp in trackpoints), default=0.0)
    total_kcal = int(sum(tp.get("kcal", 0.0) for tp in trackpoints))

    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _tp_xml(tp: dict) -> str:
        spd_ms = tp["speed_ms"]
        pwr    = tp.get("power_w", 0.0)
        cad    = speed_to_cadence(spd_ms * 3.6)
        ext = f"<ns3:Speed>{spd_ms:.3f}</ns3:Speed>"
        if pwr > 0:
            ext += f"<ns3:Watts>{int(pwr)}</ns3:Watts>"
        if cad > 0:
            ext += f"<ns3:RunCadence>{cad}</ns3:RunCadence>"
        return (
            f"      <Trackpoint>\n"
            f"        <Time>{fmt(tp['time'])}</Time>\n"
            f"        <DistanceMeters>{tp['distance_m']:.1f}</DistanceMeters>\n"
            f"        <Extensions><ns3:TPX>{ext}</ns3:TPX></Extensions>\n"
            f"      </Trackpoint>\n"
        )

    tps_xml = "".join(_tp_xml(tp) for tp in trackpoints)

    tcx = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TrainingCenterDatabase\n'
        '  xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"\n'
        '  xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2"\n'
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        '  <Activities>\n'
        '    <Activity Sport="Running">\n'
        f'      <Id>{fmt(start_time)}</Id>\n'
        f'      <Lap StartTime="{fmt(start_time)}">\n'
        f'        <TotalTimeSeconds>{total_time:.0f}</TotalTimeSeconds>\n'
        f'        <DistanceMeters>{total_dist:.1f}</DistanceMeters>\n'
        f'        <MaximumSpeed>{max_speed:.3f}</MaximumSpeed>\n'
        f'        <Calories>{total_kcal}</Calories>\n'
        '        <Intensity>Active</Intensity>\n'
        '        <TriggerMethod>Manual</TriggerMethod>\n'
        '        <Track>\n'
        f'{tps_xml}'
        '        </Track>\n'
        '      </Lap>\n'
        '      <Notes>Flexispot Treadmill (Shelly-tracked)</Notes>\n'
        '    </Activity>\n'
        '  </Activities>\n'
        '</TrainingCenterDatabase>\n'
    )
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path.write_text(tcx)


def write_fit(start_time: datetime, trackpoints: list[dict], output_path: Path) -> None:
    """Write a FIT activity file (delegates to fit_writer)."""
    from fit_writer import write_fit as _write_fit
    OUTPUT_DIR.mkdir(exist_ok=True)
    _write_fit(start_time, trackpoints, output_path)


def save_activity(start_time: datetime, trackpoints: list[dict]) -> tuple[Path, Path]:
    """Save both TCX and FIT to activities/. Returns (tcx_path, fit_path)."""
    stem    = start_time.strftime("treadmill_%Y%m%d_%H%M%S")
    tcx_out = OUTPUT_DIR / f"{stem}.tcx"
    fit_out = OUTPUT_DIR / f"{stem}.fit"
    write_tcx(start_time, trackpoints, tcx_out)
    write_fit(start_time, trackpoints, fit_out)
    return tcx_out, fit_out
