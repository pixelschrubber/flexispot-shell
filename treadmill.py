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


def fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_tcx(start_time: datetime, trackpoints: list[dict], output_path: Path) -> None:
    """Write a Garmin Connect-compatible TCX file.

    Each dict in trackpoints needs: time (datetime), distance_m (float),
    speed_ms (float), kcal (float).
    """
    total_dist = trackpoints[-1]["distance_m"] if trackpoints else 0.0
    total_time = (
        (trackpoints[-1]["time"] - start_time).total_seconds() if trackpoints else 0.0
    )
    max_speed  = max((tp["speed_ms"] for tp in trackpoints), default=0.0)
    total_kcal = int(sum(tp.get("kcal", 0.0) for tp in trackpoints))

    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    tps_xml = "".join(
        f"      <Trackpoint>\n"
        f"        <Time>{fmt(tp['time'])}</Time>\n"
        f"        <DistanceMeters>{tp['distance_m']:.1f}</DistanceMeters>\n"
        f"        <Extensions><ns3:TPX>"
        f"<ns3:Speed>{tp['speed_ms']:.3f}</ns3:Speed>"
        f"</ns3:TPX></Extensions>\n"
        f"      </Trackpoint>\n"
        for tp in trackpoints
    )

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
