# Changelog

## 2.1.3
- Added sensor.oak_camera_storage entity in Home Assistant
- Updates every 5 minutes with current storage usage percentage
- Sensor attributes include used_gb, free_gb, total_gb, recordings folder path,
  alert threshold and whether alerts are enabled
- Add it to your dashboard with a Gauge or Entity card

## 2.1.2
- Fixed pre-roll flickering: reverted to bulk pre-roll write, but record_q
  is now sized to PRE_ROLL_FRAMES+30 so no live frames are dropped during
  the brief ~300ms write time
- Added storage monitoring thread (Thread 7) — checks disk usage every 5 min
- Sends HA persistent notification and fires oak_camera_storage_alert event
  when usage exceeds configured threshold
- New config options: storage_alert_enabled (bool), storage_alert_threshold (0-100)
- Alert re-fires every 5% increase above threshold, resets when usage drops below

## 2.1.1
- Fixed jump/skip at 3-4s into recordings: pre-roll frames now written one
  per loop iteration instead of all at once, eliminating the bulk write stall
  that caused the record queue to overflow and drop live frames
- Enlarged record_q to PRE_ROLL_FRAMES+30 to absorb bursts cleanly
- Fixed "No available devices (1 connected but in use)" on startup by adding
  a 3-second delay before the first camera connection attempt

## 2.1.0
- Complete pipeline restructure into 6 independent threads
- Thread 1: camera capture only — never blocked by downstream processing
- Thread 2: detection overlay and state machine
- Thread 3: RTSP publishing to ffmpeg/mediamtx
- Thread 4: video recording to disk
- Thread 5: JPEG snapshot updates
- Thread 6: HTTP snapshot server
- Each thread has its own queue and drops frames when full instead of blocking
- Fixes choppy/jumping recordings and unresponsive live stream

## 2.0.2
- Removed invalid model slug yolov6n-r4-coco-512x288 (did not exist in Luxonis Hub)
- Fixed MobileNet SSD slug to correct full form: luxonis/mobilenet-ssd:300x300
- Dropdown now contains only verified working models

## 2.0.1
- Models now pre-downloaded into the Docker image at build time
- No internet access required at runtime for model loading
- Faster startup — models load from local cache instead of downloading
- Added download_models.py build script for all 3 supported models

## 2.0.0
- Added configurable FPS (5-30, default 15) — warning logged if above 20 on Pi 4
- Added configurable detection model dropdown with 5 options:
  - YOLOv6 Nano (default) — 80 COCO classes, fastest
  - YOLOv6 Small — more accurate, slower
  - YOLOv8 Nano — newer architecture
  - Person Detection — people only (OpenVINO model)
  - Face Detection (SCRFD) — faces only
- Active model name shown in status overlay on video feed
- Model name included in HA event data
- Renamed mjpeg_port config key to rtsp_port for clarity
- Person-only models automatically trigger on any detection regardless of class filters

## 2.1.3
- Added sensor.oak_camera_storage entity in Home Assistant
- Updates every 5 minutes with current storage usage percentage
- Sensor attributes include used_gb, free_gb, total_gb, recordings folder path,
  alert threshold and whether alerts are enabled
- Add it to your dashboard with a Gauge or Entity card

## 2.1.2
- Fixed pre-roll flickering: reverted to bulk pre-roll write, but record_q
  is now sized to PRE_ROLL_FRAMES+30 so no live frames are dropped during
  the brief ~300ms write time
- Added storage monitoring thread (Thread 7) — checks disk usage every 5 min
- Sends HA persistent notification and fires oak_camera_storage_alert event
  when usage exceeds configured threshold
- New config options: storage_alert_enabled (bool), storage_alert_threshold (0-100)
- Alert re-fires every 5% increase above threshold, resets when usage drops below

## 2.1.1
- Fixed jump/skip at 3-4s into recordings: pre-roll frames now written one
  per loop iteration instead of all at once, eliminating the bulk write stall
  that caused the record queue to overflow and drop live frames
- Enlarged record_q to PRE_ROLL_FRAMES+30 to absorb bursts cleanly
- Fixed "No available devices (1 connected but in use)" on startup by adding
  a 3-second delay before the first camera connection attempt

## 2.1.0
- Complete pipeline restructure into 6 independent threads
- Thread 1: camera capture only — never blocked by downstream processing
- Thread 2: detection overlay and state machine
- Thread 3: RTSP publishing to ffmpeg/mediamtx
- Thread 4: video recording to disk
- Thread 5: JPEG snapshot updates
- Thread 6: HTTP snapshot server
- Each thread has its own queue and drops frames when full instead of blocking
- Fixes choppy/jumping recordings and unresponsive live stream

## 2.0.2
- Removed invalid model slug yolov6n-r4-coco-512x288 (did not exist in Luxonis Hub)
- Fixed MobileNet SSD slug to correct full form: luxonis/mobilenet-ssd:300x300
- Dropdown now contains only verified working models

## 2.0.1
- Models now pre-downloaded into the Docker image at build time
- No internet access required at runtime for model loading
- Faster startup — models load from local cache instead of downloading
- Added download_models.py build script for all 3 supported models

## 2.0.0
- Added configurable FPS (5-30, default 15) — adjustable from app settings
- Added configurable detection model dropdown with 3 options:
  - YOLOv6 Nano (default, fastest, 80 COCO classes)
  - YOLOv6 Nano R4 (updated variant, 80 COCO classes)
  - MobileNet SSD (lightest, 20 PASCAL VOC classes)
- MobileNet SSD uses correct PASCAL VOC class names for people/animal/vehicle mapping
- Active model and FPS now logged at startup and included in HA event data
- Added FPS warning if set above 20 on Pi 4

## 1.9.0
- Added YOLOv6n on-device object detection via DepthAI DetectionNetwork node
- Recording now triggers only on detected people, animals, or vehicles (configurable)
- Added bounding box and label overlays on video feed and recordings
- Color coded boxes: green=person, orange=animal, blue=vehicle
- New config options: confidence_threshold, detect_people, detect_animals, detect_vehicles
- Removed motion_threshold and min_motion_area (replaced by AI detection)
- Detection event now includes list of detected class names in HA event data
- Added depthai-nodes to Dockerfile

## 1.8.1
- Fixed missing first recording after startup — added media volume readiness check
- Added VideoWriter.isOpened() verification to catch silent write failures
- Added write test before each recording to confirm directory is accessible

## 1.8.0
- Moved recording out of Home Assistant and into the app itself
- App now writes MP4 clips directly to /media/oak_recordings/ on motion
- Added 3-second pre-roll buffer so clips capture what happened before motion
- Added 5-second post-roll so clips dont cut off abruptly
- Added 120-second hard cap on clip length with automatic new clip
- camera.record action no longer needed in HA automation

## 1.7.0
- Reduced resolution to 1280x720 and FPS to 15 to ease load on Raspberry Pi 4
- Increased mediamtx write queue size to handle multiple simultaneous readers
- Added JPEG snapshot HTTP server on port 8766 for HA dashboard thumbnail
- Added bitrate cap to ffmpeg encoder

## 1.6.1
- Fixed deprecation warning: replaced getMxId() with getDeviceId()

## 1.6.0
- Replaced ffmpeg-as-RTSP-server approach with mediamtx (a proper RTSP server)
- ffmpeg now publishes to mediamtx rather than attempting to serve RTSP directly
- Added mediamtx.yml configuration file
- Updated run.sh to start mediamtx before the Python bridge
- Stream is now available at rtsp://<ha-ip>:8765/stream

## 1.5.0
- Replaced MJPEG HTTP stream with RTSP via ffmpeg
- Eliminated the need for a separate snapshot endpoint
- Stream now compatible with camera.record action in Home Assistant automations

## 1.4.0
- Rewrote pipeline for DepthAI v3 API
- Replaced dai.node.ColorCamera with dai.node.Camera
- Replaced XLinkOut/getOutputQueue with v3 createOutputQueue
- Pipeline now uses pipeline.start() and pipeline.isRunning()
- Device connection now established before pipeline creation

## 1.3.0
- Fixed camera node API: replaced setBoardSocket with correct v3 method
- Fixed ImageManip: replaced setResize with setOutputSize

## 1.2.0
- Added host_network: true to allow depthai to reach PoE camera via UDP discovery
- Pinned Dockerfile base image to aarch64-base-debian:bookworm
- Added explicit TCP/IP protocol and bootloader state to DeviceInfo for PoE connection
- Moved pipeline build inside retry loop

## 1.1.0
- Fixed Dockerfile: replaced Alpine (apk) with Debian (apt-get)
- Added Luxonis ARM wheel index for depthai pip install
- Fixed map syntax in config.yaml
- Removed incorrect image: field from config.yaml

## 1.0.0
- Initial release
- DepthAI v2 pipeline with ColorCamera node
- MJPEG HTTP stream on port 8765
- Motion detection via frame differencing
- Home Assistant event firing on motion start/stop

## 2.2.1
- Fixed OOM crash during Docker build on Pi 4
- Moved YOLO11n conversion off the Pi entirely — run prepare_yolo11n_windows.py
  on your Windows PC to generate yolo11n.tar.xz, then copy it to the
  oak_camera_app folder before building
- Dockerfile now does a simple COPY of the pre-built archive (no PyTorch on Pi)
- Added graceful fallback to yolov6-nano if yolo11n.tar.xz is not present
- Removed convert_yolo11n.py (replaced by prepare_yolo11n_windows.py)

## 2.2.0
- Added YOLO11n to the model dropdown
- YOLO11n is converted at Docker build time using the Luxonis tools CLI
  (yolo11n.pt → ONNX with patched detection head → RVC2 NNArchive)
- Stored locally at /models/yolo11n.tar.xz inside the container
- No internet access required at runtime for YOLO11n
- Hub models (yolov6-nano, mobilenet-ssd) still load from depthai cache
- Local vs Hub loading is handled automatically based on model selection
- YOLO11n uses COCO 80 classes — same people/animal/vehicle trigger sets as YOLOv6n
- Note: YOLO11n may run slower than YOLOv6n on RVC2 due to its more
  complex C3k2 + C2PSA architecture — monitor FPS in logs after switching
