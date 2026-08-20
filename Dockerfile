ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm
FROM $BUILD_FROM

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-numpy \
    python3-opencv \
    libusb-1.0-0 \
    libusb-1.0-0-dev \
    udev \
    ffmpeg \
    curl \
    tar \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install mediamtx (RTSP server) for aarch64
RUN curl -L https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_arm64v8.tar.gz \
    | tar -xz -C /usr/local/bin mediamtx \
    && chmod +x /usr/local/bin/mediamtx

# Install depthai, depthai-nodes and requests
RUN pip3 install --no-cache-dir --break-system-packages \
    requests \
    "depthai>=2.24" \
    depthai-nodes \
    --extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/

# Pre-download Hub models (yolov6-nano, mobilenet-ssd) into depthai cache
COPY download_models.py /tmp/download_models.py
RUN python3 /tmp/download_models.py && rm /tmp/download_models.py

# Copy pre-converted YOLO11n NNArchive if it exists in the build context.
# Generate it on your PC first using prepare_yolo11n_windows.py,
# then place yolo11n.tar.xz in the oak_camera_app folder before building.
RUN mkdir -p /models
COPY yolo11n.tar.xz* /models/

COPY settings_page.py /
COPY run.sh /
COPY oak_bridge.py /
COPY mediamtx.yml /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
