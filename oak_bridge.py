"""
OAK-D LR  →  Home Assistant Bridge (DepthAI v3 + YOLOv6n + mediamtx RTSP)
---------------------------------------------------------------------------
- Connects to the OAK-D LR over PoE using DepthAI v3
- Runs YOLOv6n object detection on-device
- Triggers recording only when configured classes are detected
- Draws bounding boxes and labels on video feed and recordings
- Pipes frames into ffmpeg which publishes to mediamtx RTSP server
- Serves a JPEG snapshot over HTTP for HA dashboard thumbnail
- Fires events to Home Assistant via REST API when detection starts/stops

RTSP stream:  rtsp://<ha-ip>:8765/stream
Snapshot:     http://<ha-ip>:8766/snapshot
"""

import os
import cv2
import numpy as np
import depthai as dai
import threading
import time
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
# COCO class definitions
# ==============================================================================

COCO_CLASSES = [
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

PEOPLE_CLASSES   = {"person"}
ANIMAL_CLASSES   = {"bird", "cat", "dog", "horse", "sheep", "cow",
                    "elephant", "bear", "zebra", "giraffe"}
VEHICLE_CLASSES  = {"bicycle", "car", "motorcycle", "airplane", "bus",
                    "train", "truck", "boat"}

# Bounding box colors per category (BGR)
COLORS = {
    "person":  (0, 200, 0),    # green
    "animal":  (0, 165, 255),  # orange
    "vehicle": (255, 100, 0),  # blue
    "other":   (180, 180, 180) # grey
}

def get_color(label):
    if label in PEOPLE_CLASSES:
        return COLORS["person"]
    if label in ANIMAL_CLASSES:
        return COLORS["animal"]
    if label in VEHICLE_CLASSES:
        return COLORS["vehicle"]
    return COLORS["other"]


# ==============================================================================
# Config from environment variables
# ==============================================================================

CAMERA_IP            = os.environ.get("CAMERA_IP", "").strip() or None
RTSP_PORT            = int(os.environ.get("MJPEG_PORT", 8765))
SNAPSHOT_PORT        = RTSP_PORT + 1
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.5))
DETECT_PEOPLE        = os.environ.get("DETECT_PEOPLE", "true").lower() == "true"
DETECT_ANIMALS       = os.environ.get("DETECT_ANIMALS", "true").lower() == "true"
DETECT_VEHICLES      = os.environ.get("DETECT_VEHICLES", "false").lower() == "true"
HA_URL               = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN             = os.environ.get("HA_TOKEN", "").strip()

FRAME_WIDTH       = 1280
FRAME_HEIGHT      = 720
FPS               = 15
PRE_ROLL_SECONDS  = 3
POST_ROLL_SECONDS = 5
MAX_CLIP_SECONDS  = 120
RECORDINGS_DIR    = "/media/oak_recordings"

POST_DETECTION_FRAMES = FPS * POST_ROLL_SECONDS
PRE_ROLL_FRAMES       = FPS * PRE_ROLL_SECONDS
MAX_CLIP_FRAMES       = FPS * MAX_CLIP_SECONDS

RTSP_PUBLISH_URL = f"rtsp://localhost:{RTSP_PORT}/stream"

# Build the set of classes that should trigger recording
TRIGGER_CLASSES = set()
if DETECT_PEOPLE:
    TRIGGER_CLASSES |= PEOPLE_CLASSES
if DETECT_ANIMALS:
    TRIGGER_CLASSES |= ANIMAL_CLASSES
if DETECT_VEHICLES:
    TRIGGER_CLASSES |= VEHICLE_CLASSES

log.info(f"Trigger classes: {sorted(TRIGGER_CLASSES)}")
log.info(f"Confidence threshold: {CONFIDENCE_THRESHOLD:.0%}")

# ==============================================================================
# Shared state
# ==============================================================================

detection_active = False
ffmpeg_proc      = None
latest_jpeg      = None
latest_jpeg_lock = threading.Lock()


# ==============================================================================
# Home Assistant event firing
# ==============================================================================

def fire_ha_event(event_type: str, data: dict):
    if not HA_TOKEN:
        log.warning("No HA token configured — skipping event.")
        return
    url = f"{HA_URL}/api/events/{event_type}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=5)
        resp.raise_for_status()
        log.info(f"Fired HA event: {event_type}")
    except Exception as e:
        log.error(f"Failed to fire HA event '{event_type}': {e}")


# ==============================================================================
# Draw detections overlay
# ==============================================================================

def draw_detections(frame, detections):
    """Draw bounding boxes and labels for all detections."""
    triggered_labels = []
    for det in detections:
        label = COCO_CLASSES[det.label] if det.label < len(COCO_CLASSES) else f"class_{det.label}"
        confidence = det.confidence
        color = get_color(label)

        # Scale normalised bbox coords to frame size
        x1 = int(det.xmin * FRAME_WIDTH)
        y1 = int(det.ymin * FRAME_HEIGHT)
        x2 = int(det.xmax * FRAME_WIDTH)
        y2 = int(det.ymax * FRAME_HEIGHT)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        text = f"{label} {confidence:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, text, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

        if label in TRIGGER_CLASSES:
            triggered_labels.append(label)

    return triggered_labels


# ==============================================================================
# Video recorder
# ==============================================================================

class MotionRecorder:
    def __init__(self):
        self.writer      = None
        self.clip_path   = None
        self.frame_count = 0
        os.makedirs(RECORDINGS_DIR, exist_ok=True)

    def start(self, pre_roll: deque):
        try:
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            test_path = os.path.join(RECORDINGS_DIR, ".writetest")
            with open(test_path, "w") as f:
                f.write("ok")
            os.remove(test_path)
        except Exception as e:
            log.error(f"Recordings directory not writable: {e} — skipping clip")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.clip_path = os.path.join(RECORDINGS_DIR, f"motion_{ts}.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.writer = cv2.VideoWriter(
            self.clip_path, fourcc, FPS, (FRAME_WIDTH, FRAME_HEIGHT)
        )
        if not self.writer.isOpened():
            log.error(f"VideoWriter failed to open: {self.clip_path} — skipping clip")
            self.writer = None
            self.clip_path = None
            return

        for f in pre_roll:
            self.writer.write(f)
        self.frame_count = len(pre_roll)
        log.info(f"Recording started: {self.clip_path}")

    def write(self, frame):
        if self.writer:
            self.writer.write(frame)
            self.frame_count += 1

    def stop(self):
        if self.writer:
            self.writer.release()
            self.writer = None
            duration = self.frame_count / FPS
            log.info(f"Recording saved: {self.clip_path} ({duration:.1f}s, {self.frame_count} frames)")
            self.clip_path = None
            self.frame_count = 0

    def is_recording(self):
        return self.writer is not None

    def is_too_long(self):
        return self.frame_count >= MAX_CLIP_FRAMES


# ==============================================================================
# ffmpeg RTSP publisher
# ==============================================================================

def start_ffmpeg():
    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        "-f", "rawvideo",
        "-pixel_format", "bgr24",
        "-video_size", f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
        "-framerate", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", "1000k",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        RTSP_PUBLISH_URL
    ]
    log.info(f"Starting ffmpeg publisher → {RTSP_PUBLISH_URL}")
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


# ==============================================================================
# Snapshot HTTP server
# ==============================================================================

class SnapshotHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

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

def snapshot_server_thread():
    server = HTTPServer(("0.0.0.0", SNAPSHOT_PORT), SnapshotHandler)
    log.info(f"Snapshot server on :{SNAPSHOT_PORT}")
    server.serve_forever()


# ==============================================================================
# Camera + detection + streaming + recording thread
# ==============================================================================

def camera_thread():
    global detection_active, ffmpeg_proc, latest_jpeg

    # Wait for /media volume to be ready
    log.info("Waiting for media volume to be ready...")
    for _ in range(10):
        try:
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            test = os.path.join(RECORDINGS_DIR, ".startuptest")
            open(test, "w").close()
            os.remove(test)
            log.info(f"Recordings directory ready: {RECORDINGS_DIR}")
            break
        except Exception:
            time.sleep(1)
    else:
        log.warning("Could not verify recordings directory — clips may be lost on first motion")

    recorder = MotionRecorder()
    pre_roll = deque(maxlen=PRE_ROLL_FRAMES)

    while True:
        try:
            ffmpeg_proc = start_ffmpeg()
            time.sleep(1)

            if CAMERA_IP:
                log.info(f"Connecting to OAK-D LR at {CAMERA_IP} via TCP/IP...")
                device_info = dai.DeviceInfo(CAMERA_IP)
                device_info.protocol = dai.XLinkProtocol.X_LINK_TCP_IP
                device_info.state = dai.XLinkDeviceState.X_LINK_BOOTLOADER
                device = dai.Device(device_info)
            else:
                log.info("Auto-discovering OAK-D LR on network...")
                device = dai.Device()

            with device:
                log.info(f"Connected to camera: {device.getDeviceId()}")

                pipeline = dai.Pipeline(device)

                # Camera node
                cam = pipeline.create(dai.node.Camera).build()

                # Detection network — YOLOv6n from model zoo
                log.info("Loading YOLOv6n model...")
                det_net = pipeline.create(dai.node.DetectionNetwork).build(
                    cam,
                    dai.NNModelDescription("yolov6-nano",
                                           platform=device.getPlatformAsString()),
                    fps=FPS
                )
                det_net.setConfidenceThreshold(CONFIDENCE_THRESHOLD)

                # Request a video output at our display resolution
                video_out = cam.requestOutput(
                    (FRAME_WIDTH, FRAME_HEIGHT),
                    type=dai.ImgFrame.Type.BGR888p,
                    fps=FPS
                )

                # Output queues
                video_q = video_out.createOutputQueue(maxSize=4, blocking=False)
                det_q   = det_net.out.createOutputQueue(maxSize=4, blocking=False)

                pipeline.start()
                log.info(f"Pipeline started with YOLOv6n detection")
                log.info(f"RTSP stream at rtsp://<ha-ip>:{RTSP_PORT}/stream")

                post_detection_counter = 0

                while pipeline.isRunning():
                    if ffmpeg_proc.poll() is not None:
                        log.warning("ffmpeg died — restarting...")
                        ffmpeg_proc = start_ffmpeg()
                        time.sleep(1)

                    in_frame = video_q.get()
                    if in_frame is None:
                        continue

                    frame = in_frame.getCvFrame()
                    display = frame.copy()

                    # Get latest detections (non-blocking)
                    detections = []
                    if det_q.has():
                        det_msg = det_q.get()
                        if det_msg:
                            detections = det_msg.detections

                    # Draw all detections and find which trigger classes are present
                    triggered_labels = draw_detections(display, detections)
                    detection_now = len(triggered_labels) > 0

                    # Status overlay
                    if detection_active:
                        label_text = f"RECORDING — {', '.join(sorted(set(triggered_labels)))}" if triggered_labels else "RECORDING"
                        color = (0, 0, 220)
                    else:
                        label_text = "Monitoring"
                        color = (180, 180, 180)
                    cv2.rectangle(display, (10, 10), (400, 44), (30, 30, 30), -1)
                    cv2.putText(display, label_text, (18, 34),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
                    cv2.putText(display, ts, (FRAME_WIDTH - 310, 34),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

                    # ── Detection state machine ───────────────────────────────
                    if detection_now:
                        post_detection_counter = POST_DETECTION_FRAMES
                        if not detection_active:
                            detection_active = True
                            log.info(f"Detection started: {', '.join(sorted(set(triggered_labels)))}")
                            recorder.start(pre_roll)
                            fire_ha_event("oak_camera_motion_started", {
                                "timestamp": datetime.now().isoformat(),
                                "camera": "OAK-D LR",
                                "detected": sorted(set(triggered_labels)),
                            })
                    else:
                        if detection_active:
                            post_detection_counter -= 1
                            if post_detection_counter <= 0:
                                detection_active = False
                                log.info("Detection ended")
                                recorder.stop()
                                fire_ha_event("oak_camera_motion_stopped", {
                                    "timestamp": datetime.now().isoformat(),
                                    "camera": "OAK-D LR",
                                })

                    # Hard cap on clip length
                    if recorder.is_recording() and recorder.is_too_long():
                        log.info("Max clip length reached — saving and starting new clip")
                        recorder.stop()
                        recorder.start(deque())

                    # Write to recorder or pre-roll
                    if recorder.is_recording():
                        recorder.write(display)
                    else:
                        pre_roll.append(display)

                    # Update snapshot
                    ok, jpeg_buf = cv2.imencode(
                        ".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 70]
                    )
                    if ok:
                        with latest_jpeg_lock:
                            latest_jpeg = jpeg_buf.tobytes()

                    # Push to ffmpeg for RTSP
                    try:
                        ffmpeg_proc.stdin.write(display.tobytes())
                    except (BrokenPipeError, OSError):
                        log.warning("ffmpeg pipe broken — restarting...")
                        ffmpeg_proc = start_ffmpeg()
                        time.sleep(1)

        except Exception as e:
            log.error(f"Camera error: {e} — retrying in 10s...")
            detection_active = False
            if recorder.is_recording():
                recorder.stop()
            if ffmpeg_proc:
                try:
                    ffmpeg_proc.terminate()
                except:
                    pass
            time.sleep(10)


# ==============================================================================
# Main
# ==============================================================================

if __name__ == "__main__":
    log.info(f"OAK-D LR bridge starting")
    log.info(f"RTSP stream:  rtsp://<ha-ip>:{RTSP_PORT}/stream")
    log.info(f"Snapshot:     http://<ha-ip>:{SNAPSHOT_PORT}/snapshot")
    log.info(f"Recordings:   {RECORDINGS_DIR}")

    snap_thread = threading.Thread(target=snapshot_server_thread, daemon=True)
    snap_thread.start()

    cam_thread = threading.Thread(target=camera_thread, daemon=True)
    cam_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        if ffmpeg_proc:
            ffmpeg_proc.terminate()
