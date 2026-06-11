#!/usr/bin/env python3
"""
Minimal FIT file writer — no external dependencies.
Produces files accepted by Garmin Connect and Strava.

FIT spec: https://developer.garmin.com/fit/protocol/
"""

import struct
from datetime import datetime
from pathlib import Path

# FIT timestamps are seconds since 1989-12-31T00:00:00Z
_FIT_EPOCH = 631065600

# ── CRC-16/CCITT ──────────────────────────────────────────────────────────────

_CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
]

def _crc(data: bytes, seed: int = 0) -> int:
    crc = seed
    for b in data:
        tmp = _CRC_TABLE[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _CRC_TABLE[b & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _CRC_TABLE[(b >> 4) & 0xF]
    return crc

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(dt: datetime) -> int:
    return max(0, int(dt.timestamp()) - _FIT_EPOCH)

# FIT base type bytes
_ENUM = 0x00   # 1 byte (used for enum fields)
_U8   = 0x02   # 1 byte unsigned
_U16  = 0x84   # 2 bytes unsigned LE
_U32  = 0x86   # 4 bytes unsigned LE

def _def(local: int, global_num: int, fields: list) -> bytes:
    """Build a definition message. fields = [(field_num, byte_size, base_type), ...]"""
    hdr = struct.pack('<BBBHB', 0x40 | (local & 0xF), 0, 0, global_num, len(fields))
    return hdr + b''.join(struct.pack('<BBB', fn, fs, ft) for fn, fs, ft in fields)

def _dat(local: int, fmt: str, *values) -> bytes:
    """Build a data message."""
    return struct.pack('<B' + fmt, local & 0xF, *values)

# ── Local message type assignments ────────────────────────────────────────────
_LM_FILE_ID  = 0
_LM_EVENT    = 1
_LM_RECORD   = 2
_LM_SESSION  = 3
_LM_ACTIVITY = 4

# ── Public API ────────────────────────────────────────────────────────────────

def write_fit(start_time: datetime, trackpoints: list, output_path: Path) -> None:
    """Write a Garmin Connect / Strava-compatible FIT activity file.

    Trackpoint dicts need: time (datetime), distance_m (float),
    speed_ms (float), power_w (float, optional), kcal (float, optional).
    """
    if not trackpoints:
        return

    ts0      = _ts(start_time)
    ts_last  = _ts(trackpoints[-1]["time"])
    dur_ms   = int((trackpoints[-1]["time"] - start_time).total_seconds() * 1000)
    dist_cm  = int(trackpoints[-1]["distance_m"] * 100)
    kcal     = min(0xFFFF, int(sum(tp.get("kcal", 0.0) for tp in trackpoints)))
    powers   = [tp.get("power_w", 0.0) for tp in trackpoints if tp.get("power_w", 0.0) > 0]
    avg_pwr  = min(0xFFFF, int(sum(powers) / len(powers))) if powers else 0
    max_pwr  = min(0xFFFF, int(max(powers))) if powers else 0

    buf = bytearray()

    # ── file_id (global 0) ────────────────────────────────────────────────────
    # type=4 (activity), manufacturer=255 (development), time_created
    buf += _def(_LM_FILE_ID, 0, [(0, 1, _ENUM), (1, 2, _U16), (4, 4, _U32)])
    buf += _dat(_LM_FILE_ID, "BHI", 4, 255, ts0)

    # ── event definition (global 21): timestamp, event, event_type ───────────
    buf += _def(_LM_EVENT, 21, [(253, 4, _U32), (0, 1, _ENUM), (1, 1, _ENUM)])

    # event: timer start  (event=0=timer, event_type=0=start)
    buf += _dat(_LM_EVENT, "IBB", ts0, 0, 0)

    # ── record definition (global 20) ─────────────────────────────────────────
    # timestamp, distance (cm, ×100), speed (mm/s, ×1000), power (W), cadence (strides/min)
    buf += _def(_LM_RECORD, 20, [
        (253, 4, _U32),
        (5,   4, _U32),
        (6,   2, _U16),
        (7,   2, _U16),
        (53,  1, _U8),   # cadence: strides/min
    ])

    for tp in trackpoints:
        speed_kmh = tp["speed_ms"] * 3.6
        cadence   = int(max(0, (87.0 + 4.8 * speed_kmh) / 2)) if speed_kmh > 0 else 0
        buf += _dat(_LM_RECORD, "IIHHB",
            _ts(tp["time"]),
            int(tp["distance_m"] * 100),
            min(0xFFFF, int(tp["speed_ms"] * 1000)),
            min(0xFFFF, int(tp.get("power_w", 0.0))),
            min(0xFF, cadence),
        )

    # event: timer stop  (event_type=4=stop_all)
    buf += _dat(_LM_EVENT, "IBB", ts_last, 0, 4)

    # ── session (global 18) ───────────────────────────────────────────────────
    # Fields: timestamp, start_time, total_elapsed_time(ms), total_timer_time(ms),
    #         total_distance(cm), total_calories, first_lap_index, num_laps,
    #         avg_power, max_power, event, event_type, sport, sub_sport
    buf += _def(_LM_SESSION, 18, [
        (253, 4, _U32),   # timestamp
        (2,   4, _U32),   # start_time
        (7,   4, _U32),   # total_elapsed_time
        (8,   4, _U32),   # total_timer_time
        (9,   4, _U32),   # total_distance
        (11,  2, _U16),   # total_calories
        (25,  2, _U16),   # first_lap_index
        (26,  2, _U16),   # num_laps
        (20,  2, _U16),   # avg_power
        (21,  2, _U16),   # max_power
        (0,   1, _ENUM),  # event (0=timer)
        (1,   1, _ENUM),  # event_type (1=stop)
        (29,  1, _ENUM),  # sport (11=walking)
        (30,  1, _ENUM),  # sub_sport (0=generic)
    ])
    buf += _dat(_LM_SESSION, "IIIIIHHHHHBBBB",
        ts_last, ts0,
        dur_ms, dur_ms,
        dist_cm,
        kcal,
        0, 1,          # first_lap_index, num_laps
        avg_pwr, max_pwr,
        0, 1,          # event=timer, event_type=stop
        11, 0,         # sport=walking, sub_sport=generic
    )

    # ── activity (global 34) ──────────────────────────────────────────────────
    # timestamp, total_timer_time(ms), num_sessions, type, event, event_type
    buf += _def(_LM_ACTIVITY, 34, [
        (253, 4, _U32),  # timestamp
        (0,   4, _U32),  # total_timer_time
        (1,   2, _U16),  # num_sessions
        (2,   1, _ENUM), # type (0=manual)
        (3,   1, _ENUM), # event (26=activity)
        (4,   1, _ENUM), # event_type (1=stop)
    ])
    buf += _dat(_LM_ACTIVITY, "IIHBBB", ts_last, dur_ms, 1, 0, 26, 1)

    # ── Assemble file ─────────────────────────────────────────────────────────
    data      = bytes(buf)
    hdr_body  = struct.pack("<BBH", 14, 0x10, 2132) + struct.pack("<I", len(data)) + b".FIT"
    header    = hdr_body + struct.pack("<H", _crc(hdr_body))
    file_crc  = struct.pack("<H", _crc(data))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + data + file_crc)
