# OAK-D LR Camera — Home Assistant App

Connects a Luxonis OAK-D LR PoE camera to Home Assistant. Provides a live
MJPEG stream and fires motion events that can trigger recordings and
push notifications.

---

## Files

| File | Purpose |
|---|---|
| `config.yaml` | App metadata and configurable options |
| `Dockerfile` | Container definition (installs depthai, opencv) |
| `run.sh` | Startup script |
| `oak_bridge.py` | Main Python app |
| `ha_configuration.yaml` | HA config snippets to copy in |

---

## Installation

### Step 1 — Copy the app to Home Assistant

Using the Samba app (Settings > Apps > Samba), your HA instance
will appear on your local network. Open the `addons` shared folder
and copy the entire `oak_camera_app` folder into it.

Alternatively via SSH, copy the folder to `/addons/oak_camera_app/`.

### Step 2 — Install the app

1. In Home Assistant go to **Settings > Apps**
2. Click **App store** (bottom right)
3. Click the three-dot menu (top right) → **Check for updates**
4. Refresh the page — you should see **"Local apps"** section with **OAK-D LR Camera**
5. Click it and hit **Install**

### Step 3 — Configure the app

After installation, click **Configure** and fill in:

| Option | Description |
|---|---|
| `camera_ip` | IP address of your OAK-D LR (e.g. `192.168.1.50`). Leave blank to auto-discover. |
| `mjpeg_port` | Port to serve the stream on. Default: `8765` |
| `motion_threshold` | Pixel difference sensitivity (0-255). Default: `25` |
| `min_motion_area` | Minimum changed pixel area to count as motion. Default: `5000` |
| `ha_url` | URL of your HA instance. Default: `http://homeassistant.local:8123` |
| `ha_token` | A Long-Lived Access Token from your HA profile page |

To get a Long-Lived Access Token:
1. Go to your HA profile (click your name bottom-left)
2. Scroll to **Long-Lived Access Tokens**
3. Click **Create Token**, give it a name, copy the value

### Step 4 — Add the camera to Home Assistant

Copy the contents of `ha_configuration.yaml` into the appropriate
places in your HA config:

- The `camera:` block goes into `configuration.yaml`
- The `automation:` blocks go into `automations.yaml` (or use the UI)
- The dashboard card can be pasted into any Lovelace dashboard

Then go to **Developer Tools > Check Configuration**, and if it passes,
click **Restart**.

### Step 5 — Set up your recordings folder

Make sure the `/media/oak_recordings/` folder exists. You can create
it from the File Editor app, or via SSH:

```bash
mkdir -p /media/oak_recordings
```

This folder will be accessible via your Samba share at
`\\homeassistant\media\oak_recordings`.

---

## How it works

```
OAK-D LR (PoE)
     │
     │  DepthAI SDK
     ▼
oak_bridge.py
     │
     ├──► MJPEG HTTP stream (:8765/stream)   ◄── HA Generic Camera
     ├──► JPEG snapshot    (:8765/snapshot)  ◄── HA notifications
     │
     └──► HA REST API (/api/events/...)
              │
              ├── oak_camera_motion_started  ──► Record clip + notify
              └── oak_camera_motion_stopped  ──► Optional notify
```

---

## Tuning motion sensitivity

- **Too sensitive** (triggers on shadows, light changes): raise `motion_threshold` or `min_motion_area`
- **Missing real motion**: lower those values
- Good starting points for an outdoor scene: threshold `30`, area `8000`
- Good starting points for an indoor scene: threshold `20`, area `3000`
