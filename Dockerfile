ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm
FROM $BUILD_FROM

# The HA base image is Debian-based — use apt, not apk
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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install depthai via pip using Luxonis's ARM-compatible wheel index
RUN pip3 install --no-cache-dir --break-system-packages \
    requests \
    "depthai>=2.24" \
    --extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/

# Copy app files
COPY run.sh /
COPY oak_bridge.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
