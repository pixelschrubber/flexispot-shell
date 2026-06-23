#!/usr/bin/env python3
"""
Strava OAuth setup and activity upload — no external dependencies.

One-time setup:
    python3 strava.py setup

Upload a file manually:
    python3 strava.py upload activities/treadmill_20250611_123000.fit
"""

import http.server
import json
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

_TOKENS_FILE    = Path(__file__).parent / "strava_tokens.json"
_AUTH_URL       = "https://www.strava.com/oauth/authorize"
_TOKEN_URL      = "https://www.strava.com/api/v3/oauth/token"
_UPLOAD_URL     = "https://www.strava.com/api/v3/uploads"
_UPLOAD_STATUS  = "https://www.strava.com/api/v3/uploads/{}"
_ACTIVITY_URL   = "https://www.strava.com/api/v3/activities/{}"
_REDIRECT_URI   = "http://localhost:8765/callback"
_SCOPE          = "activity:write"


# ── OAuth ─────────────────────────────────────────────────────────────────────

def setup(client_id: str, client_secret: str) -> None:
    """Open browser for OAuth, catch redirect, save tokens."""
    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  _REDIRECT_URI,
        "response_type": "code",
        "scope":         _SCOPE,
        "approval_prompt": "auto",
    })
    print(f"Opening browser for Strava authorization...")
    webbrowser.open(f"{_AUTH_URL}?{params}")
    print("Waiting for redirect on http://localhost:8765 ...")

    code = None

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal code
            parsed = urllib.parse.urlparse(self.path)
            qs     = urllib.parse.parse_qs(parsed.query)
            code   = qs.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h2>Authorization successful! You can close this tab.</h2>"
            )
        def log_message(self, *_):
            pass

    with http.server.HTTPServer(("localhost", 8765), _Handler) as srv:
        srv.handle_request()

    if not code:
        raise RuntimeError("No authorization code received from Strava.")

    tokens = _exchange(client_id, client_secret, code, "authorization_code")
    _save_tokens(tokens)
    print(f"Tokens saved to {_TOKENS_FILE}")
    print("Strava setup complete.")


def _exchange(client_id: str, client_secret: str, code_or_token: str, grant_type: str) -> dict:
    data = urllib.parse.urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        grant_type == "authorization_code" and "code" or "refresh_token": code_or_token,
        "grant_type":    grant_type,
    }).encode()
    req = urllib.request.Request(_TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _save_tokens(tokens: dict) -> None:
    _TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def _get_access_token(cfg: dict) -> str:
    if not _TOKENS_FILE.exists():
        raise RuntimeError(
            "Not authenticated with Strava. Run:  python3 strava.py setup"
        )
    tokens    = json.loads(_TOKENS_FILE.read_text())
    client_id = str(cfg["strava"]["client_id"])
    secret    = cfg["strava"]["client_secret"]

    if tokens.get("expires_at", 0) <= time.time() + 60:
        tokens = _exchange(client_id, secret, tokens["refresh_token"], "refresh_token")
        _save_tokens(tokens)

    return tokens["access_token"]


# ── Upload ────────────────────────────────────────────────────────────────────

def _api(token: str, url: str, method: str = "GET", data: bytes | None = None,
         headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def upload_activity(filepath: Path, cfg: dict, name: str = "",
                    description: str = "") -> dict:
    """Upload a .fit or .tcx file to Strava. Returns the upload response dict."""
    token     = _get_access_token(cfg)
    suffix    = filepath.suffix.lower()
    data_type = "fit" if suffix == ".fit" else "tcx"
    activity_name = name or filepath.stem.replace("_", " ").title()

    boundary  = "FlexiSpotUploadBoundary"
    file_data = filepath.read_bytes()

    def _field(fname: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{fname}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    body = (
        _field("data_type",    data_type)
        + _field("name",       activity_name)
        + _field("sport_type", "Walk")
        + _field("trainer",    "1")
        + (_field("description", description) if description else b"")
        + (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filepath.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + file_data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    result = _api(token, _UPLOAD_URL, method="POST", data=body,
                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    gear_id = cfg.get("strava", {}).get("gear_id", "").strip()
    if gear_id:
        activity_id = _wait_for_activity(token, result.get("id"))
        if activity_id:
            result["activity_id"] = activity_id
            _set_gear(token, activity_id, gear_id)

    return result


def _wait_for_activity(token: str, upload_id: int | None, retries: int = 10) -> int | None:
    """Poll the upload status endpoint until Strava assigns an activity ID."""
    if not upload_id:
        return None
    for _ in range(retries):
        time.sleep(3)
        status = _api(token, _UPLOAD_STATUS.format(upload_id))
        if status.get("activity_id"):
            return status["activity_id"]
        if status.get("error"):
            return None
    return None


def _set_gear(token: str, activity_id: int, gear_id: str) -> None:
    """Attach a gear item to an existing Strava activity."""
    data = urllib.parse.urlencode({"gear_id": gear_id}).encode()
    _api(token, _ACTIVITY_URL.format(activity_id), method="PUT",
         headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data)


def try_upload(filepath: Path, cfg: dict, name: str = "",
               description: str = "") -> None:
    """Upload to Strava if configured; log result, never raise."""
    if not cfg.get("strava", {}).get("auto_upload"):
        return
    try:
        result = upload_activity(filepath, cfg, name, description)
        status = result.get("status", "")
        act_id = result.get("activity_id") or result.get("id")
        print(f"  Strava: uploaded — {status}  (id {act_id})")
    except Exception as e:
        print(f"  Strava upload failed: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    from treadmill import load_config  # imported here to avoid circular dep at module level

    if len(sys.argv) < 2 or sys.argv[1] == "setup":
        cfg = load_config()
        strava_cfg = cfg.get("strava", {})
        client_id  = strava_cfg.get("client_id") or input("Strava Client ID: ").strip()
        secret     = strava_cfg.get("client_secret") or input("Strava Client Secret: ").strip()
        setup(str(client_id), secret)

    elif sys.argv[1] == "upload":
        if len(sys.argv) < 3:
            print("Usage: python3 strava.py upload <file.fit|file.tcx>")
            sys.exit(1)
        cfg      = load_config()
        filepath = Path(sys.argv[2])
        result   = upload_activity(filepath, cfg)
        print(json.dumps(result, indent=2))

    else:
        print("Usage: python3 strava.py [setup | upload <file>]")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
