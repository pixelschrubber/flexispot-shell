# Flexispot Treadmill Tracker

Track walking-desk sessions with a [Shelly Plug](https://www.shelly.com/en/products/shop/shelly-plug-s) and sync them to Garmin Connect, Strava, and Apple Health — zero subscription, zero wearable required.

## The problem

A Garmin watch measures treadmill distance via wrist acceleration. When you're typing at a standing desk, your arms stay still → the watch records **0 km**.

## The solution

The Shelly Plug measures the treadmill's power draw in real time. Because each speed setting has a characteristic wattage, the script infers speed and accumulates distance — no GPS, no footpod.

```
Shelly Plug (W)  →  calibration table  →  speed (km/h)  →  distance + cadence + calories
                                                                  ↓               ↓
                                                            FIT file          TCX file
                                                              ↓                  ↓
                                                  Strava + Garmin Connect   (broad compatibility)
                                                       (both auto-upload)
                                                              ↓
                                                        Apple Health (via Strava sync)
```

---

## Hardware

| Item | Notes |
|---|---|
| [Shelly Plug M Gen3](https://www.shelly.com/) | Any Gen3 Shelly with power metering works |
| Flexispot treadmill | Or any treadmill — the calibration adapts to it |
| Mac on the same Wi-Fi | Scripts talk directly to the Shelly local HTTP API — no cloud |

---

## Setup

**No pip install needed** for core tracking and Strava — only Python 3.9+ stdlib. Garmin auto-upload needs one extra package (see [Garmin Connect](#garmin-connect-automatic) below).

### 1. Clone and configure

```bash
git clone https://github.com/pixelschrubber/flexispot-shell.git
cd flexispot-shell
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "shelly_ip": "192.168.1.xxx",
  "user_weight_kg": 75.0,
  "user_age": 35
}
```

Find the Shelly IP in the Shelly app or your router's device list.

### 2. Calibrate (once)

```bash
python3 calibrate.py
```

The script walks you through measuring power draw at each speed step (~5 min per level). Result is saved in `calibration.json`. The detection threshold for session start is **automatically derived** from this file, so even the slowest speed step is reliably detected.

**Tip:** Re-run calibration if you change belt tension or after a few weeks of use.

### 3. Track a session

Choose any of the four tracking modes:

| Mode | Command | Best for |
|---|---|---|
| **Terminal** | `python3 track.py` | Manual start/stop, clean live table |
| **Widget** | `python3 widget.py` | Floating HUD while working |
| **Background** | `python3 monitor.py` | Fully automatic, runs as a macOS service |
| **xbar** | See below | Menu bar indicator |

Every session saves **two files** to `activities/`:
- `treadmill_YYYYMMDD_HHMMSS.fit` — native FIT format (preferred for Strava and Garmin)
- `treadmill_YYYYMMDD_HHMMSS.tcx` — XML format (broad compatibility)

Both include speed, distance, estimated cadence, calories, and treadmill power per trackpoint.

### 4. Export destinations

#### Strava (automatic)

Set up once, then every session uploads automatically:

```bash
python3 strava.py setup
```

This opens a browser for OAuth authorization. Tokens are saved locally in `strava_tokens.json` (gitignored) and refreshed automatically.

Add the Strava section to `config.json` to enable auto-upload:

```json
{
  "shelly_ip": "192.168.1.xxx",
  "user_weight_kg": 75.0,
  "user_age": 35,
  "strava": {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "auto_upload": true
  }
}
```

Get your `client_id` and `client_secret` at [strava.com/settings/api](https://www.strava.com/settings/api) (create a free API application).

To upload a file manually:

```bash
python3 strava.py upload activities/treadmill_20250611_120000.fit
```

#### Apple Health (via Strava)

Enable **Health** sync in the Strava iPhone app (`Settings → Health`). Strava will automatically write each uploaded workout to Apple Health — no extra steps needed.

#### Garmin Connect (automatic)

Garmin has no public upload API for personal projects, so this logs in the same way the Garmin Connect app does, via the unofficial [`garminconnect`](https://pypi.org/project/garminconnect/) package — the one dependency that isn't stdlib:

```bash
pip3 install --user --break-system-packages garminconnect
```

Add the Garmin section to `config.json`:

```json
{
  "shelly_ip": "192.168.1.xxx",
  "user_weight_kg": 75.0,
  "user_age": 35,
  "garmin": {
    "email": "you@example.com",
    "password": "YOUR_PASSWORD",
    "auto_upload": true
  }
}
```

Then log in once — this caches a session in `garmin_tokens/` (gitignored) so later runs don't need the password or a fresh login each time:

```bash
python3 garmin.py setup
```

If your account has MFA enabled, this first run will prompt for the code interactively.

To upload a file manually:

```bash
python3 garmin.py upload activities/treadmill_20250611_120000.fit
```

**Manual upload** (no setup needed): open [connect.garmin.com](https://connect.garmin.com) → cloud icon (top right) → **Import Data** → upload the `.fit` file from `activities/`.

---

## Tracking modes in detail

### Terminal tracker (`track.py`)

Starts immediately, shows a live table, saves both FIT and TCX on Ctrl+C:

```
      Time       Power         Speed   Distance  Pace       Calories
------------------------------------------------------------------------
  00:23:14     82.4W    3.0 km/h    1.16 km  20:00 /km    68 kcal
```

### Floating widget (`widget.py`)

A small always-on-top window styled like Apple system UI. Auto-detects start and stop, includes a manual "Save" button.

### Background monitor (`monitor.py`)

Runs silently in the background, auto-detects sessions, saves files, and uploads to Strava. Ideal as a launchd service that starts with macOS.

**Install as a service:**

```bash
sed -i '' "s/YOUR_USERNAME/$(whoami)/g" net.flexispot.monitor.plist
cp net.flexispot.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/net.flexispot.monitor.plist
```

Logs go to `monitor.log`. To stop:

```bash
launchctl unload ~/Library/LaunchAgents/net.flexispot.monitor.plist
```

### xbar plugin (`flexispot_xbar.5s.py`)

Shows live stats in the macOS menu bar via [xbar](https://xbarapp.com).

1. Install xbar
2. Copy all project files into the xbar plugin folder (xbar → "Open Plugin Folder")
3. Restart xbar

The menu bar shows `🟢 00:23:14  1.16km  68kcal` while the treadmill is running.

---

## File overview

| File | Purpose |
|---|---|
| `treadmill.py` | Shared library: Shelly API, calibration, physics, file export |
| `fit_writer.py` | Pure-Python FIT file writer (no external dependencies) |
| `strava.py` | Strava OAuth setup and activity upload |
| `garmin.py` | Garmin Connect login and activity upload |
| `calibrate.py` | One-time calibration wizard |
| `track.py` | Manual terminal tracker |
| `monitor.py` | Automatic background monitor |
| `widget.py` | Floating macOS HUD (tkinter) |
| `flexispot_xbar.5s.py` | xbar menu bar plugin |
| `net.flexispot.monitor.plist` | launchd service definition |
| `config.example.json` | Config template — copy to `config.json` |

---

## What's recorded per trackpoint

| Field | Source |
|---|---|
| Timestamp | System clock |
| Distance (m) | Integrated from speed × Δt |
| Speed (m/s) | Interpolated from calibration table |
| Power (W) | Shelly Plug — electrical draw of the treadmill motor |
| Cadence (strides/min) | Estimated from speed: `(87 + 4.8 × km/h) ÷ 2` |
| Calories | MET × weight × hours (Ainsworth et al.) |

Cadence is a biomechanical estimate (±10%). Power reflects the treadmill's electrical consumption, not metabolic running power — values are in a similar range for walking (50–150 W) but represent different things.

---

## Accuracy

Distance accuracy depends primarily on calibration quality. Factors that shift power draw:

- **Body weight** — heavier = more watts at the same speed
- **Belt temperature** — cold belt draws more power; let it run for 5 min before calibrating
- **Stride pattern** — walking vs. shuffling changes motor load slightly

For typical walking-desk use (1–4 km/h), expect ±5–10% distance accuracy after a good calibration.

---

## How the physics work

1. **Power measurement:** Shelly reports active power (W) every few seconds via its local HTTP API — no cloud involved.
2. **Speed lookup:** The calibration table stores `(speed_kmh, power_w)` pairs. Incoming power is linearly interpolated between the two nearest calibration points.
3. **Distance integration:** `distance += speed_ms × Δt` at each poll interval (5 s default).
4. **Calories:** MET values from the [Compendium of Physical Activities](https://sites.google.com/site/compendiumofphysicalactivities/) (Ainsworth et al.). `kcal = MET × weight_kg × hours`.
5. **Session detection:** The start threshold is auto-derived from the calibration file as 60% of the net power at the slowest calibrated speed — ensuring detection works even at 1 km/h without false positives from idle fluctuations.

---

## License

MIT — see [LICENSE](LICENSE).
