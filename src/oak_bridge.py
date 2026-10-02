"""
OAK-D LR  →  Home Assistant Bridge  (DepthAI v3 + threaded pipeline)
---------------------------------------------------------------------
Threads:
  1 camera     — captures raw frames from OAK-D LR
  2 detection  — per-object confidence filtering + overlay drawing
  3 rtsp       — pushes display frames to ffmpeg/mediamtx
  4 recorder   — writes motion clips; tags filenames with detected objects
  5 snapshot   — updates JPEG snapshot
  6 http       — serves snapshot over HTTP
  7 storage    — monitors disk usage and fires HA alerts
"""

import os, cv2, depthai as dai, threading, queue, time, shutil
import logging, requests, subprocess, re, json
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from datetime import datetime
from collections import deque
import settings_page as _settings_page
import oak_paths
import oak_logging
import oak_runtime

# The launcher configures logging before it imports this module. A direct run of
# this file configures it here instead, so the log always reaches a file.
if not logging.getLogger().handlers:
    oak_logging.setup_logging()
log = logging.getLogger("oak-bridge")

# ==============================================================================
# Class label lists
# ==============================================================================

COCO_80_CLASSES = [
    "person","bicycle","car","motorcycle","airplane","bus","train","truck",
    "boat","traffic light","fire hydrant","stop sign","parking meter","bench",
    "bird","cat","dog","horse","sheep","cow","elephant","bear","zebra","giraffe",
    "backpack","umbrella","handbag","tie","suitcase","frisbee","skis","snowboard",
    "sports ball","kite","baseball bat","baseball glove","skateboard","surfboard",
    "tennis racket","bottle","wine glass","cup","fork","knife","spoon","bowl",
    "banana","apple","sandwich","orange","broccoli","carrot","hot dog","pizza",
    "donut","cake","chair","couch","potted plant","bed","dining table","toilet",
    "tv","laptop","mouse","remote","keyboard","cell phone","microwave","oven",
    "toaster","sink","refrigerator","book","clock","vase","scissors","teddy bear",
    "hair drier","toothbrush",
]

MOBILENET_CLASSES = [
    "background","aeroplane","bicycle","bird","boat","bottle","bus","car","cat",
    "chair","cow","diningtable","dog","horse","motorbike","person","pottedplant",
    "sheep","sofa","train","tvmonitor",
]

# ==============================================================================
# Category → class membership (all 80 COCO classes covered)
# ==============================================================================

CATEGORY_CLASSES = {
    "people":      {"person"},
    "animals":     {"bird","cat","dog","horse","sheep","cow","elephant","bear","zebra","giraffe"},
    "vehicles":    {"bicycle","car","motorcycle","airplane","bus","train","truck","boat"},
    "food":        {"banana","apple","sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake"},
    "kitchen":     {"bottle","wine glass","cup","fork","knife","spoon","bowl","microwave","oven","toaster","sink","refrigerator"},
    "furniture":   {"chair","couch","potted plant","bed","dining table","toilet","clock","vase","scissors","teddy bear"},
    "electronics": {"tv","laptop","mouse","remote","keyboard","cell phone"},
    "sports":      {"frisbee","skis","snowboard","sports ball","kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket"},
    "accessories": {"backpack","umbrella","handbag","tie","suitcase","book","hair drier","toothbrush"},
    "outdoor":     {"traffic light","fire hydrant","stop sign","parking meter","bench"},
}

# MobileNet SSD name mappings (PASCAL VOC → COCO equivalent where they differ)
MOBILENET_REMAP = {
    "aeroplane": "airplane", "motorbike": "motorcycle",
    "diningtable": "dining table", "pottedplant": "potted plant",
    "sofa": "couch", "tvmonitor": "tv",
}

# Colour per category for bounding boxes
CATEGORY_COLORS = {
    "people":      (0,   200,   0),
    "animals":     (0,   165, 255),
    "vehicles":    (255, 100,   0),
    "food":        (0,   220, 220),
    "kitchen":     (100, 180, 255),
    "furniture":   (200,   0, 200),
    "electronics": (0,   255, 255),
    "sports":      (180, 100, 255),
    "accessories": (200, 200,   0),
    "outdoor":     (0,     0, 220),
    "other":       (180, 180, 180),
}

# Model definitions. The archive lives in the resolved models folder: /models
# in the add-on, or a models folder beside the executable when portable.
YOLO11N_LOCAL_PATH = os.path.join(oak_paths.models_dir(), "yolo11n.tar.xz")

MODELS = {
    "yolov6-nano": {
        "display":  "YOLOv6 Nano (fastest, 80 classes)",
        "classes":  COCO_80_CLASSES,
    },
    "luxonis/mobilenet-ssd:300x300": {
        "display":  "MobileNet SSD (lightest, 20 classes)",
        "classes":  MOBILENET_CLASSES,
        "remap":    MOBILENET_REMAP,
    },
    "yolo11n": {
        "display":    "YOLO11n (accurate, 80 classes, may be slower on RVC2)",
        "classes":    COCO_80_CLASSES,
        "local_path": YOLO11N_LOCAL_PATH,
    },
}

# ==============================================================================
# Config — read environment variables
# ==============================================================================

def _bool(key, default="false"):
    return os.environ.get(key, default).lower() == "true"

def _float(key, default):
    try:    return float(os.environ.get(key, default))
    except: return float(default)

def _int(key, default):
    try:    return int(os.environ.get(key, default))
    except: return int(default)

CAMERA_IP             = os.environ.get("CAMERA_IP", "").strip() or None
RTSP_PORT             = _int("MJPEG_PORT", 8765)
SNAPSHOT_PORT         = RTSP_PORT + 1
FPS                   = _int("FPS", 15)
DETECTION_MODEL       = os.environ.get("DETECTION_MODEL", "yolov6-nano").strip()
STORAGE_ALERT_ENABLED = _bool("STORAGE_ALERT_ENABLED", "true")
STORAGE_ALERT_THRESHOLD = _int("STORAGE_ALERT_THRESHOLD", 50)
HA_URL                = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN              = os.environ.get("HA_TOKEN", "").strip()
FILENAME_TAG_OBJECTS  = _bool("FILENAME_TAG_OBJECTS", "true")

# OBJECT_THRESHOLDS: {class_name: confidence} — sole source of truth for detection.
# Populated entirely by the web settings panel (_apply_settings_to_thresholds).
# Empty at module load; filled when saved settings are loaded below.
OBJECT_THRESHOLDS: dict[str, float] = {}

# Build reverse map: class_name → category (for colours)
CLASS_TO_CATEGORY: dict[str, str] = {}
for _cat, _classes in CATEGORY_CLASSES.items():
    for _cls in _classes:
        CLASS_TO_CATEGORY[_cls] = _cat

# Hardware threshold — updated by _apply_settings_to_thresholds after settings load.
# 0.10 initial value is safe; the camera thread reads this after startup delay.
HARDWARE_THRESHOLD = 0.10

# Minimum seconds an object must be visible to appear in filename tag
TAG_DURATION_SECONDS = 0.0
OBJECT_OVERRIDES_RAW = ""  # not used — settings panel handles per-object overrides

# Default settings applied when no saved file exists:
# people + animals ON at 0.70, everything else OFF
DEFAULT_SETTINGS = {
    "hw_threshold": 0.10,
    "tag_duration": 0.0,
    "objects": {
        **{cls: {"enabled": True,  "confidence": 0.50}
           for cls in (list(CATEGORY_CLASSES["people"]) +
                       list(CATEGORY_CLASSES["animals"]))},
        **{cls: {"enabled": False, "confidence": 0.50}
           for cat, clss in CATEGORY_CLASSES.items()
           if cat not in ("people", "animals")
           for cls in clss},
    }
}

if DETECTION_MODEL not in MODELS:
    log.warning(f"Unknown model '{DETECTION_MODEL}' — falling back to yolov6-nano")
    DETECTION_MODEL = "yolov6-nano"

if DETECTION_MODEL == "yolo11n" and not os.path.exists(MODELS["yolo11n"].get("local_path","")):
    log.warning(f"yolo11n selected but {YOLO11N_LOCAL_PATH} not found "
                f"— falling back to yolov6-nano")
    DETECTION_MODEL = "yolov6-nano"

MODEL_CFG    = MODELS[DETECTION_MODEL]
CLASS_LABELS = MODEL_CFG["classes"]
LABEL_REMAP  = MODEL_CFG.get("remap", {})   # MobileNet VOC→COCO name fix

# Constants
FRAME_WIDTH           = 1280
FRAME_HEIGHT          = 720
PRE_ROLL_SECONDS      = 3
POST_ROLL_SECONDS     = 5
MAX_CLIP_SECONDS      = 120
RECORDINGS_DIR        = oak_paths.recordings_dir()
STORAGE_CHECK_INTERVAL= 300
MAX_FILENAME_OBJECTS  = 10

POST_ROLL_FRAMES  = FPS * POST_ROLL_SECONDS
PRE_ROLL_FRAMES   = FPS * PRE_ROLL_SECONDS
MAX_CLIP_FRAMES   = FPS * MAX_CLIP_SECONDS
RTSP_PUBLISH_URL  = f"rtsp://localhost:{RTSP_PORT}/stream"

if FPS > 20:
    log.warning(f"FPS={FPS} may cause instability on Pi 4 — consider 15-20")

# Startup log — thresholds will be logged properly after settings load below
log.info(f"Model: {MODEL_CFG['display']}")
log.info(f"FPS: {FPS}")
log.info(f"Storage alerts: {'enabled' if STORAGE_ALERT_ENABLED else 'disabled'} "
         f"(threshold: {STORAGE_ALERT_THRESHOLD}%)")
log.info(f"Filename object tagging: {'enabled' if FILENAME_TAG_OBJECTS else 'disabled'}")

# ==============================================================================
# Shared state
# ==============================================================================

raw_q    = queue.Queue(maxsize=8)
rtsp_q   = queue.Queue(maxsize=8)
record_q = queue.Queue(maxsize=PRE_ROLL_FRAMES + 30)  # (frame, [triggered_labels])
snap_q   = queue.Queue(maxsize=2)

detection_active = False
detection_lock   = threading.Lock()
latest_jpeg      = None
latest_jpeg_lock = threading.Lock()
frame_event      = threading.Event()   # fires each time a new JPEG is ready
ffmpeg_proc      = None

# Set once when the program must stop. Every loop that can block checks it, so
# a tray Quit, a settings panel Shutdown and Ctrl-C all end the process.
shutdown_event   = threading.Event()

# The launcher owns mediamtx, so it registers a stopper here. shutdown_children
# then stops every child the program started, whoever started it.
_cleanup_hooks: list = []


def register_cleanup(func) -> None:
    """Add a callable that shutdown_children must run. The launcher uses this."""
    _cleanup_hooks.append(func)


def shutdown_children() -> None:
    """Stop ffmpeg and every registered child process. Safe to call twice."""
    global ffmpeg_proc
    if ffmpeg_proc is not None:
        try:
            ffmpeg_proc.terminate()
            ffmpeg_proc.wait(timeout=5)
        except Exception:
            try:    ffmpeg_proc.kill()
            except Exception: pass
        ffmpeg_proc = None

    for hook in _cleanup_hooks:
        try:
            hook()
        except Exception as e:
            log.error(f"Cleanup hook failed: {e}")


def request_shutdown() -> None:
    """Stop the program. Called by the tray, the settings panel and signals."""
    if shutdown_event.is_set():
        return
    log.info("Shutting down")
    shutdown_event.set()
    shutdown_children()
    logging.shutdown()
    # The worker threads are daemons and some block on the camera, so a plain
    # return would hang. Exit the interpreter directly.
    os._exit(0)

# Settings persistence
SETTINGS_PATH  = os.path.join(oak_paths.data_dir(), "oak_settings.json")
settings_lock  = threading.Lock()
_SETTINGS_HTML = _settings_page.build_settings_html()


SETTINGS_VERSION = "2.3.3"  # bump this whenever defaults change


def _load_settings_file() -> dict:
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH) as f:
                data = json.load(f)
            # If saved settings are from an older version, reset to defaults
            # so users always get the current defaults on upgrade
            saved_version = data.get("_version", "0")
            if saved_version != SETTINGS_VERSION:
                log.info(f"Settings version mismatch ({saved_version} vs {SETTINGS_VERSION}) "                         f"— resetting to defaults")
                return {}
            return data
    except Exception as e:
        log.warning(f"Could not load settings file: {e}")
    return {}


def _save_settings_file(data: dict):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    data["_version"] = SETTINGS_VERSION
    # Also persist the current hw_threshold back into the file
    if "hw_threshold" not in data:
        data["hw_threshold"] = DEFAULT_SETTINGS.get("hw_threshold", 0.10)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _apply_settings_to_thresholds(data: dict):
    """Rebuild OBJECT_THRESHOLDS and HARDWARE_THRESHOLD from settings data.
    Uses DEFAULT_SETTINGS as a base when data is empty (first run / reset).
    """
    global HARDWARE_THRESHOLD
    # Merge defaults with saved data so first-run always has people+animals on
    merged = {}
    for cls, cfg in DEFAULT_SETTINGS["objects"].items():
        merged[cls] = dict(cfg)  # copy defaults
    for label, cfg in data.get("objects", {}).items():
        merged[label] = cfg  # saved settings override defaults

    new_thresh: dict = {}
    for label, cfg in merged.items():
        if cfg.get("enabled", True):
            conf = cfg.get("confidence", 0.50)
            if conf > 0:
                new_thresh[label] = float(conf)

    with settings_lock:
        OBJECT_THRESHOLDS.clear()
        OBJECT_THRESHOLDS.update(new_thresh)

    global TAG_DURATION_SECONDS
    # Update hardware threshold
    saved_hw = data.get("hw_threshold", DEFAULT_SETTINGS.get("hw_threshold", 0.10))
    HARDWARE_THRESHOLD = max(0.05, float(saved_hw))

    # Update filename tag duration
    saved_td = data.get("tag_duration", DEFAULT_SETTINGS.get("tag_duration", 2.0))
    TAG_DURATION_SECONDS = max(0.0, float(saved_td))

    active_count = len(OBJECT_THRESHOLDS)
    log.info(f"Settings applied — {active_count} active objects, "
             f"hw threshold {HARDWARE_THRESHOLD:.2f}, "
             f"tag duration {TAG_DURATION_SECONDS:.1f}s")


def _get_current_settings_json() -> dict:
    """Build the full settings dict for the UI — merges live state with defaults."""
    data: dict = {}
    for cls, default_cfg in DEFAULT_SETTINGS["objects"].items():
        with settings_lock:
            thresh = OBJECT_THRESHOLDS.get(cls)
        enabled = thresh is not None
        conf    = thresh if thresh is not None else default_cfg.get("confidence", 0.70)
        data[cls] = {"enabled": enabled, "confidence": round(conf, 4)}
    return {"objects": data, "hw_threshold": round(HARDWARE_THRESHOLD, 4),
            "tag_duration": round(TAG_DURATION_SECONDS, 4)}


# Apply any saved settings on startup
_apply_settings_to_thresholds(_load_settings_file())

# ==============================================================================
# Helpers
# ==============================================================================

def get_color(label: str) -> tuple:
    cat = CLASS_TO_CATEGORY.get(label, "other")
    return CATEGORY_COLORS.get(cat, CATEGORY_COLORS["other"])


def label_text_color(bg_color: tuple) -> tuple:
    """Return black or white text colour for maximum contrast on bg_color (BGR)."""
    b, g, r = bg_color
    # Perceived luminance (sRGB formula adapted for BGR)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (0, 0, 0) if luminance > 160 else (255, 255, 255)


def fire_ha_event(event_type, data):
    if not HA_TOKEN: return
    try:
        requests.post(f"{HA_URL}/api/events/{event_type}", json=data,
                      headers={"Authorization": f"Bearer {HA_TOKEN}",
                               "Content-Type": "application/json"},
                      timeout=5).raise_for_status()
        log.info(f"Fired HA event: {event_type}")
    except Exception as e:
        log.error(f"HA event failed: {e}")


def send_ha_notification(title, message):
    if not HA_TOKEN: return
    try:
        requests.post(f"{HA_URL}/api/services/persistent_notification/create",
                      json={"title": title, "message": message,
                            "notification_id": "oak_camera_storage"},
                      headers={"Authorization": f"Bearer {HA_TOKEN}",
                               "Content-Type": "application/json"},
                      timeout=5).raise_for_status()
    except Exception as e:
        log.error(f"HA notification failed: {e}")


def update_storage_sensor(pct, used_gb, total_gb, free_gb):
    if not HA_TOKEN: return
    try:
        requests.post(f"{HA_URL}/api/states/sensor.oak_camera_storage",
                      json={"state": str(pct),
                            "attributes": {
                                "unit_of_measurement": "%",
                                "friendly_name": "OAK Camera Storage Used",
                                "icon": "mdi:harddisk",
                                "used_gb": round(used_gb, 2),
                                "free_gb": round(free_gb, 2),
                                "total_gb": round(total_gb, 2),
                                "recordings_folder": RECORDINGS_DIR,
                                "alert_threshold": STORAGE_ALERT_THRESHOLD,
                                "alert_enabled": STORAGE_ALERT_ENABLED,
                            }},
                      headers={"Authorization": f"Bearer {HA_TOKEN}",
                               "Content-Type": "application/json"},
                      timeout=5).raise_for_status()
    except Exception as e:
        log.error(f"Storage sensor update failed: {e}")

# ==============================================================================
# Detection overlay — per-object confidence filtering
# ==============================================================================

def draw_detections(frame, detections) -> list[str]:
    """Draw boxes on frame. Returns list of triggered class names that passed
    per-object confidence thresholds."""
    triggered = []
    for det in detections:
        raw_label = (CLASS_LABELS[det.label]
                     if det.label < len(CLASS_LABELS) else f"class_{det.label}")
        # Apply MobileNet VOC→COCO name remapping if needed
        label = LABEL_REMAP.get(raw_label, raw_label)

        # Per-object threshold check
        threshold = OBJECT_THRESHOLDS.get(label)
        if threshold is None:
            continue  # class not enabled
        if det.confidence < threshold:
            continue  # below per-object threshold

        color = get_color(label)
        x1 = int(det.xmin * FRAME_WIDTH)
        y1 = int(det.ymin * FRAME_HEIGHT)
        x2 = int(det.xmax * FRAME_WIDTH)
        y2 = int(det.ymax * FRAME_HEIGHT)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label} {det.confidence:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1-th-6), (x1+tw+4, y1), color, -1)
        cv2.putText(frame, text, (x1+2, y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, label_text_color(color), 1)
        triggered.append(label)
    return triggered

# ==============================================================================
# Motion recorder
# ==============================================================================

def _safe_filename_label(label: str) -> str:
    """Convert a class name to a filesystem-safe string."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", label).strip("_")


class MotionRecorder:
    def __init__(self):
        self.writer      = None
        self.clip_path   = None
        self.frame_count = 0
        os.makedirs(RECORDINGS_DIR, exist_ok=True)

    def start(self, pre_roll_frames):
        try:
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            tp = os.path.join(RECORDINGS_DIR, ".writetest")
            open(tp, "w").close(); os.remove(tp)
        except Exception as e:
            log.error(f"Recordings dir not writable: {e}"); return False

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.clip_path = os.path.join(RECORDINGS_DIR, f"motion_{ts}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(
            self.clip_path, fourcc, FPS, (FRAME_WIDTH, FRAME_HEIGHT))
        if not self.writer.isOpened():
            log.error(f"VideoWriter failed: {self.clip_path}")
            self.writer = None; self.clip_path = None; return False

        for f in pre_roll_frames:
            self.writer.write(f)
        self.frame_count = len(pre_roll_frames)
        log.info(f"Recording started: {self.clip_path} "
                 f"({self.frame_count} pre-roll frames)")
        return True

    def write(self, frame):
        if self.writer:
            self.writer.write(frame)
            self.frame_count += 1

    def stop(self, confirmed_objects: set | None = None):
        if not self.writer:
            return
        self.writer.release()
        self.writer = None
        duration = self.frame_count / FPS

        final_path = self.clip_path
        if FILENAME_TAG_OBJECTS and confirmed_objects:
            # Sort alphabetically, cap at MAX_FILENAME_OBJECTS, make filesystem-safe
            tags = sorted(_safe_filename_label(o)
                          for o in confirmed_objects)[:MAX_FILENAME_OBJECTS]
            if tags:
                base, ext = os.path.splitext(self.clip_path)
                tagged_path = f"{base}-{'_'.join(tags)}{ext}"
                try:
                    os.rename(self.clip_path, tagged_path)
                    final_path = tagged_path
                except Exception as e:
                    log.warning(f"Could not rename clip: {e}")

        log.info(f"Recording saved: {final_path} "
                 f"({duration:.1f}s, {self.frame_count} frames)"
                 f"{' tags:'+str(sorted(confirmed_objects)) if confirmed_objects else ''}")
        self.clip_path = None
        self.frame_count = 0

    def is_recording(self): return self.writer is not None
    def is_too_long(self):  return self.frame_count >= MAX_CLIP_FRAMES

# ==============================================================================
# ffmpeg publisher
# ==============================================================================

def start_ffmpeg():
    """Start the RTSP publisher. Return None when ffmpeg is not installed.

    The portable build may ship without ffmpeg to keep the download small. The
    caller treats None as no RTSP and leaves the other outputs running.
    """
    exe = oak_runtime.resolve_binary("ffmpeg")
    if exe is None:
        return None

    cmd = [exe, "-loglevel", "warning",
           "-f", "rawvideo", "-pixel_format", "bgr24",
           "-video_size", f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
           "-framerate", str(FPS), "-i", "pipe:0",
           "-c:v", "libx264", "-preset", "ultrafast",
           "-tune", "zerolatency", "-b:v", "1000k",
           # One keyframe per second. Without -g, x264 uses one every 250
           # frames, and a viewer that connects mid-stream cannot draw a
           # picture until the next keyframe: AnyCam measured 19-28 s.
           "-g", str(FPS),
           "-f", "rtsp", "-rtsp_transport", "tcp", RTSP_PUBLISH_URL]
    log.info(f"Starting ffmpeg → {RTSP_PUBLISH_URL}")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=oak_runtime.child_creation_flags())
    # Without a console, ffmpeg errors vanish. Copy them into the log file.
    oak_logging.drain_pipe(proc.stderr, "ffmpeg", logging.WARNING)
    return proc

# ==============================================================================
# Thread 1 — Camera capture
# ==============================================================================

def camera_thread():
    time.sleep(3)  # let previous session release
    while True:
        try:
            if CAMERA_IP:
                log.info(f"Connecting to OAK-D LR at {CAMERA_IP}...")
                di = dai.DeviceInfo(CAMERA_IP)
                di.protocol = dai.XLinkProtocol.X_LINK_TCP_IP
                di.state    = dai.XLinkDeviceState.X_LINK_BOOTLOADER
                device = dai.Device(di)
            else:
                log.info("Auto-discovering OAK-D LR...")
                device = dai.Device()

            with device:
                log.info(f"Connected: {device.getDeviceId()}")
                pipeline = dai.Pipeline(device)
                cam      = pipeline.create(dai.node.Camera).build()

                local_path = MODEL_CFG.get("local_path")
                if local_path:
                    if not os.path.exists(local_path):
                        raise FileNotFoundError(f"Local model not found: {local_path}")
                    log.info(f"Loading model: {DETECTION_MODEL} (local: {local_path})")
                    nn_archive = dai.NNArchive(local_path)
                    det_net = pipeline.create(dai.node.DetectionNetwork).build(
                        cam, nn_archive, fps=FPS)
                else:
                    log.info(f"Loading model: {DETECTION_MODEL} (Hub cache)")
                    model_desc = dai.NNModelDescription(
                        DETECTION_MODEL, platform=device.getPlatformAsString())
                    model_path = dai.getModelFromZoo(model_desc, useCached=True)
                    nn_archive = dai.NNArchive(model_path)
                    det_net = pipeline.create(dai.node.DetectionNetwork).build(
                        cam, nn_archive, fps=FPS)

                # Set hardware threshold from current global value.
                # HARDWARE_THRESHOLD is updated by the settings panel so changes
                # take effect on the next camera reconnect cycle.
                det_net.setConfidenceThreshold(HARDWARE_THRESHOLD)
                log.info(f"Hardware threshold set to {HARDWARE_THRESHOLD:.2f} "
                         f"(per-object thresholds enforced in Python)")

                video_out = cam.requestOutput(
                    (FRAME_WIDTH, FRAME_HEIGHT),
                    type=dai.ImgFrame.Type.BGR888p, fps=FPS)
                video_q = video_out.createOutputQueue(maxSize=4, blocking=False)
                det_q   = det_net.out.createOutputQueue(maxSize=4, blocking=False)

                pipeline.start()
                log.info(f"Pipeline running — {MODEL_CFG['display']} @ {FPS}fps "
                         f"(hw threshold {HARDWARE_THRESHOLD:.2f})")

                last_detections = []  # persist until next result arrives
                while pipeline.isRunning():
                    in_frame = video_q.get()
                    if in_frame is None: continue
                    # Only update detections when a new result is ready.
                    # Reuse last_detections otherwise so boxes stay visible
                    # between NN inference cycles (important when NN is slower
                    # than camera FPS, e.g. YOLO11n on RVC2 at 15fps)
                    if det_q.has():
                        msg = det_q.get()
                        if msg is not None:
                            last_detections = msg.detections
                    try:
                        raw_q.put_nowait((in_frame.getCvFrame(), last_detections))
                    except queue.Full:
                        pass

        except Exception as e:
            log.error(f"Camera error: {e} — retrying in 10s...")
            time.sleep(10)

# ==============================================================================
# Thread 2 — Detection + overlay + state machine
# ==============================================================================

def detection_thread():
    global detection_active
    post_roll_counter  = 0
    # Small grace buffer: require N consecutive frames with no detection
    # before counting down post-roll. Prevents rapid on/off flickering
    # when the NN runs slower than camera FPS.
    no_detect_streak   = 0
    NO_DETECT_GRACE    = max(2, FPS // 5)  # ~3 frames at 15fps

    # Overlay drawing constants — defined once outside the frame loop
    # All three overlay elements (status, timestamp, model) share these
    _OV_FONT  = cv2.FONT_HERSHEY_SIMPLEX
    _OV_SCALE = 0.38
    _OV_THICK = 1
    _OV_BG    = (30, 30, 30)
    _OV_PAD   = 5

    def _draw_label_box(img, text, txt_color, x, y):
        """Draw dark background box with coloured text. All overlay elements use this."""
        (tw, th), _ = cv2.getTextSize(text, _OV_FONT, _OV_SCALE, _OV_THICK)
        cv2.rectangle(img, (x - _OV_PAD, y - th - _OV_PAD),
                      (x + tw + _OV_PAD, y + _OV_PAD), _OV_BG, -1)
        cv2.putText(img, text, (x, y), _OV_FONT, _OV_SCALE, txt_color, _OV_THICK)

    while True:
        try:
            frame, detections = raw_q.get(timeout=5)
        except queue.Empty:
            continue

        display   = frame.copy()
        triggered = draw_detections(display, detections)
        detected  = len(triggered) > 0

        if detected:
            no_detect_streak = 0
        else:
            no_detect_streak += 1

        # Only treat as "no detection" after grace frames in a row
        effectively_detected = detected or (no_detect_streak < NO_DETECT_GRACE)

        with detection_lock:
            active = detection_active

        # Status overlay
        if active:
            label_text = (f"RECORDING - {', '.join(sorted(set(triggered)))}"
                          if triggered else "RECORDING")
            color = (0, 0, 220)
        else:
            label_text = "Monitoring"
            color = (180, 180, 180)

        # Status box — top left
        _draw_label_box(display, label_text, color, 8, 20)

        # Timestamp — top right
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        (ts_w, ts_h), _ = cv2.getTextSize(ts, _OV_FONT, _OV_SCALE, _OV_THICK)
        _draw_label_box(display, ts, (200, 200, 200),
                        FRAME_WIDTH - ts_w - _OV_PAD * 2 - 3, 20)

        # Model name — top right, below timestamp
        model_name = MODEL_CFG["display"].split(" (")[0]
        (mn_w, mn_h), _ = cv2.getTextSize(model_name, _OV_FONT, _OV_SCALE, _OV_THICK)
        _draw_label_box(display, model_name, (160, 160, 160),
                        FRAME_WIDTH - mn_w - _OV_PAD * 2 - 3,
                        20 + ts_h + _OV_PAD * 2 + 3)

        # Detection state machine
        if effectively_detected:
            if detected:  # only reset post-roll counter on real detections
                post_roll_counter = POST_ROLL_FRAMES
            with detection_lock:
                if not detection_active and detected:
                    detection_active = True
                    log.info(f"Detection: {', '.join(sorted(set(triggered)))}")
                    fire_ha_event("oak_camera_motion_started", {
                        "timestamp": datetime.now().isoformat(),
                        "camera": "OAK-D LR",
                        "detected": sorted(set(triggered)),
                        "model": DETECTION_MODEL,
                    })
        else:
            with detection_lock:
                if detection_active:
                    post_roll_counter -= 1
                    if post_roll_counter <= 0:
                        detection_active = False
                        log.info("Detection ended")
                        fire_ha_event("oak_camera_motion_stopped", {
                            "timestamp": datetime.now().isoformat(),
                            "camera": "OAK-D LR",
                        })

        # Fan out — record_q carries (frame, triggered) for filename tagging
        for q in (rtsp_q, snap_q):
            try: q.put_nowait(display)
            except queue.Full: pass
        try:
            record_q.put_nowait((display, triggered))
        except queue.Full:
            pass

# ==============================================================================
# Thread 3 — RTSP publisher
# ==============================================================================

def rtsp_thread():
    global ffmpeg_proc
    ffmpeg_proc = start_ffmpeg()
    if ffmpeg_proc is None:
        log.warning("ffmpeg not found — RTSP stream disabled. "
                    "The MJPEG feed, snapshots and recording still run.")
        # Drain the queue so the detection thread never blocks on a full queue.
        while not shutdown_event.is_set():
            try:    rtsp_q.get(timeout=5)
            except queue.Empty: continue
        return
    time.sleep(2)

    while not shutdown_event.is_set():
        try:
            frame = rtsp_q.get(timeout=5)
        except queue.Empty:
            continue

        # shutdown_children sets ffmpeg_proc to None, so re-read it once and
        # leave the loop if the program is stopping. Without this check a
        # restart raises AttributeError on None.poll and writes a traceback to
        # the log, which is the only diagnostic a windowed build has.
        proc = ffmpeg_proc
        if proc is None:
            break

        if proc.poll() is not None:
            log.warning("ffmpeg died — restarting...")
            ffmpeg_proc = start_ffmpeg(); time.sleep(2)
            continue
        try:
            proc.stdin.write(frame.tobytes())
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            if shutdown_event.is_set():
                break
            log.warning("ffmpeg pipe broken — restarting...")
            ffmpeg_proc = start_ffmpeg(); time.sleep(2)

    log.info("RTSP publisher stopped")

# ==============================================================================
# Thread 4 — Recorder  (tracks per-object sighting duration for filename tags)
# ==============================================================================

def recorder_thread():
    recorder = MotionRecorder()
    pre_roll = deque(maxlen=PRE_ROLL_FRAMES)  # stores plain frames
    object_frame_counts: dict[str, int] = {}  # label → frames seen this clip
    confirmed_objects:   set[str]       = set()  # seen >= MIN_TAG_FRAMES

    log.info("Waiting for recordings directory...")
    for _ in range(10):
        try:
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            tp = os.path.join(RECORDINGS_DIR, ".startuptest")
            open(tp, "w").close(); os.remove(tp)
            log.info(f"Recordings directory ready: {RECORDINGS_DIR}"); break
        except Exception: time.sleep(1)
    else:
        log.warning("Could not verify recordings directory")

    while True:
        try:
            frame, triggered_labels = record_q.get(timeout=5)
        except queue.Empty:
            continue

        with detection_lock:
            active = detection_active

        if active:
            if not recorder.is_recording():
                object_frame_counts = {}
                confirmed_objects   = set()
                recorder.start(pre_roll)  # pre_roll holds plain frames

            if recorder.is_recording():
                # Track how long each object has been visible
                for label in triggered_labels:
                    object_frame_counts[label] = object_frame_counts.get(label, 0) + 1
                    if object_frame_counts[label] >= max(1, TAG_DURATION_SECONDS * FPS):
                        confirmed_objects.add(label)

                recorder.write(frame)
                if recorder.is_too_long():
                    log.info("Max clip length — splitting")
                    recorder.stop(confirmed_objects)
                    object_frame_counts = {}
                    confirmed_objects   = set()
                    recorder.start(deque())
        else:
            if recorder.is_recording():
                recorder.stop(confirmed_objects)
                object_frame_counts = {}
                confirmed_objects   = set()
            # Store only the frame (not labels) in pre-roll
            pre_roll.append(frame)

# ==============================================================================
# Thread 5 — Snapshot
# ==============================================================================

def snapshot_thread():
    global latest_jpeg
    while True:
        try:
            frame = snap_q.get(timeout=5)
        except queue.Empty:
            continue
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with latest_jpeg_lock:
                latest_jpeg = buf.tobytes()
            frame_event.set()   # wake any waiting MJPEG clients
            frame_event.clear()

# ==============================================================================
# Thread 6 — HTTP snapshot server
# ==============================================================================

class SnapshotHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/snapshot":
            with latest_jpeg_lock:
                data = latest_jpeg
            if data:
                self._send(200, "image/jpeg", data)
            else:
                self._send(503, "text/plain", b"No frame yet")
        elif self.path in ("/settings", "/settings/"):
            self._send(200, "text/html; charset=utf-8",
                       _SETTINGS_HTML.encode("utf-8"))
        elif self.path == "/api/settings":
            body = json.dumps(_get_current_settings_json()).encode("utf-8")
            self._send(200, "application/json", body)
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw    = self.rfile.read(length)
                data   = json.loads(raw)
                _save_settings_file(data)
                _apply_settings_to_thresholds(data)
                self._send(200, "application/json", b'{"ok":true}')
            except Exception as e:
                log.error(f"Settings save failed: {e}")
                self._send(400, "text/plain", str(e).encode())
        else:
            self._send(404, "text/plain", b"Not found")

    def do_DELETE(self):
        if self.path == "/api/settings":
            try:
                if os.path.exists(SETTINGS_PATH):
                    os.remove(SETTINGS_PATH)
                _apply_settings_to_thresholds({})
                self._send(200, "application/json", b'{"ok":true}')
            except Exception as e:
                self._send(400, "text/plain", str(e).encode())
        else:
            self._send(404, "text/plain", b"Not found")

def http_thread():
    server = HTTPServer(("0.0.0.0", SNAPSHOT_PORT), SnapshotHandler)
    log.info(f"Snapshot server on :{SNAPSHOT_PORT}")
    server.serve_forever()


# ==============================================================================
# Thread 8 — HA Ingress settings panel (port 8767)
# HA Ingress proxies requests to this port and embeds the result in the HA UI.
# All URLs in the served HTML must be RELATIVE so the ingress path prefix
# is preserved in the browser and correctly proxied back to us.
# ==============================================================================

INGRESS_PORT = 8767


class IngressHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", ""):
            self._send(200, "text/html; charset=utf-8",
                       _SETTINGS_HTML.encode("utf-8"))
        elif path == "/api/settings":
            body = json.dumps(_get_current_settings_json()).encode("utf-8")
            self._send(200, "application/json", body)
        elif path == "/stream":
            # MJPEG stream — browsers display this natively in an <img> tag
            boundary = b"--oakframe"
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=oakframe")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    frame_event.wait(timeout=2.0)
                    with latest_jpeg_lock:
                        jpg = latest_jpeg
                    if jpg is None:
                        continue
                    header = (boundary
                              + b"\r\nContent-Type: image/jpeg\r\n"
                              + b"Content-Length: "
                              + str(len(jpg)).encode()
                              + b"\r\n\r\n")
                    self.wfile.write(header + jpg + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass   # client disconnected — normal
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", 0))
                data   = json.loads(self.rfile.read(length))
                _save_settings_file(data)
                _apply_settings_to_thresholds(data)
                self._send(200, "application/json", b'{"ok":true}')
            except Exception as e:
                log.error(f"Ingress settings save failed: {e}")
                self._send(400, "text/plain", str(e).encode())
        elif path == "/api/restart":
            self._send(200, "application/json", b'{"ok":true}')
            log.info("Restart requested via settings panel")
            # Hand over to a fresh process. This works with no service manager,
            # so the add-on, the portable build and a source run all restart.
            threading.Thread(target=oak_runtime.restart_process,
                             args=(shutdown_children,),
                             name="restart", daemon=False).start()
        elif path == "/api/shutdown":
            self._send(200, "application/json", b'{"ok":true}')
            log.info("Shutdown requested via settings panel")
            threading.Thread(target=request_shutdown,
                             name="shutdown", daemon=False).start()
        else:
            self._send(404, "text/plain", b"Not found")

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path == "/api/settings":
            try:
                if os.path.exists(SETTINGS_PATH):
                    os.remove(SETTINGS_PATH)
                _apply_settings_to_thresholds({})
                self._send(200, "application/json", b'{"ok":true}')
            except Exception as e:
                self._send(400, "text/plain", str(e).encode())
        else:
            self._send(404, "text/plain", b"Not found")


def ingress_thread():
    # ThreadingHTTPServer so MJPEG stream connections don't block the API
    server = ThreadingHTTPServer(("0.0.0.0", INGRESS_PORT), IngressHandler)
    server.daemon_threads = True
    log.info(f"Ingress panel on :{INGRESS_PORT} (MJPEG stream + settings API)")
    server.serve_forever()

# ==============================================================================
# Thread 7 — Storage monitor
# ==============================================================================

def storage_thread():
    if not STORAGE_ALERT_ENABLED:
        log.info("Storage alerts disabled"); return

    log.info(f"Storage monitor started — alert threshold: {STORAGE_ALERT_THRESHOLD}%")
    last_alert_pct = 0

    while True:
        try:
            usage   = shutil.disk_usage(RECORDINGS_DIR)
            pct     = round((usage.used / usage.total) * 100, 1)
            used_gb = usage.used  / (1024**3)
            total_gb= usage.total / (1024**3)
            free_gb = usage.free  / (1024**3)
            log.info(f"Storage: {pct}% used ({used_gb:.1f} GB / {total_gb:.1f} GB, "
                     f"{free_gb:.1f} GB free)")
            update_storage_sensor(pct, used_gb, total_gb, free_gb)
            if pct >= STORAGE_ALERT_THRESHOLD:
                if pct >= last_alert_pct + 5 or last_alert_pct == 0:
                    last_alert_pct = pct
                    msg = (f"OAK recordings are using **{pct}%** of storage "
                           f"({used_gb:.1f} GB of {total_gb:.1f} GB, "
                           f"{free_gb:.1f} GB free).\n\n"
                           f"Consider deleting old recordings from `{RECORDINGS_DIR}`.")
                    send_ha_notification("⚠️ OAK Camera: Storage Alert", msg)
                    fire_ha_event("oak_camera_storage_alert", {
                        "timestamp": datetime.now().isoformat(),
                        "used_percent": pct, "used_gb": round(used_gb,2),
                        "total_gb": round(total_gb,2), "free_gb": round(free_gb,2),
                        "threshold": STORAGE_ALERT_THRESHOLD,
                    })
            else:
                last_alert_pct = 0
        except Exception as e:
            log.error(f"Storage check failed: {e}")
        time.sleep(STORAGE_CHECK_INTERVAL)

# ==============================================================================
# Main
# ==============================================================================

def main() -> None:
    """Start every worker thread and block until shutdown is requested."""
    log.info("OAK-D LR bridge starting (threaded pipeline)")
    log.info(f"RTSP stream:  rtsp://<host>:{RTSP_PORT}/stream")
    log.info(f"Snapshot:     http://<host>:{SNAPSHOT_PORT}/snapshot")
    log.info(f"Settings:     http://<host>:{INGRESS_PORT}/")
    log.info(f"Recordings:   {RECORDINGS_DIR}")

    # SIGINT covers Ctrl-C in a console. SIGTERM covers docker stop and the
    # Home Assistant Supervisor stopping the add-on.
    import signal
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: request_shutdown())
        except (ValueError, OSError, AttributeError):
            pass    # not the main thread, or the platform lacks the signal

    threads = [
        threading.Thread(target=camera_thread,    name="camera",    daemon=True),
        threading.Thread(target=detection_thread, name="detection",  daemon=True),
        threading.Thread(target=rtsp_thread,      name="rtsp",       daemon=True),
        threading.Thread(target=recorder_thread,  name="recorder",   daemon=True),
        threading.Thread(target=snapshot_thread,  name="snapshot",   daemon=True),
        threading.Thread(target=http_thread,      name="http",       daemon=True),
        threading.Thread(target=storage_thread,   name="storage",    daemon=True),
        threading.Thread(target=ingress_thread,   name="ingress",    daemon=True),
    ]
    for t in threads:
        t.start()

    # Block here until the tray, the settings panel or a signal asks to stop.
    try:
        while not shutdown_event.wait(timeout=1.0):
            pass
    except KeyboardInterrupt:
        pass
    request_shutdown()


if __name__ == "__main__":
    main()
