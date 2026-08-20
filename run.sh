#!/usr/bin/with-contenv bashio

bashio::log.info "Starting OAK-D LR Camera bridge..."

export CAMERA_IP=$(bashio::config 'camera_ip')
export MJPEG_PORT=$(bashio::config 'mjpeg_port')
export MOTION_THRESHOLD=$(bashio::config 'motion_threshold')
export MIN_MOTION_AREA=$(bashio::config 'min_motion_area')
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')

bashio::log.info "Camera IP: ${CAMERA_IP}"
bashio::log.info "RTSP stream will be available on port ${MJPEG_PORT}"

# Start mediamtx RTSP server in background
mediamtx /mediamtx.yml &
MEDIAMTX_PID=$!
bashio::log.info "mediamtx RTSP server started (PID ${MEDIAMTX_PID})"

sleep 2

# Start the Python bridge
exec python3 /oak_bridge.py
