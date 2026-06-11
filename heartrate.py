#!/usr/bin/env python3
"""
BLE heart rate monitor — reads from any ANT+/BLE HR device (Polar, Wahoo, Garmin, etc.)

Requires:  pip install bleak

Usage:
    python3 heartrate.py scan              # find nearby HR devices
    python3 heartrate.py read <name>       # stream live values for testing
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time

HR_SERVICE_UUID = "0000180d-0000-1000-8000-00805f9b34fb"
HR_CHAR_UUID    = "00002a37-0000-1000-8000-00805f9b34fb"
SCAN_TIMEOUT    = 15.0
RECONNECT_DELAY = 5.0


def _parse_hr(data: bytearray) -> int:
    """Decode HR Measurement characteristic value (Bluetooth spec Vol 3, Part G)."""
    flags = data[0]
    if flags & 0x01:          # 16-bit HR value
        return int.from_bytes(data[1:3], "little")
    return data[1]            # 8-bit HR value


async def _find_device(name_or_addr: str):
    from bleak import BleakScanner
    target = name_or_addr.strip()
    # On macOS, BLE addresses are UUIDs; on Linux they're MACs — handle both
    is_addr = len(target) in (17, 36) and ("-" in target or ":" in target)
    if is_addr:
        return await BleakScanner.find_device_by_address(target, timeout=SCAN_TIMEOUT)
    return await BleakScanner.find_device_by_name(target, timeout=SCAN_TIMEOUT)


class HRMonitor:
    """Thread-safe BLE heart rate reader.

    Runs an asyncio event loop in a daemon thread. Call start(), then
    get_hr() from any thread at any time. Reconnects automatically on dropout.
    """

    def __init__(self, device: str):
        """device: device name (partial match OK) or BLE address/UUID."""
        self._device   = device
        self._hr       = 0
        self._lock     = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread   = threading.Thread(
            target=self._run, daemon=True, name="hr-monitor"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()

    def get_hr(self) -> int:
        with self._lock:
            return self._hr

    # ── internal ──────────────────────────────────────────────────────────────

    def _set(self, hr: int) -> None:
        with self._lock:
            self._hr = hr

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while not self._stop_evt.is_set():
            try:
                loop.run_until_complete(self._session())
            except Exception as e:
                print(f"\n  HR: lost connection ({e}) — retrying in {RECONNECT_DELAY:.0f}s",
                      flush=True)
                self._set(0)
                time.sleep(RECONNECT_DELAY)

    async def _session(self) -> None:
        from bleak import BleakClient

        print(f"  HR: searching for '{self._device}'...", flush=True)
        device = await _find_device(self._device)
        if device is None:
            raise RuntimeError(f"'{self._device}' not found — is it awake?")

        print(f"  HR: connecting to {device.name} ({device.address})", flush=True)

        async with BleakClient(device, timeout=10.0) as client:
            print("  HR: connected ✓", flush=True)

            def _on_data(_, data: bytearray) -> None:
                self._set(_parse_hr(data))

            await client.start_notify(HR_CHAR_UUID, _on_data)

            while not self._stop_evt.is_set() and client.is_connected:
                await asyncio.sleep(1.0)

        self._set(0)


# ── Public helper ─────────────────────────────────────────────────────────────

def load_hr_monitor(cfg: dict) -> HRMonitor | None:
    """Return a started HRMonitor if hr_device is set in config, else None."""
    device = cfg.get("hr_device", "").strip()
    if not device:
        return None
    try:
        import bleak  # noqa: F401
    except ImportError:
        print("  HR: bleak not installed — run:  pip install bleak")
        return None
    mon = HRMonitor(device)
    mon.start()
    return mon


# ── CLI ───────────────────────────────────────────────────────────────────────

async def _scan() -> None:
    from bleak import BleakScanner
    print("Scanning for BLE heart rate devices (10 s) ...")
    devices = await BleakScanner.discover(
        timeout=10.0,
        service_uuids=[HR_SERVICE_UUID],
    )
    if not devices:
        print("No HR devices found. Make sure the device is awake / worn.")
        return
    print(f"\nFound {len(devices)} device(s):\n")
    for d in devices:
        name = d.name or "Unknown"
        print(f'  {name}  ({d.address})')
        print(f'  → add to config.json:  "hr_device": "{name}"')
        print()


async def _read(device: str) -> None:
    mon = HRMonitor(device)
    mon.start()
    print("Streaming HR — Ctrl+C to stop\n")
    try:
        while True:
            hr = mon.get_hr()
            print(f"\r  {hr if hr else '--':>3} bpm", end="", flush=True)
            await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        print()
    finally:
        mon.stop()


if __name__ == "__main__":
    try:
        import bleak  # noqa: F401
    except ImportError:
        print("bleak is required:  pip install bleak")
        sys.exit(1)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        asyncio.run(_scan())
    elif cmd == "read":
        if len(sys.argv) < 3:
            print("Usage: python3 heartrate.py read <device-name-or-address>")
            sys.exit(1)
        asyncio.run(_read(sys.argv[2]))
    else:
        print("Usage: python3 heartrate.py [scan | read <device>]")
        sys.exit(1)
