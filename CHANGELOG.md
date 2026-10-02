# OAK-D LR Camera — Changelog

## 3.0.0
Runs standalone on Windows and Linux as well as a Home Assistant add-on, from one source tree.

### Changes & improvements
- **Portable Windows build.** `OakCamera.exe` is one file. Unzip it anywhere and run it.
- **System tray icon.** It opens the settings page and the log, toggles start with Windows, and restarts or quits the program.
- **Log file.** The program writes `oak_camera.log` and rotates it. It also captures mediamtx and ffmpeg output.
- **One launcher for every deployment.** `oak_launcher.py` replaces `run.sh` and reads the add-on options file directly.
- **Prebuilt add-on image.** The add-on installs from a container registry. It no longer builds on the user's device.
- **Per-platform folders.** Settings, recordings and models resolve per deployment. Each one accepts an override.
- **Optional ffmpeg.** The RTSP stream turns off without it. The MJPEG feed, snapshots and recording continue.
- **Shut down button** on the settings page, for a deployment with no tray icon.
- **Single instance guard.** A second copy exits instead of competing for the camera.
- **One release workflow.** A tag builds the Windows package and the add-on image.

### Bugs fixed
- **The RTSP stream failed on every port except 8765.** The server config now follows the configured port.
- **Restart stopped the program for good outside Home Assistant.** The process now restarts itself.
- **A restart wrote a traceback to the log.** The RTSP publisher now exits cleanly.

### Known issues
- **The Windows build is not signed.** SmartScreen warns on first run. Choose More info, then Run anyway.
- **Windows Firewall prompts twice.** Once for `OakCamera.exe` and once for `mediamtx.exe`.
- **The add-on folder moved.** An earlier install from this repository needs installing again.
- **A new container image is private.** Set the package to public or Home Assistant cannot pull it.
- **The arm64 image builds under emulation.** The audit note gives the expected build time.

## 2.4.2
- RTSP stream now sends one keyframe per second (`-g` set to the FPS
  option). x264's default is one keyframe every 250 frames, and a viewer
  cannot draw a picture until the first keyframe arrives. AnyCam measured
  19 to 28 s before the first frame on every new connection to this stream
  (2026-09-29); it should now be about 1 s. The fixed 1000k bitrate spends
  a little more on keyframes, so the picture may be slightly softer

## 2.4.1
- Fixed filename tag min duration not saving when set to 0: JS falsy evaluation
  caused parseFloat('0') || 2.0 to return 2.0 instead of 0; fixed with explicit
  empty-string check so 0 is correctly sent to the server
- Fixed overlay text inconsistency when status changes from Monitoring to
  Recording: em dash character (U+2014) in "RECORDING - person" is not
  supported by OpenCV's built-in fonts (ASCII only), causing garbled rendering
  and changing the apparent box size; replaced with plain ASCII hyphen
- Moved overlay drawing constants (_OV_FONT, _OV_SCALE, _OV_BG, etc.) and
  _draw_label_box() helper outside the frame loop so they are defined once
  and consistently shared by all three overlay elements (status, timestamp,
  model name) on every frame

## 2.4.0
- Default confidence changed from 0.70 to 0.50
- Default filename tag min duration changed from 2s to 0 (tag all detected objects)
- Added "Save to file" button in settings toolbar — exports all current settings
  to a dated .txt file (oak_detection_settings_YYYY-MM-DD.txt) organized by
  category with enabled state and confidence for each object
- Detection bounding box label text now uses black text on bright/yellow
  backgrounds for legibility — luminance calculation picks black or white
  automatically based on background colour
- Timestamp and model name in video overlay now match the status box exactly:
  same font (HERSHEY_SIMPLEX 0.38), same dark background fill (30,30,30),
  same compact padding — all three elements use a shared draw_label_box helper
- Missing changelog entries added for versions 2.3.4 through 2.3.9 (below)

## 2.3.10
- Fixed JS syntax error introduced in 2.3.8: bare newline character inside a
  single-quoted JS string in the confirm() dialog broke the entire script block,
  causing live feed to show "Connecting..." and Detection Settings panel to not
  expand. Fixed by using String.fromCharCode(10) instead of '\n' in the join call
- Added "Set all confidence" control at top of settings panel — enter a value
  and click Apply to blanket-set all 80 per-object confidence levels at once
- Added "Hardware threshold" field — controls the camera-level confidence floor;
  changes trigger a confirmation dialog offering to restart the app immediately
  so the new value takes effect (restart handled via SIGTERM, S6 brings it back)
- Added "Filename tag min duration (sec)" field — replaces the fixed 2-second
  threshold with a user-adjustable value from 0 to 60 seconds (supports decimals
  like 0.2s); setting to 0 tags all detected objects regardless of duration
- hw_threshold and tag_duration saved to settings JSON and restored on reload
- Added /api/restart endpoint to ingress server

## 2.3.9
- Attempted fix for JS bare newline bug using array.join('\\n') — the join
  string itself still contained a bare newline in the rendered HTML, so the
  bug persisted. Live feed showed "Connecting..." and Detection Settings
  panel would not expand

## 2.3.8
- Added "Set all confidence" control in settings panel
- Added "Hardware threshold" field in settings panel (persisted in settings JSON)
- Added hardware threshold change detection: confirmation dialog on Save & Apply
  if hw_threshold changed, offering immediate restart via SIGTERM
- Added /api/restart endpoint to ingress server
- INTRODUCED BUG: confirm() dialog string built with array.join('\\n') where
  '\\n' rendered as a bare newline in the HTML, breaking JS script parsing

## 2.3.7
- Added "Set all confidence" and "Hardware threshold" controls to settings panel
  (initial version, later refined in 2.3.8)
- hw_threshold saved in settings JSON and restored on reload
- Hardware threshold logged each time camera pipeline (re)connects

## 2.3.6
- Fixed root cause of degraded detection: CATEGORY_ENABLED env vars removed in
  2.3.3 but still read by bridge — all categories showed disabled at startup
- Fixed HARDWARE_THRESHOLD never updated after _apply_settings_to_thresholds:
  was computed as local variable hw, never assigned to global
- Removed env-var category system — settings panel is now sole authority
- Added DEFAULT_SETTINGS: people + animals ON at 0.70 used on first run
- _apply_settings_to_thresholds merges DEFAULT_SETTINGS as base then applies
  saved overrides — reset also returns to defaults
- Added persistent last_detections so boxes stay visible between NN cycles
- Added 3-frame grace buffer before ending detection (prevents rapid on/off)
- Video overlay: status box reduced to half size; model name under timestamp

## 2.3.5
- Fixed live feed not showing in ingress panel: HA ingress proxy buffers
  multipart/x-mixed-replace streams; stream src now set to direct port 8767
  via window.location.hostname, bypassing the ingress proxy entirely

## 2.3.4
- Live MJPEG stream embedded at top of ingress settings panel (16:9, full width)
- Detection settings collapsed by default; "Detection Settings" bar toggles them
- Ingress server switched to ThreadingHTTPServer so MJPEG clients don't block API
- Status box reduced to ~half size using dynamic width based on text content
- Model name shown below timestamp in top-right corner of video overlay

## 2.3.3
- Fixed confidence levels showing as 0.6 instead of 0.7 — saved settings file
  from a previous version was overriding the new defaults on startup; added
  version migration that resets saved settings when defaults change
- Added Reset to Defaults button in the settings panel
- Simplified HA config form — per-category and per-object settings are now
  managed exclusively through the Settings panel (HA Ingress sidebar entry)
  keeping the config form clean and minimal
- With ingress enabled, HA automatically adds an "Open Web UI" button to the
  app info page which opens the same settings panel as the sidebar entry
- All confidence defaults confirmed at 0.70

## 2.3.2
- Added HA Ingress support — settings panel now embedded inside HA as a
  sidebar entry labelled "OAK Camera" (mdi:camera-iris icon)
- Ingress panel served on port 8767; HA proxies and authenticates natively
- No separate browser tab or URL required — lives inside Home Assistant
- All confidence defaults set to 0.70
- Relative URLs used throughout settings HTML for correct ingress proxying

## 2.3.1
- Added built-in web settings panel (initially at http://<ha-ip>:8766/settings)
- Per-object confidence and enable/disable toggle for all 80 COCO classes
- Organised by category with colour-coded headers matching bounding box colours
- Category-level "All On / All Off" buttons and global Enable All / Disable All
- Settings saved to /data/oak_settings.json and applied immediately without restart
- Settings survive app restarts and layer on top of HA config defaults

## 2.3.0
- Per-category detection: 10 categories (people, animals, vehicles, food,
  kitchen, furniture, electronics, sports, accessories, outdoor)
- Per-category confidence threshold — each category has its own sensitivity
- Per-object confidence overrides via object_overrides field ("cat:0.2,knife:0.1")
  Set to 0 to disable a specific object even if its category is enabled
- Hardware threshold set to minimum of all active per-object thresholds (min 0.10)
  so all candidates reach Python host-side for accurate per-object filtering
- Recording filename tagging — objects seen for 2+ seconds appended to filename
  e.g. motion_20260417_120000-cat-person.mp4 (capped at 10 objects)
- filename_tag_objects config option toggles filename tagging on/off
- Bounding box colours reflect category: green=people, orange=animals,
  blue=vehicles, cyan=food, purple=furniture, yellow=electronics, etc.
- MobileNet SSD now remaps PASCAL VOC names to COCO equivalents

## 2.2.1
- Fixed OOM crash during Docker build on Pi 4 caused by installing PyTorch/
  ultralytics inside the container (exhausts ~4GB RAM during build)
- Moved YOLO11n conversion entirely to Windows PC via prepare_yolo11n.bat
  and prepare_yolo11n_windows.py scripts
- Dockerfile now does a simple COPY of the pre-built yolo11n.tar.xz archive
- App gracefully falls back to yolov6-nano if yolo11n.tar.xz is absent
- Removed convert_yolo11n.py (superseded by Windows prep scripts)

## 2.2.0
- Added YOLO11n to the model dropdown (alongside yolov6-nano and mobilenet-ssd)
- YOLO11n converted via Luxonis tools CLI on Windows PC before Docker build:
  yolo11n.pt → ONNX with patched detection head → RVC2 NNArchive (.tar.xz)
- YOLO11n loaded at runtime from /models/yolo11n.tar.xz — no internet needed
- Hub models (yolov6-nano, mobilenet-ssd) still load from depthai cache
- prepare_yolo11n.bat / prepare_yolo11n_windows.py provided for Windows conversion

## 2.1.3
- Added sensor.oak_camera_storage entity in Home Assistant
- Updates every 5 minutes with current disk usage percentage
- Attributes: used_gb, free_gb, total_gb, recordings folder, alert threshold
- Add to dashboard with a Gauge or Entity card

## 2.1.2
- Fixed pre-roll flickering introduced in 2.1.1: reverted to bulk pre-roll write;
  record_q now sized to PRE_ROLL_FRAMES+30 so no live frames drop during the
  brief ~300ms write burst
- Added storage monitoring thread (Thread 7) — checks disk usage every 5 minutes
- Fires oak_camera_storage_alert event and sends HA persistent notification when
  usage exceeds threshold; re-alerts every 5% above threshold
- New config options: storage_alert_enabled, storage_alert_threshold (0-100)

## 2.1.1
- Fixed jump/skip at 3-4s mark in recordings: pre-roll bulk write was blocking
  the recorder thread, causing record_q to fill and drop ~2-3s of live frames
  (reverted in 2.1.2 in favour of a larger queue approach)
- Fixed "No available devices (1 connected but in use)" on startup by adding
  a 3-second delay before first camera connection attempt

## 2.1.0
- Complete pipeline restructure into 6 independent threads to fix choppy
  recordings and unresponsive live RTSP stream
- Thread 1: camera capture only — never blocked by downstream consumers
- Thread 2: detection overlay drawing and state machine
- Thread 3: RTSP publishing via ffmpeg pipe to mediamtx
- Thread 4: video recording to disk with pre-roll buffer
- Thread 5: JPEG snapshot updates
- Thread 6: HTTP snapshot server
- Each thread has its own bounded queue; slow consumers drop frames rather
  than blocking the camera capture loop

## 2.0.2
- Removed invalid model slug yolov6n-r4-coco-512x288 (did not exist in Hub —
  caused camera crash with "No public model found" 404 error)
- Corrected MobileNet SSD slug to full form: luxonis/mobilenet-ssd:300x300
- Model dropdown now contains only verified working Hub slugs

## 2.0.1
- All supported models pre-downloaded into Docker image at build time via
  download_models.py — no internet access required at runtime
- Faster startup: models load from local depthai cache instead of Hub download

## 2.0.0
- Added configurable FPS (5-30, default 15); warning logged if above 20 on Pi 4
- Added configurable detection model dropdown:
  yolov6-nano (default), luxonis/mobilenet-ssd:300x300
- Active model name shown in status overlay on video feed
- Model name included in HA event payload

## 1.9.0
- Added YOLOv6n on-device object detection via DepthAI DetectionNetwork node
- Recording now triggers on AI detections of people, animals, or vehicles
- Configurable: detect_people, detect_animals, detect_vehicles, confidence_threshold
- Bounding box and label overlays drawn on video feed and recordings
- Colour-coded boxes: green=person, orange=animal, blue=vehicle
- Replaced frame-differencing motion detection entirely

## 1.8.1
- Fixed missing first recording after startup — added /media volume readiness check
- Added VideoWriter.isOpened() verification to catch silent write failures
- Added write test before each recording to confirm directory is accessible

## 1.8.0
- Moved recording from Home Assistant (camera.record) into the app itself
- App writes MP4 clips directly to /media/oak_recordings/ on motion detection
- 3-second pre-roll buffer so clips capture events before motion triggered
- 5-second post-roll so clips don't cut off immediately when motion stops
- 120-second hard cap per clip with automatic split and new clip

## 1.7.0
- Reduced resolution to 1280x720 and FPS to 15 to ease load on Raspberry Pi 4
- Increased mediamtx writeQueueSize to handle multiple simultaneous consumers
- Added JPEG snapshot HTTP server on port 8766 for HA dashboard thumbnails
- Added bitrate cap on ffmpeg encoder (~1000k)

## 1.6.1
- Fixed deprecation: replaced getMxId() with getDeviceId() for DepthAI v3

## 1.6.0
- Replaced ffmpeg-as-RTSP-server with mediamtx (a dedicated RTSP server)
- ffmpeg now publishes raw frames to mediamtx via RTSP rather than serving directly
- Added mediamtx.yml configuration
- Stream available at rtsp://<ha-ip>:8765/stream
- mediamtx started by run.sh before the Python bridge

## 1.5.0
- Replaced MJPEG HTTP stream with RTSP via ffmpeg for HA camera.record compatibility
- RTSP stream compatible with HA Generic Camera integration

## 1.4.0
- Rewrote pipeline for DepthAI v3 API (breaking changes from v2)
- Replaced dai.node.ColorCamera with dai.node.Camera + .build()
- Replaced XLinkOut / getOutputQueue with v3 createOutputQueue()
- Pipeline now uses pipeline.start() and pipeline.isRunning()
- Device connection established before pipeline creation (v3 requirement)

## 1.3.0
- Fixed camera node API: replaced deprecated setBoardSocket with v3 equivalent
- Fixed ImageManip: replaced setResize with setOutputSize

## 1.2.0
- Added host_network: true so depthai can reach PoE camera via UDP autodiscovery
- Added explicit TCP/IP protocol and bootloader state to DeviceInfo for PoE
- Moved pipeline build inside camera retry loop

## 1.1.0
- Fixed Dockerfile: replaced Alpine Linux (apk) with Debian (apt-get)
- Added Luxonis ARM wheel index for depthai pip install on aarch64
- Fixed config.yaml map syntax and removed incorrect image: field

## 1.0.0
- Initial release
- DepthAI v2 pipeline with ColorCamera node
- MJPEG HTTP stream on port 8765
- Frame-differencing motion detection
- Home Assistant events: oak_camera_motion_started, oak_camera_motion_stopped
