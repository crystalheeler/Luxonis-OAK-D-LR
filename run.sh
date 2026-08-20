#!/usr/bin/with-contenv bashio

bashio::log.info "Starting OAK-D LR Camera bridge..."

export CAMERA_IP=$(bashio::config 'camera_ip')
export MJPEG_PORT=$(bashio::config 'mjpeg_port')
export FPS=$(bashio::config 'fps')
export DETECTION_MODEL=$(bashio::config 'detection_model')

export DETECT_PEOPLE=$(bashio::config 'detect_people')
export CONFIDENCE_PEOPLE=$(bashio::config 'confidence_people')
export DETECT_ANIMALS=$(bashio::config 'detect_animals')
export CONFIDENCE_ANIMALS=$(bashio::config 'confidence_animals')
export DETECT_VEHICLES=$(bashio::config 'detect_vehicles')
export CONFIDENCE_VEHICLES=$(bashio::config 'confidence_vehicles')
export DETECT_FOOD=$(bashio::config 'detect_food')
export CONFIDENCE_FOOD=$(bashio::config 'confidence_food')
export DETECT_KITCHEN=$(bashio::config 'detect_kitchen')
export CONFIDENCE_KITCHEN=$(bashio::config 'confidence_kitchen')
export DETECT_FURNITURE=$(bashio::config 'detect_furniture')
export CONFIDENCE_FURNITURE=$(bashio::config 'confidence_furniture')
export DETECT_ELECTRONICS=$(bashio::config 'detect_electronics')
export CONFIDENCE_ELECTRONICS=$(bashio::config 'confidence_electronics')
export DETECT_SPORTS=$(bashio::config 'detect_sports')
export CONFIDENCE_SPORTS=$(bashio::config 'confidence_sports')
export DETECT_ACCESSORIES=$(bashio::config 'detect_accessories')
export CONFIDENCE_ACCESSORIES=$(bashio::config 'confidence_accessories')
export DETECT_OUTDOOR=$(bashio::config 'detect_outdoor')
export CONFIDENCE_OUTDOOR=$(bashio::config 'confidence_outdoor')
export OBJECT_OVERRIDES=$(bashio::config 'object_overrides')
export FILENAME_TAG_OBJECTS=$(bashio::config 'filename_tag_objects')

export STORAGE_ALERT_ENABLED=$(bashio::config 'storage_alert_enabled')
export STORAGE_ALERT_THRESHOLD=$(bashio::config 'storage_alert_threshold')
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')

bashio::log.info "Camera IP: ${CAMERA_IP}"
bashio::log.info "RTSP stream will be available on port ${MJPEG_PORT}"
bashio::log.info "FPS: ${FPS}"
bashio::log.info "Detection model: ${DETECTION_MODEL}"
bashio::log.info "Storage alerts: ${STORAGE_ALERT_ENABLED} (threshold: ${STORAGE_ALERT_THRESHOLD}%)"

# Start mediamtx RTSP server in background
mediamtx /mediamtx.yml &
MEDIAMTX_PID=$!
bashio::log.info "mediamtx RTSP server started (PID ${MEDIAMTX_PID})"

sleep 2

exec python3 /oak_bridge.py
