# Multi-architecture image for the Home Assistant add-on.
#
# This replaces the old Home Assistant base image and the bashio shell script.
# oak_launcher.py reads /data/options.json directly, which is the same file
# bashio read, so the Supervisor interface is unchanged and one launcher now
# serves the add-on, the portable Windows build and a source run.
#
# Build with buildx so one tag carries both architectures:
#   docker buildx build --platform linux/amd64,linux/arm64 -f docker/Dockerfile .
FROM python:3.11-slim-bookworm

# TARGETARCH comes from buildx: amd64 or arm64.
ARG TARGETARCH
ARG MEDIAMTX_VERSION=1.9.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# libusb lets DepthAI talk to a USB device. A PoE camera needs only the network,
# but the library loads libusb at import time either way.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libusb-1.0-0 \
        udev \
        curl \
        ca-certificates \
        tar \
        xz-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# mediamtx ships one static binary per architecture.
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64) MTX_ARCH="linux_amd64"   ;; \
        arm64) MTX_ARCH="linux_arm64v8" ;; \
        *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL \
      "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/mediamtx_v${MEDIAMTX_VERSION}_${MTX_ARCH}.tar.gz" \
      | tar -xz -C /usr/local/bin mediamtx; \
    chmod +x /usr/local/bin/mediamtx; \
    mediamtx --version || true

# opencv-python-headless carries its own ffmpeg libraries and needs no X11,
# which the apt python3-opencv package would have pulled in.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
        --extra-index-url https://artifacts.luxonis.com/artifactory/luxonis-python-snapshot-local/ \
    && rm /tmp/requirements.txt

COPY src/ /app/

# Pre-download the Hub models into the DepthAI cache so a first start needs no
# internet access. yolo11n is not here: it is a local archive the user generates
# with tools/prepare_yolo11n_windows.py and drops into the models folder.
RUN python /app/download_models.py

WORKDIR /app

# oak_launcher.py reads /data/options.json, writes the mediamtx config, starts
# mediamtx, then runs the bridge. It also handles SIGTERM from the Supervisor.
CMD ["python", "/app/oak_launcher.py"]
