#!/usr/bin/with-contenv bashio

bashio::log.info "Starting OAK-D LR Camera bridge..."

export CAMERA_IP=$(bashio::config 'camera_ip')
export MJPEG_PORT=$(bashio::config 'mjpeg_port')
export FPS=$(bashio::config 'fps')
export DETECTION_MODEL=$(bashio::config 'detection_model')
export CONFIDENCE_THRESHOLD=$(bashio::config 'confidence_threshold')
export DETECT_PEOPLE=$(bashio::config 'detect_people')
export DETECT_ANIMALS=$(bashio::config 'detect_animals')
export DETECT_VEHICLES=$(bashio::config 'detect_vehicles')
export STORAGE_ALERT_ENABLED=$(bashio::config 'storage_alert_enabled')
export STORAGE_ALERT_THRESHOLD=$(bashio::config 'storage_alert_threshold')
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')

bashio::log.info "Camera IP: ${CAMERA_IP}"
bashio::log.info "RTSP stream will be available on port ${MJPEG_PORT}"
bashio::log.info "FPS: ${FPS}"
bashio::log.info "Detection model: ${DETECTION_MODEL}"
bashio::log.info "Detection — People: ${DETECT_PEOPLE}, Animals: ${DETECT_ANIMALS}, Vehicles: ${DETECT_VEHICLES}"
bashio::log.info "Confidence threshold: ${CONFIDENCE_THRESHOLD}"
bashio::log.info "Storage alerts: ${STORAGE_ALERT_ENABLED} (threshold: ${STORAGE_ALERT_THRESHOLD}%)"

# Start mediamtx RTSP server in background
mediamtx /mediamtx.yml &
MEDIAMTX_PID=$!
bashio::log.info "mediamtx RTSP server started (PID ${MEDIAMTX_PID})"

sleep 2

exec python3 /oak_bridge.py
