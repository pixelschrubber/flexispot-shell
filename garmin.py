#!/usr/bin/env python3
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

import sys
from pathlib import Path

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


def upload_activity(filepath: Path, cfg: dict) -> None:
    client = _client(cfg)
    client.upload_activity(str(filepath))


def try_upload(filepath: Path, cfg: dict) -> None:
    """Upload to Garmin Connect if configured; log result, never raise."""
    if not cfg.get("garmin", {}).get("auto_upload"):
        return
    try:
        upload_activity(filepath, cfg)
        print(f"  Garmin: uploaded — {filepath.name}")
    except Exception as e:
        print(f"  Garmin upload failed: {e}")


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
        upload_activity(filepath, cfg)
        print(f"Uploaded {filepath.name} to Garmin Connect.")

    else:
        print("Usage: python3 garmin.py [setup | upload <file>]")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
