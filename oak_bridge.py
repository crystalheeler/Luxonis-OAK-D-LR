"""
OAK-D LR  →  Home Assistant Bridge
-------------------------------------
- Connects to the OAK-D LR over PoE using DepthAI
- Detects motion via frame differencing
- Serves an MJPEG HTTP stream on a configurable port
- Fires events to Home Assistant via REST API when motion starts/stops
  so HA automations can trigger recordings, notifications, etc.
"""

import os
import cv2
import numpy as np
import depthai as dai
import threading
import time
import logging
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oak-bridge")

# ==============================================================================
# Config from environment variables (set by run.sh from HA app options)
# ==============================================================================

CAMERA_IP        = os.environ.get("CAMERA_IP", "").strip() or None
MJPEG_PORT       = int(os.environ.get("MJPEG_PORT", 8765))
MOTION_THRESHOLD = int(os.environ.get("MOTION_THRESHOLD", 25))
MIN_MOTION_AREA  = int(os.environ.get("MIN_MOTION_AREA", 5000))
HA_URL           = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN         = os.environ.get("HA_TOKEN", "").strip()

FRAME_WIDTH  = 1280
FRAME_HEIGHT = 800
FPS          = 20

# How many consecutive quiet frames before we call motion "stopped"
POST_MOTION_FRAMES = FPS * 4  # 4 seconds

# ==============================================================================
# Shared state between the camera thread and the HTTP server
# ==============================================================================

latest_jpeg      = None
latest_jpeg_lock = threading.Lock()
motion_active    = False


# ==============================================================================
# Home Assistant event firing
# ==============================================================================

def fire_ha_event(event_type: str, data: dict):
    """Fire a custom event into Home Assistant via the REST API."""
    if not HA_TOKEN:
        log.warning("No HA token configured — skipping event firing.")
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
# Motion detection
# ==============================================================================

def detect_motion(prev_gray, curr_gray):
    diff = cv2.absdiff(prev_gray, curr_gray)
    _, thresh = cv2.threshold(diff, MOTION_THRESHOLD, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    thresh = cv2.dilate(thresh, kernel, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = sum(cv2.contourArea(c) for c in contours)
    return area >= MIN_MOTION_AREA, thresh


# ==============================================================================
# Camera capture thread
# ==============================================================================

def build_pipeline():
    pipeline = dai.Pipeline()

    cam = pipeline.create(dai.node.ColorCamera)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1200_P)
    cam.setInterleaved(False)
    cam.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)
    cam.setFps(FPS)

    manip = pipeline.create(dai.node.ImageManip)
    manip.initialConfig.setResize(FRAME_WIDTH, FRAME_HEIGHT)
    manip.initialConfig.setFrameType(dai.ImgFrame.Type.BGR888p)
    manip.setMaxOutputFrameSize(FRAME_WIDTH * FRAME_HEIGHT * 3)

    xout = pipeline.create(dai.node.XLinkOut)
    xout.setStreamName("video")

    cam.video.link(manip.inputImage)
    manip.out.link(xout.input)

    return pipeline


def camera_thread():
    global latest_jpeg, motion_active

    log.info("Connecting to OAK-D LR...")
    pipeline = build_pipeline()

    while True:
        try:
            if CAMERA_IP:
                device_info = dai.DeviceInfo(CAMERA_IP)
                device_ctx = dai.Device(pipeline, device_info)
            else:
                device_ctx = dai.Device(pipeline)

            with device_ctx as device:
                log.info(f"Connected to camera: {device.getMxId()}")
                q = device.getOutputQueue(name="video", maxSize=4, blocking=False)

                prev_gray = None
                post_motion_counter = 0

                while True:
                    in_frame = q.get()
                    if in_frame is None:
                        continue

                    frame = in_frame.getCvFrame()
                    curr_gray = cv2.GaussianBlur(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0
                    )

                    motion_now = False
                    motion_mask = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint8)

                    if prev_gray is not None:
                        motion_now, motion_mask = detect_motion(prev_gray, curr_gray)

                    prev_gray = curr_gray

                    # Motion state machine
                    if motion_now:
                        post_motion_counter = POST_MOTION_FRAMES
                        if not motion_active:
                            motion_active = True
                            log.info("Motion started")
                            fire_ha_event("oak_camera_motion_started", {
                                "timestamp": datetime.now().isoformat(),
                                "camera": "OAK-D LR",
                            })
                    else:
                        if motion_active:
                            post_motion_counter -= 1
                            if post_motion_counter <= 0:
                                motion_active = False
                                log.info("Motion stopped")
                                fire_ha_event("oak_camera_motion_stopped", {
                                    "timestamp": datetime.now().isoformat(),
                                    "camera": "OAK-D LR",
                                })

                    # Draw overlay
                    display = frame.copy()
                    if motion_now:
                        red = np.zeros_like(display)
                        red[:, :, 2] = motion_mask
                        display = cv2.addWeighted(display, 1.0, red, 0.3, 0)

                    label = "MOTION DETECTED" if motion_active else "Monitoring"
                    color = (0, 0, 220) if motion_active else (180, 180, 180)
                    cv2.rectangle(display, (10, 10), (320, 44), (30, 30, 30), -1)
                    cv2.putText(display, label, (18, 34),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
                    cv2.putText(display, ts, (FRAME_WIDTH - 310, 34),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

                    # Encode to JPEG
                    ok, jpeg_buf = cv2.imencode(
                        ".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 75]
                    )
                    if ok:
                        with latest_jpeg_lock:
                            latest_jpeg = jpeg_buf.tobytes()

        except Exception as e:
            log.error(f"Camera error: {e} — retrying in 5s...")
            time.sleep(5)


# ==============================================================================
# MJPEG HTTP server
# ==============================================================================

BOUNDARY = b"--frame"

class MJPEGHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress per-request access logs

    def do_GET(self):
        if self.path == "/stream":
            self.serve_stream()
        elif self.path == "/snapshot":
            self.serve_snapshot()
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def serve_stream(self):
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                with latest_jpeg_lock:
                    frame = latest_jpeg
                if frame:
                    self.wfile.write(BOUNDARY + b"\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                time.sleep(1 / FPS)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def serve_snapshot(self):
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
            self.wfile.write(b"No frame available yet")


# ==============================================================================
# Main
# ==============================================================================

if __name__ == "__main__":
    log.info(f"OAK-D LR bridge starting — MJPEG port {MJPEG_PORT}")

    cam_thread = threading.Thread(target=camera_thread, daemon=True)
    cam_thread.start()

    server = HTTPServer(("0.0.0.0", MJPEG_PORT), MJPEGHandler)
    log.info(f"MJPEG server listening on :{MJPEG_PORT}")
    log.info(f"  Stream:   http://<ha-ip>:{MJPEG_PORT}/stream")
    log.info(f"  Snapshot: http://<ha-ip>:{MJPEG_PORT}/snapshot")
    server.serve_forever()
