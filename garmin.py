#!/usr/bin/env python3
from __future__ import annotations

"""
Garmin Connect login and activity upload.

Garmin has no public upload API for personal projects, so this uses the same
SSO login flow as the Garmin Connect app/website, via the unofficial
`garminconnect` package (pip install garminconnect).

One-time setup (caches the session so future uploads need no password):
    python3 garmin.py setup

Upload a file manually:
    python3 garmin.py upload activities/treadmill_20250611_123000.fit
"""

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_TOKEN_STORE = Path(__file__).parent / "garmin_tokens"


def _client(cfg: dict):
    try:
        import garminconnect
    except ImportError as e:
        raise RuntimeError(
            "garminconnect package not installed. Run: "
            "pip3 install --user --break-system-packages garminconnect"
        ) from e

    garmin_cfg = cfg.get("garmin", {})
    client = garminconnect.Garmin(
        email=garmin_cfg.get("email"),
        password=garmin_cfg.get("password"),
    )
    client.login(tokenstore=str(_TOKEN_STORE))
    return client


def setup(cfg: dict) -> None:
    """Log in once and cache session tokens under garmin_tokens/."""
    _client(cfg)
    print(f"Garmin login successful. Session cached in {_TOKEN_STORE}")


def upload_activity(filepath: Path, cfg: dict, start_time: datetime | None = None) -> int | None:
    """Upload FIT file to Garmin Connect. Returns the activity ID if start_time is given."""
    client = _client(cfg)
    client.upload_activity(str(filepath))

    if start_time is None:
        return None

    # Garmin processes uploads asynchronously; wait briefly then resolve activity ID
    time.sleep(4)
    target_ms = int(start_time.timestamp() * 1000)
    for act in client.get_activities(0, 5):
        begin_ms = act.get("beginTimestamp", 0)
        if abs(begin_ms - target_ms) < 300_000:  # within 5 minutes
            return act.get("activityId")
    return None


def link_gear(activity_id: int, cfg: dict) -> None:
    """Link the configured gear UUID to a Garmin Connect activity."""
    gear_uuid = cfg.get("garmin", {}).get("gear_uuid", "").strip()
    if not gear_uuid:
        return
    client = _client(cfg)
    client.add_gear_to_activity(gear_uuid, activity_id)


def attach_image(activity_id: int, image_path: Path, cfg: dict) -> None:
    """Attach a JPEG image to an existing Garmin Connect activity."""
    from PIL import Image
    import io

    client = _client(cfg)
    img = Image.open(image_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    img_bytes = buf.getvalue()

    boundary = "FlexiSpotPosterBoundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="file"; filename="poster.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
    ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()

    client.client.post(
        "connectapi",
        f"/activity-service/activity/{activity_id}/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def try_upload(filepath: Path, cfg: dict, start_time: datetime | None = None) -> int | None:
    """Upload to Garmin Connect if configured; return activity ID, never raise."""
    if not cfg.get("garmin", {}).get("auto_upload"):
        return None
    try:
        activity_id = upload_activity(filepath, cfg, start_time)
        log.info("Garmin: uploaded — %s%s", filepath.name,
                 f" (id {activity_id})" if activity_id else "")
        if activity_id:
            link_gear(activity_id, cfg)
        return activity_id
    except Exception as e:
        log.error("Garmin upload failed: %s", e)
        return None


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    from treadmill import load_config  # imported here to avoid circular dep at module level

    if len(sys.argv) < 2 or sys.argv[1] == "setup":
        cfg = load_config()
        setup(cfg)

    elif sys.argv[1] == "upload":
        if len(sys.argv) < 3:
            print("Usage: python3 garmin.py upload <file.fit>")
            sys.exit(1)
        cfg      = load_config()
        filepath = Path(sys.argv[2])
        activity_id = upload_activity(filepath, cfg)
        print(f"Uploaded {filepath.name} to Garmin Connect."
              + (f" Activity ID: {activity_id}" if activity_id else ""))

    else:
        print("Usage: python3 garmin.py [setup | upload <file>]")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
