"""
OAK-D LR  →  Home Assistant Bridge (DepthAI v3 + mediamtx RTSP)
-----------------------------------------------------------------
- Connects to the OAK-D LR over PoE using DepthAI v3
- Detects motion via frame differencing
- Pipes frames into ffmpeg which publishes to mediamtx RTSP server
- Serves a JPEG snapshot over HTTP for HA dashboard thumbnail
- Fires events to Home Assistant via REST API when motion starts/stops

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oak-bridge")

# ==============================================================================
# Config from environment variables
# ==============================================================================

CAMERA_IP        = os.environ.get("CAMERA_IP", "").strip() or None
RTSP_PORT        = int(os.environ.get("MJPEG_PORT", 8765))
SNAPSHOT_PORT    = RTSP_PORT + 1  # snapshot on next port e.g. 8766
MOTION_THRESHOLD = int(os.environ.get("MOTION_THRESHOLD", 25))
MIN_MOTION_AREA  = int(os.environ.get("MIN_MOTION_AREA", 5000))
HA_URL           = os.environ.get("HA_URL", "http://homeassistant.local:8123").rstrip("/")
HA_TOKEN         = os.environ.get("HA_TOKEN", "").strip()

# Reduced resolution and FPS to ease load on Raspberry Pi 4
FRAME_WIDTH  = 1280
FRAME_HEIGHT = 720
FPS          = 15
POST_MOTION_FRAMES = FPS * 4

RTSP_PUBLISH_URL = f"rtsp://localhost:{RTSP_PORT}/stream"

# ==============================================================================
# Shared state
# ==============================================================================

motion_active    = False
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
# ffmpeg publisher
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
    log.info(f"Snapshot server listening on :{SNAPSHOT_PORT}")
    server.serve_forever()


# ==============================================================================
# Camera + streaming thread
# ==============================================================================

def camera_thread():
    global motion_active, ffmpeg_proc, latest_jpeg

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
                cam = pipeline.create(dai.node.Camera).build()
                video_out = cam.requestOutput(
                    (FRAME_WIDTH, FRAME_HEIGHT),
                    type=dai.ImgFrame.Type.BGR888p,
                    fps=FPS
                )
                q = video_out.createOutputQueue(maxSize=4, blocking=False)
                pipeline.start()
                log.info(f"Pipeline started — RTSP at rtsp://<ha-ip>:{RTSP_PORT}/stream")
                log.info(f"Snapshot at http://<ha-ip>:{SNAPSHOT_PORT}/snapshot")

                prev_gray = None
                post_motion_counter = 0

                while pipeline.isRunning():
                    if ffmpeg_proc.poll() is not None:
                        log.warning("ffmpeg died — restarting...")
                        ffmpeg_proc = start_ffmpeg()
                        time.sleep(1)

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

                    # Update snapshot
                    ok, jpeg_buf = cv2.imencode(
                        ".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 70]
                    )
                    if ok:
                        with latest_jpeg_lock:
                            latest_jpeg = jpeg_buf.tobytes()

                    # Push frame to ffmpeg
                    try:
                        ffmpeg_proc.stdin.write(display.tobytes())
                    except (BrokenPipeError, OSError):
                        log.warning("ffmpeg pipe broken — restarting...")
                        ffmpeg_proc = start_ffmpeg()
                        time.sleep(1)

        except Exception as e:
            log.error(f"Camera error: {e} — retrying in 10s...")
            motion_active = False
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
