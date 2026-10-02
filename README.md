# Luxonis OAK-D LR Camera

On-device AI object detection for the **Luxonis OAK-D LR PoE** camera. Runs as a
Home Assistant add-on or as a standalone program on Windows and Linux. Both use
the same code, so both get the same features.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcrystalheeler%2FLuxonis-OAK-D-LR)

---

## Features

- **Live RTSP stream** through [mediamtx](https://github.com/bluenviron/mediamtx), for a Home Assistant dashboard or any other client
- **On-device AI detection** — YOLOv6n, MobileNet SSD, or YOLO11n, running on the camera
- **Per-object confidence thresholds** for all 80 COCO classes
- **Motion recording** to MP4, with a 3 second pre-roll buffer
- **Filename tagging** — the detected object names go into each clip filename
- **Web settings panel** with a live feed, on port 8767
- **Storage monitoring** — a Home Assistant sensor plus notifications
- **Home Assistant events** — `oak_camera_motion_started`, `oak_camera_motion_stopped`, `oak_camera_storage_alert`

---

## Install

### Home Assistant add-on

1. Click the badge above, or go to **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and add
   `https://github.com/crystalheeler/Luxonis-OAK-D-LR`.
2. Install **OAK-D LR Camera**.
3. Set `camera_ip` on the Configuration tab.
4. Start the add-on. **OAK Camera** then appears in the sidebar.

The add-on installs a prebuilt image from GHCR, so it does not compile anything
on your Raspberry Pi.

Requirements: Home Assistant OS on `aarch64` or `amd64`, and the camera on the
same network through a PoE switch or injector.

### Windows, portable

1. Download `OakCamera-<version>-win64.zip` from the
   [latest release](https://github.com/crystalheeler/Luxonis-OAK-D-LR/releases/latest).
2. Unzip it anywhere you can write to. Avoid `C:\Program Files`.
3. Set `camera_ip` in `oak_config.yaml`.
4. Run `OakCamera.exe`. A camera icon appears next to the clock.
5. Right-click the icon and choose **Open settings**.

No installer and no administrator rights. Windows Firewall asks once for
`OakCamera.exe` and once for `mediamtx.exe`. See
[windows/README-windows.md](windows/README-windows.md) for the full guide.

### Linux, from source

```bash
git clone https://github.com/crystalheeler/Luxonis-OAK-D-LR.git
cd Luxonis-OAK-D-LR
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt \
  --extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/
sudo apt install ffmpeg          # for the RTSP stream
cp windows/oak_config.yaml src/oak_config.yaml   # then edit camera_ip
python src/oak_launcher.py
```

Install [mediamtx](https://github.com/bluenviron/mediamtx) on your `PATH` for
RTSP. Without `ffmpeg` or `mediamtx` the RTSP stream turns off, and the MJPEG
feed, snapshots and recording keep working.

---

## Configuration

Both deployments read the same keys. The add-on reads them from the
Configuration tab, and the portable build reads them from `oak_config.yaml`.

| Option | Default | Description |
|---|---|---|
| `camera_ip` | (empty) | Camera IP address. Empty searches for a USB device. |
| `mjpeg_port` | 8765 | RTSP port. The snapshot server uses this plus one. |
| `fps` | 15 | 5 to 30. Keep it at 20 or below on a Raspberry Pi 4. |
| `detection_model` | `yolov6-nano` | `yolov6-nano`, `luxonis/mobilenet-ssd:300x300`, or `yolo11n` |
| `filename_tag_objects` | true | Put the detected object names in each clip filename. |
| `storage_alert_enabled` | true | Watch the recordings drive. |
| `storage_alert_threshold` | 50 | Alert above this percentage. |
| `ha_url` | `http://homeassistant.local:8123` | Home Assistant address. |
| `ha_token` | (empty) | Long-lived access token. Empty turns the integration off. |
| `models_dir` | see below | Folder holding `yolo11n.tar.xz`. |

Per-object toggles and confidence values live in the web settings panel, not in
this file. Open it from the Home Assistant sidebar, from the tray icon, or at
`http://<host>:8767/`.

### Where files go

| | Home Assistant add-on | Portable |
|---|---|---|
| Settings and log | `/data` | `data\` beside the executable |
| Recordings | `/media/oak_recordings` | `recordings\` beside the executable |
| Models | `/media/oak_models` | `models\` beside the executable |

Override any of them with `recordings_dir`, `data_dir` and `models_dir` in the
config, or with the `OAK_RECORDINGS_DIR`, `OAK_DATA_DIR` and `OAK_MODELS_DIR`
environment variables. A portable build that cannot write beside its executable
falls back to `%LOCALAPPDATA%\OakCamera`.

### Ports

| Port | Use |
|---|---|
| 8765 | RTSP stream, at `rtsp://<host>:8765/stream` |
| 8766 | JPEG snapshot, at `http://<host>:8766/snapshot` |
| 8767 | Settings panel and the live MJPEG feed |
| 8764 | Held open internally to stop a second copy from starting |

---

## YOLO11n, optional

YOLO11n needs a one-time conversion on a PC with more memory than a Pi:

```bash
pip install ultralytics blobconverter "luxonis-tools @ git+https://github.com/luxonis/tools.git"
python tools/prepare_yolo11n_windows.py
```

Copy the resulting `yolo11n.tar.xz` into the models folder from the table above,
then select `yolo11n` as the model. Without that file the program falls back to
`yolov6-nano` and says so in the log.

---

## Home Assistant integration

Both deployments send events and the storage sensor, so the standalone build on
a Windows PC can still drive Home Assistant. Fill in `ha_url` and `ha_token`.

Add to `configuration.yaml`:

```yaml
camera:
  - platform: generic
    name: OAK-D LR
    still_image_url: http://<host>:8766/snapshot
    stream_source: rtsp://<host>:8765/stream?transport=tcp

sensor:
  - platform: template
    sensors:
      oak_storage:
        friendly_name: OAK Camera Storage
        value_template: "{{ states('sensor.oak_camera_storage') }}%"
        unit_of_measurement: "%"
```

See [ha_configuration.yaml](ha_configuration.yaml) for automation examples.

### Events

| Event | Payload |
|---|---|
| `oak_camera_motion_started` | `camera`, `detected` (list), `model`, `timestamp` |
| `oak_camera_motion_stopped` | `camera`, `timestamp` |
| `oak_camera_storage_alert` | `used_percent`, `used_gb`, `free_gb`, `total_gb`, `threshold` |

---

## Repository layout

```
src/        shared Python for every deployment
  oak_launcher.py   entry point: reads config, starts mediamtx, runs the bridge
  oak_bridge.py     the 8 thread pipeline
  oak_paths.py      per-platform folder resolution
  oak_logging.py    rotating log file
  oak_runtime.py    binary staging, instance guard, restart
  oak_tray.py       Windows tray icon
  settings_page.py  the web panel
addon/      Home Assistant add-on manifest
docker/     multi-architecture image for the add-on
windows/    PyInstaller spec, portable config, icon
tools/      YOLO11n preparation and icon generation
```

### Pipeline

```
Thread 1  camera      Captures raw frames from the OAK-D LR through DepthAI v3
Thread 2  detection   Per-object confidence filtering and overlay drawing
Thread 3  rtsp        Pushes display frames to ffmpeg, then to mediamtx
Thread 4  recorder    Writes MP4 clips with a pre-roll buffer
Thread 5  snapshot    Updates the JPEG for the dashboard still image
Thread 6  http        Serves the snapshot on port 8766
Thread 7  storage     Checks disk usage every 5 minutes
Thread 8  ingress     Settings panel and live feed on port 8767
```

---

## Building

### The Windows executable

```bash
pip install -r windows/requirements-windows.txt \
  --extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/
# Put mediamtx.exe and ffmpeg.exe in windows/bin/ to bundle them.
pyinstaller --clean --noconfirm windows/oak_camera.spec
```

### The add-on image

```bash
docker buildx build --platform linux/amd64,linux/arm64 -f docker/Dockerfile .
```

### A release

Push a tag. The [workflow](.github/workflows/release.yml) then builds the
Windows ZIP, pushes the image to GHCR, and publishes a Release with both:

```bash
# Bump version: in addon/oak_camera/config.yaml to match, and sync the changelog.
cp CHANGELOG.md addon/oak_camera/CHANGELOG.md
git tag v3.0.1 && git push origin v3.0.1
```

---

## Release checks

```bash
python tests/test_modules.py     # 45 checks on the support modules
python tests/privacy_scan.py     # no personal data in tracked files
```

Both run in the `check` job of the release workflow. A tag push cannot build a
package that fails one.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Each release has an audit note holding the
evidence, the measurements and the gaps that the changelog leaves out:
[docs/audit-3.0.1.md](docs/audit-3.0.1.md).

---

## License

MIT
