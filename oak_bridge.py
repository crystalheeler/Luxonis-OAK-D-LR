"""
OAK-D LR  →  Home Assistant Bridge (DepthAI v3 + threaded pipeline)
--------------------------------------------------------------------
Architecture:
  Thread 1 (camera)     — captures raw frames from OAK-D LR
  Thread 2 (detection)  — runs overlay drawing on captured frames
  Thread 3 (rtsp)       — pushes display frames to ffmpeg/mediamtx
  Thread 4 (recorder)   — writes motion clips to disk
  Thread 5 (snapshot)   — updates JPEG snapshot periodically
  Thread 6 (http)       — serves snapshot over HTTP
  Thread 7 (storage)    — monitors disk usage and fires HA alerts
"""

import os
import cv2
import numpy as np
import depthai as dai
import threading
import queue
import time
import shutil
import logging
import requests
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from collections import deque

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oak-bridge")

# ==============================================================================
# Class labels
# ==============================================================================

COCO_80_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv",
    "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
    "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush"
]

MOBILENET_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus",
    "car", "cat", "chair", "cow", "diningtable", "dog", "horse",
    "motorbike", "person", "pottedplant", "sheep", "sofa", "train",
    "tvmonitor"
]

# Path to locally converted YOLO11n NNArchive (built into Docker image)
YOLO11N_LOCAL_PATH = "/models/yolo11n.tar.xz"

MODELS = {
    "yolov6-nano": {
        "display":  "YOLOv6 Nano (fastest, 80 classes)",
        "classes":  COCO_80_CLASSES,
        "people":   {"person"},
        "animals":  {"bird", "cat", "dog", "horse", "sheep", "cow",
                     "elephant", "bear", "zebra", "giraffe"},
        "vehicles": {"bicycle", "car", "motorcycle", "airplane", "bus",
                     "train", "truck", "boat"},
    },
    "luxonis/mobilenet-ssd:300x300": {
        "display":  "MobileNet SSD (lightest, 20 classes)",
        "classes":  MOBILENET_CLASSES,
        "people":   {"person"},
        "animals":  {"bird", "cat", "dog", "horse", "cow", "sheep"},
        "vehicles": {"aeroplane", "bicycle", "boat", "bus", "car",
                     "motorbike", "train"},
    },
    "yolo11n": {
        "display":  "YOLO11n (accurate, 80 classes, may be slower on RVC2)",
        "classes":  COCO_80_CLASSES,
        "people":   {"person"},
        "animals":  {"bird", "cat", "dog", "horse", "sheep", "cow",
                     "elephant", "bear", "zebra", "giraffe"},
        "vehicles": {"bicycle", "car", "motorcycle", "airplane", "bus",
                     "train", "truck", "boat"},
        "local_path": YOLO11N_LOCAL_PATH,
    },
}

COLORS = {
    "person":  (0, 200, 0),
    "animal":  (0, 165, 255),
    "vehicle": (255, 100, 0),
    "other":   (180, 180, 180),
}

# ==============================================================================
# Config
# ==============================================================================

CAMERA_IP              = os.environ.get("CAMERA_IP", "").strip() or None
RTSP_PORT              = int(os.environ.get("MJPEG_PORT", 8765))
SNAPSHOT_PORT          = RTSP_PORT + 1
FPS                    = int(os.environ.get("FPS", 15))
DETECTION_MODEL        = os.environ.get("DETECTION_MODEL", "yolov6-nano").strip()
CONFIDENCE_THRESHOLD   = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.5))
DETECT_PEOPLE          = os.environ.get("DETECT_PEOPLE", "true").lower() == "true"
DETECT_ANIMALS         = os.environ.get("DETECT_ANIMALS", "true").lower() == "true"
DETECT_VEHICLES        = os.environ.get("DETECT_VEHICLES", "false").lower() == "true"
STORAGE_ALERT_ENABLED  = os.environ.get("STORAGE_ALERT_ENABLED", "true").lower() == "true"
STORAGE_ALERT_THRESHOLD= int(os.environ.get("STORAGE_ALERT_THRESHOLD", 50))
HA_URL                 = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN               = os.environ.get("HA_TOKEN", "").strip()

FRAME_WIDTH       = 1280
FRAME_HEIGHT      = 720
PRE_ROLL_SECONDS  = 3
POST_ROLL_SECONDS = 5
MAX_CLIP_SECONDS  = 120
RECORDINGS_DIR    = "/media/oak_recordings"
STORAGE_CHECK_INTERVAL = 300  # check every 5 minutes

POST_DETECTION_FRAMES = FPS * POST_ROLL_SECONDS
PRE_ROLL_FRAMES       = FPS * PRE_ROLL_SECONDS
MAX_CLIP_FRAMES       = FPS * MAX_CLIP_SECONDS
RTSP_PUBLISH_URL      = f"rtsp://localhost:{RTSP_PORT}/stream"

if FPS > 20:
    log.warning(f"FPS={FPS} may cause instability on Pi 4 — consider 15-20")

if DETECTION_MODEL not in MODELS:
    log.warning(f"Unknown model '{DETECTION_MODEL}' — falling back to yolov6-nano")
    DETECTION_MODEL = "yolov6-nano"

# Warn if yolo11n selected but file not yet present
if DETECTION_MODEL == "yolo11n" and not os.path.exists(MODELS["yolo11n"].get("local_path", "")):
    log.warning("yolo11n selected but /models/yolo11n.tar.xz not found.")
    log.warning("Run prepare_yolo11n_windows.py on your PC, copy yolo11n.tar.xz")
    log.warning("to oak_camera_app folder, then rebuild the app.")
    log.warning("Falling back to yolov6-nano.")
    DETECTION_MODEL = "yolov6-nano"

MODEL_CFG    = MODELS[DETECTION_MODEL]
CLASS_LABELS = MODEL_CFG["classes"]

TRIGGER_CLASSES = set()
if DETECT_PEOPLE:   TRIGGER_CLASSES |= MODEL_CFG["people"]
if DETECT_ANIMALS:  TRIGGER_CLASSES |= MODEL_CFG["animals"]
if DETECT_VEHICLES: TRIGGER_CLASSES |= MODEL_CFG["vehicles"]

log.info(f"Model: {MODEL_CFG['display']}")
log.info(f"Trigger classes: {sorted(TRIGGER_CLASSES)}")
log.info(f"Confidence threshold: {CONFIDENCE_THRESHOLD:.0%}")
log.info(f"FPS: {FPS}")
log.info(f"Storage alerts: {'enabled' if STORAGE_ALERT_ENABLED else 'disabled'} "
         f"(threshold: {STORAGE_ALERT_THRESHOLD}%)")


def get_color(label):
    if label in MODEL_CFG["people"]:   return COLORS["person"]
    if label in MODEL_CFG["animals"]:  return COLORS["animal"]
    if label in MODEL_CFG["vehicles"]: return COLORS["vehicle"]
    return COLORS["other"]


# ==============================================================================
# Shared queues
# record_q is large enough to buffer frames during pre-roll bulk write (~300ms)
# At 20fps that's ~6 incoming frames — 90 slots is more than sufficient
# ==============================================================================

raw_q    = queue.Queue(maxsize=8)
rtsp_q   = queue.Queue(maxsize=8)
record_q = queue.Queue(maxsize=PRE_ROLL_FRAMES + 30)
snap_q   = queue.Queue(maxsize=2)

detection_active = False
detection_lock   = threading.Lock()
latest_jpeg      = None
latest_jpeg_lock = threading.Lock()
ffmpeg_proc      = None


# ==============================================================================
# HA event / notification firing
# ==============================================================================

def fire_ha_event(event_type, data):
    if not HA_TOKEN:
        return
    try:
        requests.post(
            f"{HA_URL}/api/events/{event_type}",
            json=data,
            headers={"Authorization": f"Bearer {HA_TOKEN}",
                     "Content-Type": "application/json"},
            timeout=5
        ).raise_for_status()
        log.info(f"Fired HA event: {event_type}")
    except Exception as e:
        log.error(f"HA event failed: {e}")


def send_ha_notification(title, message):
    """Send a persistent notification to the HA UI."""
    if not HA_TOKEN:
        return
    try:
        requests.post(
            f"{HA_URL}/api/services/persistent_notification/create",
            json={"title": title, "message": message,
                  "notification_id": "oak_camera_storage"},
            headers={"Authorization": f"Bearer {HA_TOKEN}",
                     "Content-Type": "application/json"},
            timeout=5
        ).raise_for_status()
        log.info(f"Sent HA notification: {title}")
    except Exception as e:
        log.error(f"HA notification failed: {e}")


def update_storage_sensor(pct, used_gb, total_gb, free_gb):
    """Push storage usage as a sensor entity into Home Assistant."""
    if not HA_TOKEN:
        return
    try:
        requests.post(
            f"{HA_URL}/api/states/sensor.oak_camera_storage",
            json={
                "state": str(pct),
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
                }
            },
            headers={"Authorization": f"Bearer {HA_TOKEN}",
                     "Content-Type": "application/json"},
            timeout=5
        ).raise_for_status()
    except Exception as e:
        log.error(f"Storage sensor update failed: {e}")


# ==============================================================================
# Detection overlay
# ==============================================================================

def draw_detections(frame, detections):
    triggered = []
    for det in detections:
        label = CLASS_LABELS[det.label] if det.label < len(CLASS_LABELS) else f"class_{det.label}"
        color = get_color(label)
        x1 = int(det.xmin * FRAME_WIDTH)
        y1 = int(det.ymin * FRAME_HEIGHT)
        x2 = int(det.xmax * FRAME_WIDTH)
        y2 = int(det.ymax * FRAME_HEIGHT)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label} {det.confidence:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        if label in TRIGGER_CLASSES:
            triggered.append(label)
    return triggered


# ==============================================================================
# Video recorder — pre-roll written in bulk at start, queue is large enough
# to absorb the ~300ms write time without dropping any live frames
# ==============================================================================

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
            log.error(f"Recordings dir not writable: {e}")
            return False

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.clip_path = os.path.join(RECORDINGS_DIR, f"motion_{ts}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(
            self.clip_path, fourcc, FPS, (FRAME_WIDTH, FRAME_HEIGHT))
        if not self.writer.isOpened():
            log.error(f"VideoWriter failed: {self.clip_path}")
            self.writer = None; self.clip_path = None
            return False

        # Write all pre-roll frames at once.
        # record_q is sized to PRE_ROLL_FRAMES+30 so incoming frames won't
        # be dropped during this brief (~300ms) write.
        for f in pre_roll_frames:
            self.writer.write(f)
        self.frame_count = len(pre_roll_frames)
        log.info(f"Recording started: {self.clip_path} "
                 f"({self.frame_count} pre-roll frames written)")
        return True

    def write(self, frame):
        if self.writer:
            self.writer.write(frame)
            self.frame_count += 1

    def stop(self):
        if self.writer:
            self.writer.release()
            self.writer = None
            log.info(f"Recording saved: {self.clip_path} "
                     f"({self.frame_count/FPS:.1f}s, {self.frame_count} frames)")
            self.clip_path = None
            self.frame_count = 0

    def is_recording(self): return self.writer is not None
    def is_too_long(self):  return self.frame_count >= MAX_CLIP_FRAMES


# ==============================================================================
# ffmpeg RTSP publisher
# ==============================================================================

def start_ffmpeg():
    cmd = [
        "ffmpeg", "-loglevel", "warning",
        "-f", "rawvideo", "-pixel_format", "bgr24",
        "-video_size", f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
        "-framerate", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-tune", "zerolatency", "-b:v", "1000k",
        "-f", "rtsp", "-rtsp_transport", "tcp",
        RTSP_PUBLISH_URL
    ]
    log.info(f"Starting ffmpeg → {RTSP_PUBLISH_URL}")
    return subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


# ==============================================================================
# Thread 1 — Camera capture
# ==============================================================================

def camera_thread():
    # Short startup delay to let any previous device session release
    time.sleep(3)

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

                # Load from local file if model has a local_path, otherwise from Hub
                local_path = MODEL_CFG.get("local_path")
                if local_path:
                    if not os.path.exists(local_path):
                        raise FileNotFoundError(
                            f"Local model not found: {local_path}. "
                            f"Was the Docker image built correctly?")
                    log.info(f"Loading model: {DETECTION_MODEL} (local: {local_path})")
                    nn_archive = dai.NNArchive(local_path)
                    det_net = pipeline.create(dai.node.DetectionNetwork).build(
                        cam, nn_archive, fps=FPS
                    )
                else:
                    log.info(f"Loading model: {DETECTION_MODEL} (from Hub cache)")
                    model_desc = dai.NNModelDescription(
                        DETECTION_MODEL, platform=device.getPlatformAsString())
                    model_path = dai.getModelFromZoo(model_desc, useCached=True)
                    nn_archive = dai.NNArchive(model_path)
                    det_net = pipeline.create(dai.node.DetectionNetwork).build(
                        cam, nn_archive, fps=FPS
                    )
                det_net.setConfidenceThreshold(CONFIDENCE_THRESHOLD)

                video_out = cam.requestOutput(
                    (FRAME_WIDTH, FRAME_HEIGHT),
                    type=dai.ImgFrame.Type.BGR888p,
                    fps=FPS
                )
                video_q = video_out.createOutputQueue(maxSize=4, blocking=False)
                det_q   = det_net.out.createOutputQueue(maxSize=4, blocking=False)

                pipeline.start()
                log.info(f"Pipeline started — {MODEL_CFG['display']} @ {FPS}fps")

                while pipeline.isRunning():
                    in_frame = video_q.get()
                    if in_frame is None:
                        continue
                    detections = []
                    if det_q.has():
                        msg = det_q.get()
                        if msg:
                            detections = msg.detections
                    try:
                        raw_q.put_nowait((in_frame.getCvFrame(), detections))
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
    post_detection_counter = 0

    while True:
        try:
            frame, detections = raw_q.get(timeout=5)
        except queue.Empty:
            continue

        display   = frame.copy()
        triggered = draw_detections(display, detections)
        detection_now = len(triggered) > 0

        with detection_lock:
            active = detection_active

        if active:
            label_text = (f"RECORDING — {', '.join(sorted(set(triggered)))}"
                          if triggered else "RECORDING")
            color = (0, 0, 220)
        else:
            label_text = "Monitoring"
            color = (180, 180, 180)

        cv2.rectangle(display, (10, 10), (500, 44), (30, 30, 30), -1)
        cv2.putText(display, label_text, (18, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        cv2.putText(display, ts, (FRAME_WIDTH - 310, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

        if detection_now:
            post_detection_counter = POST_DETECTION_FRAMES
            with detection_lock:
                if not detection_active:
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
                    post_detection_counter -= 1
                    if post_detection_counter <= 0:
                        detection_active = False
                        log.info("Detection ended")
                        fire_ha_event("oak_camera_motion_stopped", {
                            "timestamp": datetime.now().isoformat(),
                            "camera": "OAK-D LR",
                        })

        for q in (rtsp_q, record_q, snap_q):
            try:
                q.put_nowait(display)
            except queue.Full:
                pass


# ==============================================================================
# Thread 3 — RTSP publisher
# ==============================================================================

def rtsp_thread():
    global ffmpeg_proc
    ffmpeg_proc = start_ffmpeg()
    time.sleep(2)

    while True:
        try:
            frame = rtsp_q.get(timeout=5)
        except queue.Empty:
            continue

        if ffmpeg_proc.poll() is not None:
            log.warning("ffmpeg died — restarting...")
            ffmpeg_proc = start_ffmpeg()
            time.sleep(2)

        try:
            ffmpeg_proc.stdin.write(frame.tobytes())
            ffmpeg_proc.stdin.flush()
        except (BrokenPipeError, OSError):
            log.warning("ffmpeg pipe broken — restarting...")
            ffmpeg_proc = start_ffmpeg()
            time.sleep(2)


# ==============================================================================
# Thread 4 — Recorder
# ==============================================================================

def recorder_thread():
    recorder = MotionRecorder()
    pre_roll = deque(maxlen=PRE_ROLL_FRAMES)

    log.info("Waiting for recordings directory...")
    for _ in range(10):
        try:
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            tp = os.path.join(RECORDINGS_DIR, ".startuptest")
            open(tp, "w").close(); os.remove(tp)
            log.info(f"Recordings directory ready: {RECORDINGS_DIR}")
            break
        except Exception:
            time.sleep(1)
    else:
        log.warning("Could not verify recordings directory")

    while True:
        try:
            frame = record_q.get(timeout=5)
        except queue.Empty:
            continue

        with detection_lock:
            active = detection_active

        if active:
            if not recorder.is_recording():
                recorder.start(pre_roll)
            if recorder.is_recording():
                recorder.write(frame)
                if recorder.is_too_long():
                    log.info("Max clip length — splitting")
                    recorder.stop()
                    recorder.start(deque())
        else:
            if recorder.is_recording():
                recorder.stop()
            pre_roll.append(frame)


# ==============================================================================
# Thread 5 — Snapshot updater
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


# ==============================================================================
# Thread 6 — HTTP snapshot server
# ==============================================================================

class SnapshotHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        if self.path == "/snapshot":
            with latest_jpeg_lock:
                frame = latest_jpeg
            if frame:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"No frame yet")
        else:
            self.send_response(404)
            self.end_headers()

def http_thread():
    server = HTTPServer(("0.0.0.0", SNAPSHOT_PORT), SnapshotHandler)
    log.info(f"Snapshot server on :{SNAPSHOT_PORT}")
    server.serve_forever()


# ==============================================================================
# Thread 7 — Storage monitor
# ==============================================================================

def storage_thread():
    if not STORAGE_ALERT_ENABLED:
        log.info("Storage alerts disabled — skipping storage monitor")
        return

    log.info(f"Storage monitor started — alert threshold: {STORAGE_ALERT_THRESHOLD}%")
    last_alert_pct = 0  # track last alerted threshold to avoid spam

    while True:
        try:
            usage   = shutil.disk_usage(RECORDINGS_DIR)
            pct     = round((usage.used / usage.total) * 100, 1)
            used_gb = usage.used  / (1024 ** 3)
            total_gb= usage.total / (1024 ** 3)
            free_gb = usage.free  / (1024 ** 3)

            log.info(f"Storage: {pct}% used ({used_gb:.1f} GB / {total_gb:.1f} GB, "
                     f"{free_gb:.1f} GB free)")

            # Update HA sensor on every check
            update_storage_sensor(pct, used_gb, total_gb, free_gb)

            if pct >= STORAGE_ALERT_THRESHOLD:
                # Only re-alert if usage crossed another 5% band since last alert
                if pct >= last_alert_pct + 5 or last_alert_pct == 0:
                    last_alert_pct = pct
                    msg = (f"OAK camera recordings are using **{pct}%** of available storage "
                           f"({used_gb:.1f} GB used of {total_gb:.1f} GB, "
                           f"{free_gb:.1f} GB free).\n\n"
                           f"Consider deleting old recordings from `/media/oak_recordings/`.")
                    send_ha_notification("⚠️ OAK Camera: Storage Alert", msg)
                    fire_ha_event("oak_camera_storage_alert", {
                        "timestamp": datetime.now().isoformat(),
                        "used_percent": pct,
                        "used_gb": round(used_gb, 2),
                        "total_gb": round(total_gb, 2),
                        "free_gb": round(free_gb, 2),
                        "threshold": STORAGE_ALERT_THRESHOLD,
                    })
            else:
                # Reset alert level when usage drops back below threshold
                last_alert_pct = 0

        except Exception as e:
            log.error(f"Storage check failed: {e}")

        time.sleep(STORAGE_CHECK_INTERVAL)


# ==============================================================================
# Main
# ==============================================================================

if __name__ == "__main__":
    log.info("OAK-D LR bridge starting (threaded pipeline)")
    log.info(f"RTSP stream:  rtsp://<ha-ip>:{RTSP_PORT}/stream")
    log.info(f"Snapshot:     http://<ha-ip>:{SNAPSHOT_PORT}/snapshot")
    log.info(f"Recordings:   {RECORDINGS_DIR}")

    threads = [
        threading.Thread(target=camera_thread,    name="camera",    daemon=True),
        threading.Thread(target=detection_thread, name="detection",  daemon=True),
        threading.Thread(target=rtsp_thread,      name="rtsp",       daemon=True),
        threading.Thread(target=recorder_thread,  name="recorder",   daemon=True),
        threading.Thread(target=snapshot_thread,  name="snapshot",   daemon=True),
        threading.Thread(target=http_thread,      name="http",       daemon=True),
        threading.Thread(target=storage_thread,   name="storage",    daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if ffmpeg_proc:
            ffmpeg_proc.terminate()
