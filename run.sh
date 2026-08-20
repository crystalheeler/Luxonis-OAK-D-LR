#!/usr/bin/with-contenv bashio

bashio::log.info "Starting OAK-D LR Camera bridge..."

# Read config options and export as environment variables for the Python script
export CAMERA_IP=$(bashio::config 'camera_ip')
export MJPEG_PORT=$(bashio::config 'mjpeg_port')
export MOTION_THRESHOLD=$(bashio::config 'motion_threshold')
export MIN_MOTION_AREA=$(bashio::config 'min_motion_area')
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')

bashio::log.info "Camera IP: ${CAMERA_IP}"
bashio::log.info "MJPEG stream will be available on port ${MJPEG_PORT}"

exec python3 /oak_bridge.py
