# OAK Camera — Home Assistant Add-on

A Home Assistant add-on for the **Luxonis OAK-D LR PoE** camera. Runs on-device AI object detection via DepthAI, streams live video, records motion clips, and integrates natively with Home Assistant.

---

## Features

- **Live RTSP stream** via mediamtx, embeddable in HA dashboards
- **On-device AI detection** — YOLOv6n, MobileNet SSD, or YOLO11n
- **Per-object confidence thresholds** for all 80 COCO classes
- **Motion recording** to `/media/oak_recordings/` with pre-roll buffer
- **Filename tagging** — detected objects appended to clip filenames
- **HA Ingress settings panel** — live feed + detection settings inside HA
- **Storage monitoring** — HA sensor + persistent notifications
- **HA events** — `oak_camera_motion_started`, `oak_camera_motion_stopped`, `oak_camera_storage_alert`

---

## Requirements

- Raspberry Pi 4 running Home Assistant OS (aarch64)
- Luxonis OAK-D LR PoE camera on the same network
- PoE switch or injector for the camera

---

## Installation

1. Copy the `oak_camera_app` folder to your HA `addons` Samba share
2. In HA: **Settings → Add-ons → Add-on store** (three-dot menu) → **Check for updates**
3. Install **OAK-D LR Camera** from Local add-ons
4. Configure in the add-on Settings tab (see Configuration below)
5. Start the add-on

---

## YOLO11n Setup (optional)

YOLO11n requires a one-time conversion on a Windows PC before installation:

1. Place `prepare_yolo11n.bat`, `prepare_yolo11n.ps1`, and `prepare_yolo11n_windows.py` in the `oak_camera_app` folder
2. Double-click `prepare_yolo11n.bat` and follow the prompts
3. Copy the generated `yolo11n.tar.xz` into `oak_camera_app`
4. Copy the folder to your HA addons share and install/update

If `yolo11n.tar.xz` is absent the add-on falls back to yolov6-nano automatically.

---

## Configuration

| Option | Default | Description |
|---|---|---|
| `camera_ip` | (auto) | Leave blank for UDP autodiscovery |
| `mjpeg_port` | 8765 | RTSP stream port |
| `fps` | 15 | Camera FPS (5–30; keep ≤ 20 on Pi 4) |
| `detection_model` | yolov6-nano | `yolov6-nano`, `luxonis/mobilenet-ssd:300x300`, or `yolo11n` |
| `filename_tag_objects` | true | Append detected objects to clip filenames |
| `storage_alert_enabled` | true | Enable storage alerts |
| `storage_alert_threshold` | 50 | Alert when storage exceeds this % |
| `ha_url` | homeassistant.local:8123 | Home Assistant URL |
| `ha_token` | | Long-lived access token |

**Per-object confidence and detection toggles** are managed in the built-in settings panel at the "OAK Camera" sidebar entry in HA (or `http://<ha-ip>:8767/`).

---

## HA Integration

Add to `configuration.yaml`:

```yaml
camera:
  - platform: generic
    name: OAK-D LR
    still_image_url: http://<ha-ip>:8766/snapshot
    stream_source: rtsp://<ha-ip>:8765/stream?transport=tcp

sensor:
  - platform: template
    sensors:
      oak_storage:
        friendly_name: OAK Camera Storage
        value_template: "{{ states('sensor.oak_camera_storage') }}%"
        unit_of_measurement: "%"
```

### Events

| Event | Payload |
|---|---|
| `oak_camera_motion_started` | `camera`, `detected` (list), `model`, `timestamp` |
| `oak_camera_motion_stopped` | `camera`, `timestamp` |
| `oak_camera_storage_alert` | `used_percent`, `used_gb`, `free_gb`, `total_gb`, `threshold` |

---

## Architecture

```
Thread 1  camera      Captures raw frames from OAK-D LR via DepthAI v3
Thread 2  detection   Per-object confidence filtering + overlay drawing
Thread 3  rtsp        Pushes display frames to ffmpeg → mediamtx
Thread 4  recorder    Writes MP4 clips to /media/oak_recordings/
Thread 5  snapshot    Updates JPEG for HA dashboard still image
Thread 6  http        Serves snapshot on port 8766
Thread 7  storage     Monitors disk usage every 5 minutes
Thread 8  ingress     HA Ingress panel on port 8767 (settings + live feed)
```

---

## Changelog

See [CHANGELOG.md](oak_camera_app/CHANGELOG.md) for full version history.

---

## License

MIT
