#!/usr/bin/env python3
"""Gamification stats — streaks, weekly goals, virtual journeys."""

from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

_BASE      = Path(__file__).resolve().parent
STATS_FILE = _BASE / "gamification_stats.json"
OUTPUT_DIR = _BASE / "activities"


def _parse_tcx(tcx_path: Path) -> tuple[float, float, int] | None:
    """Return (dist_km, duration_s, kcal) or None on parse failure."""
    try:
        ns  = {"g": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
        lap = ET.parse(tcx_path).getroot().find(".//g:Lap", ns)
        if lap is None:
            return None
        dist = float(lap.findtext("g:DistanceMeters", "0", ns)) / 1000
        dur  = float(lap.findtext("g:TotalTimeSeconds", "0", ns))
        kcal = int(float(lap.findtext("g:Calories", "0", ns)))
        return dist, dur, kcal
    except Exception:
        return None


def _save(stats: dict) -> None:
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def rebuild_from_activities() -> dict:
    """Scan all TCX files in activities/ and build stats from scratch."""
    sessions = []
    tcx_files = sorted(OUTPUT_DIR.glob("treadmill_*.tcx")) if OUTPUT_DIR.exists() else []
    for tcx_path in tcx_files:
        parts = tcx_path.stem.split("_")  # ["treadmill", "YYYYMMDD", "HHMMSS"]
        if len(parts) < 2 or len(parts[1]) != 8:
            continue
        d   = parts[1]
        day = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        data = _parse_tcx(tcx_path)
        if data:
            dist_km, duration_s, kcal = data
            sessions.append({"date": day, "dist_km": round(dist_km, 3),
                              "duration_s": round(duration_s, 1), "kcal": kcal})
    stats = {"sessions": sorted(sessions, key=lambda s: s["date"])}
    _save(stats)
    return stats


def load_stats() -> dict:
    if not STATS_FILE.exists():
        if OUTPUT_DIR.exists() and any(OUTPUT_DIR.glob("treadmill_*.tcx")):
            return rebuild_from_activities()
        return {"sessions": []}
    try:
        return json.loads(STATS_FILE.read_text())
    except Exception:
        return {"sessions": []}


def record_session(dist_km: float, duration_s: float, kcal: int) -> dict:
    """Append today's session and persist. Returns updated stats."""
    stats = load_stats()
    stats["sessions"].append({
        "date":       date.today().isoformat(),
        "dist_km":    round(dist_km, 3),
        "duration_s": round(duration_s, 1),
        "kcal":       kcal,
    })
    _save(stats)
    return stats


def get_streak(stats: dict) -> int:
    """Consecutive calendar weeks with at least one session.

    Grace: if the current week has no session yet it is not counted, but
    the streak is not broken either — last week is checked first.
    """
    active_weeks = {
        date.fromisoformat(s["date"]).isocalendar()[:2]
        for s in stats.get("sessions", [])
    }
    today   = date.today()
    monday  = today - timedelta(days=today.weekday())
    # Start from current week if active, otherwise from last week
    if today.isocalendar()[:2] not in active_weeks:
        monday -= timedelta(weeks=1)
    n = 0
    while monday.isocalendar()[:2] in active_weeks:
        n += 1
        monday -= timedelta(weeks=1)
    return n


def get_week_km(stats: dict, weeks_ago: int = 0) -> float:
    """Total km in the calendar week `weeks_ago` weeks before the current one."""
    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    start  = (monday - timedelta(weeks=weeks_ago)).isoformat()
    end    = (monday - timedelta(weeks=weeks_ago) + timedelta(days=6)).isoformat()
    return sum(s["dist_km"] for s in stats.get("sessions", []) if start <= s["date"] <= end)


def get_total_km(stats: dict) -> float:
    return sum(s["dist_km"] for s in stats.get("sessions", []))


def week_delta_pct(stats: dict) -> float | None:
    """Percentage change this week vs last week. None if last week was 0."""
    this_w = get_week_km(stats, 0)
    last_w = get_week_km(stats, 1)
    return None if last_w == 0 else (this_w - last_w) / last_w * 100


def journey_progress(stats: dict, cfg: dict) -> tuple[str, float, float] | None:
    """Returns (name, done_km, total_km) or None if not configured."""
    journey = cfg.get("gamification", {}).get("virtual_journey")
    if not journey:
        return None
    total = float(journey.get("total_km", 0))
    name  = journey.get("name", "Reise")
    if total <= 0:
        return None
    return name, min(get_total_km(stats), total), total


def progress_bar(done: float, total: float, width: int = 10) -> str:
    filled = round(done / total * width)
    return "█" * filled + "░" * (width - filled)


def notify(title: str, message: str) -> None:
    """macOS notification via osascript."""
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            check=False, timeout=5,
        )
    except Exception:
        pass


def check_milestones(stats: dict, new_dist_km: float) -> None:
    """Fire macOS notifications for streak and cumulative distance milestones."""
    streak = get_streak(stats)
    if streak in (2, 4, 8, 13, 26, 52):
        notify("🔥 Streak!", f"{streak} Wochen in Folge auf dem Laufband!")

    total = get_total_km(stats)
    prev  = total - new_dist_km
    for m in (10, 25, 50, 100, 200, 500, 1000):
        if prev < m <= total:
            notify("🏅 Meilenstein!", f"{m} km Gesamtdistanz erreicht!")
            break


if __name__ == "__main__":
    stats = rebuild_from_activities()
    sessions = stats.get("sessions", [])
    print(f"Rebuilt stats from {len(sessions)} sessions")
    print(f"Gesamtdistanz: {get_total_km(stats):.1f} km")
    print(f"Streak:        {get_streak(stats)} Wochen")
    print(f"Diese Woche:   {get_week_km(stats):.1f} km")
    print(f"Letzte Woche:  {get_week_km(stats, 1):.1f} km")
