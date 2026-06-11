# Flexispot Treadmill Tracker

Track walking-desk sessions with a [Shelly Plug](https://www.shelly.com/en/products/shop/shelly-plug-s) and export them to Garmin Connect — zero subscription, zero wearable required.

## The problem

A Garmin watch measures treadmill distance via wrist acceleration. When you're typing at a standing desk, your arms stay still → the watch records **0 km**.

## The solution

The Shelly Plug measures the treadmill's power draw in real time. Because each speed setting has a characteristic wattage, the script can infer speed and accumulate distance — no GPS, no footpod.

```
Shelly Plug (power in W)  →  calibration table  →  speed (km/h)  →  distance (m)  →  TCX file
```

The TCX file is imported into Garmin Connect (or any compatible app) and shows up like a normal treadmill workout.

---

## Hardware

| Item | Notes |
|---|---|
| [Shelly Plug M Gen3](https://www.shelly.com/) | Any Gen3 Shelly with power metering works |
| Flexispot treadmill | Or any treadmill — the calibration adapts to it |
| Mac on the same Wi-Fi | The scripts talk directly to the Shelly HTTP API |

---

## Setup

**No pip install needed** — only Python 3.10+ stdlib.

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/flexispot-shell.git
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

The script guides you through measuring power draw at each speed step. Takes about 5 minutes per speed level. Result is saved in `calibration.json`.

**Tip:** Re-run calibration if you change belt tension or after a few weeks of use.

### 3. Track a session

Choose any of the three tracking modes:

| Mode | Command | Best for |
|---|---|---|
| **Terminal** | `python3 track.py` | Manual start/stop, clean live table |
| **Widget** | `python3 widget.py` | Floating HUD while working |
| **Background** | `python3 monitor.py` | Fully automatic, runs as a macOS service |
| **xbar** | See below | Menu bar indicator |

### 4. Import into Garmin Connect

1. Open [connect.garmin.com](https://connect.garmin.com)
2. Click the cloud icon (top right) → **Import Data**
3. Upload the `.tcx` file from the `activities/` folder

---

## Tracking modes in detail

### Terminal tracker (`track.py`)

Starts immediately, shows a live table, saves on Ctrl+C:

```
      Time       Power         Speed   Distance  Pace       Calories
------------------------------------------------------------------------
  00:23:14     82.4W    3.0 km/h    1.16 km  20:00 /km    68 kcal
```

### Floating widget (`widget.py`)

A small always-on-top window styled like Apple system UI. Auto-detects start and stop, includes a manual "Save" button.

![Widget screenshot](docs/widget.png)

### Background monitor (`monitor.py`)

Runs silently in the background and auto-saves sessions. Ideal as a launchd service so it starts with macOS.

**Install as a service:**

```bash
# Edit net.flexispot.monitor.plist — replace YOUR_USERNAME with your macOS username
sed -i '' "s/YOUR_USERNAME/$(whoami)/g" net.flexispot.monitor.plist

cp net.flexispot.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/net.flexispot.monitor.plist
```

Logs go to `monitor.log`. To stop the service:

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
| `treadmill.py` | Shared library: Shelly API, calibration, physics, TCX export |
| `calibrate.py` | One-time calibration wizard |
| `track.py` | Manual terminal tracker |
| `monitor.py` | Automatic background monitor |
| `widget.py` | Floating macOS HUD (tkinter) |
| `flexispot_xbar.5s.py` | xbar menu bar plugin |
| `net.flexispot.monitor.plist` | launchd service definition |
| `config.example.json` | Config template — copy to `config.json` |

---

## Accuracy

Distance accuracy depends primarily on calibration quality. Factors that shift power draw:

- **Body weight** — heavier = more watts at the same speed
- **Belt temperature** — cold belt draws more power; run for 5 min before calibrating
- **Stride pattern** — walking vs. shuffling changes load slightly

For typical walking-desk use (2–4 km/h), expect ±5–10% distance accuracy after a good calibration.

---

## How the physics work

1. **Power measurement:** Shelly reports active power (W) every few seconds via its local HTTP API — no cloud involved.
2. **Speed lookup:** The calibration table stores `(speed_kmh, power_w)` pairs. Incoming power is linearly interpolated between the two nearest calibration points.
3. **Distance integration:** `distance += speed_ms × Δt` at each poll interval (5 s default).
4. **Calories:** MET values from the [Compendium of Physical Activities](https://sites.google.com/site/compendiumofphysicalactivities/) (Ainsworth et al.). `kcal = MET × weight_kg × hours`.

---

## License

MIT — see [LICENSE](LICENSE).
